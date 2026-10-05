"""Resetting a user's password: set by an administrator, or chosen by the user
from an emailed link.

The link carries Django's own password-reset token (django.contrib.auth.tokens).
It needs no table of its own: the token is signed from the user's current
password hash and last login, so it stops working the moment the password
changes or the user signs in, and expires after PASSWORD_RESET_TIMEOUT
(three days by default). The public endpoints answer the same way whether or
not the account exists, and are rate-limited per address.
"""
import json
import logging

from django.conf import settings
from django.contrib.auth import update_session_auth_hash
from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.http import JsonResponse
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import activity
from .client_requests import _base_url
from .views import _require_admin

logger = logging.getLogger(__name__)

MIN_LENGTH = 8
ATTEMPTS_PER_HOUR = 10


def password_problem(password, user=None):
    """Why a new password won't do, or '' if it is fine. The platform has no
    AUTH_PASSWORD_VALIDATORS, so these are the floor."""
    if len(password) < MIN_LENGTH:
        return f'Use at least {MIN_LENGTH} characters.'
    if password.isdigit():
        return 'Use letters as well as numbers.'
    if user is not None and password.lower() in {user.username.lower(), (user.email or '').lower()}:
        return "Don't use the username or email address as the password."
    return ''


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _days():
    return max(1, round(getattr(settings, 'PASSWORD_RESET_TIMEOUT', 259200) / 86400))


def _client_ip(request):
    fwd = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (fwd.split(',')[0].strip() if fwd else request.META.get('REMOTE_ADDR', '')) or 'unknown'


def _rate_limited(request):
    key = f'pwreset:{_client_ip(request)}'
    count = cache.get(key, 0)
    if count >= ATTEMPTS_PER_HOUR:
        return True
    cache.set(key, count + 1, 3600)
    return False


# ── administrators ──────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["POST"])
def api_user_set_password(request, pk):
    """An administrator sets someone's password directly."""
    err = _require_admin(request)
    if err:
        return err
    user = User.objects.filter(pk=pk).first()
    if user is None:
        return JsonResponse({'detail': 'User not found.'}, status=404)
    password = str(_body(request).get('password') or '')
    if problem := password_problem(password, user):
        return JsonResponse({'detail': problem}, status=400)
    user.set_password(password)
    user.save(update_fields=['password'])
    # Changing your own password would otherwise sign you out on the spot.
    if user.pk == request.user.pk:
        update_session_auth_hash(request, user)
    activity.record(request, 'updated', 'user', obj=user, label=user.username, detail='password set')
    return JsonResponse({'ok': True})


def _reset_email(user, link, sender):
    from . import email_layout as el
    name = user.get_full_name() or user.username
    subject = 'Reset your Sentinel password'
    days = _days()
    blocks = [
        el.para(f'Hi {name},'),
        el.para(f'{sender} has sent you a link to choose a new password for Sentinel. '
                f'Your username is {user.username}.'),
        el.button('Choose a new password', link),
        el.para(f'The link works once and expires in {days} day{"" if days == 1 else "s"}. '
                'If you did not expect this, you can ignore it - your password stays the same.',
                muted=True, size=13),
        el.raw(f'<p style="margin:0 0 14px;font-size:13px">{el.link(link)}</p>'),
    ]
    html = el.render(subject, blocks, preheader='Choose a new password for Sentinel.')
    text = (f'Hi {name},\n\n{sender} has sent you a link to choose a new password for Sentinel. '
            f'Your username is {user.username}.\n\nChoose a new password: {link}\n\n'
            f'The link works once and expires in {days} days. If you did not expect this, ignore it.')
    return subject, html, text


@csrf_exempt
@require_http_methods(["POST"])
def api_user_send_reset(request, pk):
    """Email someone a link to choose their own new password."""
    from . import email_layout as el
    from .views import _graph_send_simple

    err = _require_admin(request)
    if err:
        return err
    user = User.objects.filter(pk=pk).first()
    if user is None:
        return JsonResponse({'detail': 'User not found.'}, status=404)
    if not (user.email or '').strip():
        return JsonResponse({'detail': 'This user has no email address. Add one and save first.'}, status=400)
    if not user.is_active:
        return JsonResponse({'detail': 'This account is switched off, so it cannot sign in.'}, status=400)

    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    link = f'{_base_url()}/reset-password?uid={uid}&token={token}'
    sender = request.user.get_full_name() or request.user.username
    subject, html, text = _reset_email(user, link, sender)
    banner = el.banner_attachment()
    ok, msg = _graph_send_simple(user.email.strip(), subject, body_html=html, body_text=text,
                                 attachments=[banner] if banner else [])
    if not ok:
        logger.error('[password-reset] email to %s failed: %s', user.email, msg)
        return JsonResponse({'detail': 'The email could not be sent. Try again in a minute.'}, status=502)
    activity.record(request, 'sent', 'user', obj=user, label=user.username,
                    detail=f'password reset link to {user.email}')
    return JsonResponse({'ok': True, 'email': user.email, 'days': _days()})


# ── the person with the link ────────────────────────────────────────────────

def _user_for(uid, token):
    try:
        user = User.objects.filter(pk=int(force_str(urlsafe_base64_decode(uid or '')))).first()
    except (TypeError, ValueError, OverflowError):
        return None
    if user is None or not user.is_active or not default_token_generator.check_token(user, token or ''):
        return None
    return user


@csrf_exempt
@require_http_methods(["GET"])
def api_password_reset_check(request):
    """Whether a reset link still works, and whose it is."""
    if _rate_limited(request):
        return JsonResponse({'valid': False, 'detail': 'Too many attempts. Try again in an hour.'}, status=429)
    user = _user_for(request.GET.get('uid'), request.GET.get('token'))
    if user is None:
        return JsonResponse({'valid': False})
    return JsonResponse({'valid': True, 'username': user.username, 'min_length': MIN_LENGTH})


@csrf_exempt
@require_http_methods(["POST"])
def api_password_reset_confirm(request):
    """Set the new password from a reset link. The link stops working after."""
    if _rate_limited(request):
        return JsonResponse({'detail': 'Too many attempts. Try again in an hour.'}, status=429)
    data = _body(request)
    user = _user_for(data.get('uid'), data.get('token'))
    if user is None:
        return JsonResponse({'detail': 'This link has expired or has already been used. '
                                       'Ask an administrator to send a new one.'}, status=400)
    password = str(data.get('password') or '')
    if problem := password_problem(password, user):
        return JsonResponse({'detail': problem}, status=400)
    user.set_password(password)
    user.save(update_fields=['password'])
    logger.info('[password-reset] %s chose a new password', user.username)
    return JsonResponse({'ok': True, 'username': user.username})
