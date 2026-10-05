"""Feedback on a project: a public form for its users, and a list for managers.

People who use a client's system - inspectors, for example - are not Sentinel
users. They send complaints, change requests, suggestions and questions
through a public link per project (FeedbackLink), with screenshots. Managers
see it all on the project's Feedback page, answer it, move it through a status,
add their own, and turn any of it into a task.

The public endpoints trust nothing but the token in the link, the same rule as
the client request sheets. Screenshots are opened and re-saved by Pillow on the
way in - which proves they are images and drops hidden data such as a phone's
GPS position - and stored outside MEDIA_ROOT, served only to signed-in staff.
"""
import io
import json
import logging
import secrets

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.http import FileResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods
from PIL import Image, UnidentifiedImageError

from . import activity
from .client_requests import _base_url
from .models import Feedback, FeedbackAttachment, FeedbackLink, ProjectList, ProjectMeta, ProjectTask
from .views import _require_module

logger = logging.getLogger(__name__)

MAX_FILES = 6
MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_SIDE = 3000                     # longest edge kept, in pixels
PER_HOUR_PER_SENDER = 10            # submissions through one link from one address
KINDS = dict(Feedback.KIND_CHOICES)
STATUSES = dict(Feedback.STATUS_CHOICES)


def _is_admin(request):
    return request.user.is_authenticated and request.user.is_superuser


def _link_url(link):
    return f'{_base_url()}/feedback/{link.token}'


def _client_ip(request):
    fwd = request.META.get('HTTP_X_FORWARDED_FOR', '')
    return (fwd.split(',')[0].strip() if fwd else request.META.get('REMOTE_ADDR', '')) or 'unknown'


def _attachment(a):
    return {'id': a.id, 'name': a.original_name, 'width': a.width, 'height': a.height,
            'url': f'/api/feedback/attachments/{a.id}'}


def _dict(f):
    return {
        'id': f.id, 'kind': f.kind, 'kind_display': KINDS.get(f.kind, f.kind),
        'title': f.title, 'description': f.description, 'area': f.area,
        'submitter_name': f.submitter_name, 'submitter_email': f.submitter_email,
        'submitter_role': f.submitter_role,
        'status': f.status, 'status_display': STATUSES.get(f.status, f.status),
        'manager_note': f.manager_note, 'source': f.source,
        'created_by': (f.created_by.get_full_name() or f.created_by.username) if f.created_by_id else '',
        'task': {'id': f.task_id, 'title': f.task.title, 'status': f.task.status} if f.task_id else None,
        'created_at': f.created_at.isoformat(),
        'attachments': [_attachment(a) for a in f.attachments.all()],
    }


def _save_screenshot(feedback, upload):
    """Check an upload is an image and keep a clean re-saved copy. Returns an error or ''."""
    if upload.size > MAX_UPLOAD_BYTES:
        return f'"{upload.name}" is over {MAX_UPLOAD_BYTES // (1024 * 1024)} MB.'
    try:
        img = Image.open(upload)
        img.verify()                     # structure check; the image must be reopened after
        upload.seek(0)
        img = Image.open(upload)
        img.load()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError):
        return f'"{upload.name}" is not an image Sentinel can read. PNG, JPG, GIF or WebP please.'
    if img.width * img.height > 40_000_000:
        return f'"{upload.name}" is too large an image.'
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    keep_alpha = img.mode in ('RGBA', 'LA', 'P')
    out = io.BytesIO()
    if keep_alpha or (img.format or '').upper() in ('PNG', 'GIF'):
        img.convert('RGBA' if keep_alpha else 'RGB').save(out, 'PNG', optimize=True)
        ext, ctype = '.png', 'image/png'
    else:
        img.convert('RGB').save(out, 'JPEG', quality=88)
        ext, ctype = '.jpg', 'image/jpeg'
    a = FeedbackAttachment(feedback=feedback, original_name=(upload.name or 'screenshot')[:300],
                           content_type=ctype, width=img.width, height=img.height,
                           size=out.tell())
    a.file.save(f'shot{ext}', ContentFile(out.getvalue()), save=True)
    return ''


def _create(request, project, source):
    """A Feedback from a multipart form, with its screenshots. Returns (feedback, error)."""
    p = request.POST
    title = (p.get('title') or '').strip()[:200]
    if not title:
        return None, 'Give it a short title.'
    files = request.FILES.getlist('screenshots')
    if len(files) > MAX_FILES:
        return None, f'At most {MAX_FILES} screenshots, please.'
    f = Feedback.objects.create(
        project_name=project.name,
        kind=p.get('kind') if p.get('kind') in KINDS else 'problem',
        title=title, description=(p.get('description') or '').strip()[:8000],
        area=(p.get('area') or '').strip()[:200],
        submitter_name=(p.get('name') or '').strip()[:150],
        submitter_email=(p.get('email') or '').strip()[:254],
        submitter_role=(p.get('role') or '').strip()[:100],
        source=source, created_by=request.user if source == 'staff' else None)
    problems = [msg for msg in (_save_screenshot(f, u) for u in files) if msg]
    return f, ' '.join(problems)


# ── public, by link ─────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_public_feedback(request, token):
    link = FeedbackLink.objects.filter(token=token, is_active=True).first()
    project = ProjectMeta.objects.filter(name=link.project_name).first() if link else None
    if project is None:
        return JsonResponse({'detail': 'This feedback link is not valid any more.'}, status=404)

    if request.method == 'GET':
        return JsonResponse({
            'project': project.name, 'client': project.client,
            'kinds': [{'value': k, 'label': v} for k, v in KINDS.items()],
            'max_files': MAX_FILES, 'max_mb': MAX_UPLOAD_BYTES // (1024 * 1024),
        })

    # A field people never see; anything filled in is a bot. Answered as if it
    # worked, so the bot learns nothing.
    if (request.POST.get('website') or '').strip():
        return JsonResponse({'ok': True, 'reference': 0}, status=201)
    key = f'feedback:{token}:{_client_ip(request)}'
    sent = cache.get(key, 0)
    if sent >= PER_HOUR_PER_SENDER:
        return JsonResponse({'detail': 'That is a lot of feedback in one hour - please try again later.'},
                            status=429)
    f, problem = _create(request, project, 'form')
    if f is None:
        return JsonResponse({'detail': problem}, status=400)
    cache.set(key, sent + 1, 3600)
    logger.info('[feedback] %s sent feedback %s on %s', f.submitter_name or 'someone', f.id, project.name)
    return JsonResponse({'ok': True, 'reference': f.id, 'warning': problem}, status=201)


# ── staff ───────────────────────────────────────────────────────────────────

@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_project_feedback(request, name):
    """A project's feedback (GET), or add some as staff (POST, multipart)."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    project = ProjectMeta.objects.filter(name=name).first()
    if project is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    if request.method == 'POST':
        f, problem = _create(request, project, 'staff')
        if f is None:
            return JsonResponse({'detail': problem}, status=400)
        activity.record(request, 'created', 'feedback', obj=f, label=f.title, project=name)
        return JsonResponse({'feedback': _dict(f), 'warning': problem}, status=201)

    rows = (Feedback.objects.filter(project_name=name)
            .select_related('created_by', 'task').prefetch_related('attachments'))
    link = FeedbackLink.objects.filter(project_name=name).first()
    counts = {k: 0 for k in STATUSES}
    for f in rows:
        counts[f.status] = counts.get(f.status, 0) + 1
    return JsonResponse({
        'feedback': [_dict(f) for f in rows],
        'counts': counts,
        'kinds': [{'value': k, 'label': v} for k, v in KINDS.items()],
        'statuses': [{'value': k, 'label': v} for k, v in STATUSES.items()],
        'link': {'url': _link_url(link), 'token': link.token, 'active': link.is_active} if link else None,
        'can_manage': True, 'is_admin': _is_admin(request),
        'max_files': MAX_FILES,
    })


def _get(request, name, pk):
    err = _require_module(request, 'tasks')
    if err:
        return None, err
    f = Feedback.objects.filter(id=pk, project_name=name).first()
    if f is None:
        return None, JsonResponse({'detail': 'Not found.'}, status=404)
    return f, None


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_project_feedback_update(request, name, pk):
    """Status, the manager's answer, or the type."""
    f, err = _get(request, name, pk)
    if err:
        return err
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = {}
    if data.get('status') in STATUSES:
        f.status = data['status']
    if data.get('kind') in KINDS:
        f.kind = data['kind']
    if 'manager_note' in data:
        f.manager_note = str(data.get('manager_note') or '').strip()[:4000]
    f.save()
    return JsonResponse({'feedback': _dict(f)})


@csrf_exempt
@require_http_methods(["POST"])
def api_project_feedback_task(request, name, pk):
    """Turn a piece of feedback into a task on the project's "Feedback" list."""
    f, err = _get(request, name, pk)
    if err:
        return err
    if f.task_id:
        return JsonResponse({'feedback': _dict(f)})
    who = ', '.join(x for x in (f.submitter_name, f.submitter_role) if x) or 'staff'
    body = '\n\n'.join(x for x in (
        f.description,
        f'From feedback #{f.id} by {who} on {f.created_at:%d %b %Y}.' + (f' Where: {f.area}.' if f.area else ''),
    ) if x)
    ProjectList.objects.get_or_create(project_name=name, workspace=None, name='Feedback')
    f.task = ProjectTask.objects.create(
        title=f'{KINDS.get(f.kind, "Feedback")}: {f.title}'[:255], description=body,
        project_name=name, list_name='Feedback', status='todo',
        priority='high' if f.kind == 'problem' else 'medium')
    if f.status in ('new', 'reviewing'):
        f.status = 'planned'
    f.save()
    activity.record(request, 'created', 'task', obj=f.task, label=f.task.title,
                    detail=f'from feedback #{f.id}', project=name)
    return JsonResponse({'feedback': _dict(f)}, status=201)


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_project_feedback_delete(request, name, pk):
    f, err = _get(request, name, pk)
    if err:
        return err
    if not _is_admin(request):
        return JsonResponse({'detail': 'Only administrators can delete feedback.'}, status=403)
    for a in f.attachments.all():
        a.file.delete(save=False)
    title = f.title
    f.delete()
    activity.record(request, 'deleted', 'feedback', object_id=pk, label=title, project=name)
    return JsonResponse({'ok': True})


@csrf_exempt
@require_http_methods(["POST"])
def api_project_feedback_link(request, name):
    """Make the public link, or turn it off, on, or replace it with a new one."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    if not ProjectMeta.objects.filter(name=name).exists():
        return JsonResponse({'detail': 'Project not found.'}, status=404)
    try:
        action = json.loads(request.body or b'{}').get('action')
    except json.JSONDecodeError:
        action = None
    link = FeedbackLink.objects.filter(project_name=name).first()
    if action in ('create', 'regenerate'):
        token = secrets.token_urlsafe(24)
        if link:
            link.token, link.is_active = token, True
            link.save(update_fields=['token', 'is_active'])
        else:
            link = FeedbackLink.objects.create(project_name=name, token=token, created_by=request.user)
    elif action in ('disable', 'enable') and link:
        link.is_active = action == 'enable'
        link.save(update_fields=['is_active'])
    else:
        return JsonResponse({'detail': 'Unknown action.'}, status=400)
    return JsonResponse({'link': {'url': _link_url(link), 'token': link.token, 'active': link.is_active}})


MAX_RECIPIENTS = 50


def _invite_email(project, url, sender, message):
    """The email someone gets when they are sent the form: who asked, why,
    and one button. It works for anyone - the form needs no login."""
    from . import email_layout as el
    subject = f'Your feedback on {project}'
    blocks = []
    if message:
        blocks.append(el.para(message))
    blocks += [
        el.para(f'{sender} has asked for your feedback on {project}. Use the form to report a '
                'problem, ask for a change, suggest an improvement or ask a question - you can '
                'add screenshots, and you do not need an account.'),
        el.button('Open the feedback form', url),
        el.para('Or copy this link into your browser:', muted=True, size=13),
        el.raw(f'<p style="margin:0 0 14px;font-size:13px">{el.link(url)}</p>'),
    ]
    html = el.render(subject, blocks,
                     preheader=f'{sender} would like your feedback on {project}.',
                     footer_note='You can use the same link as often as you like.')
    text = '\n\n'.join(x for x in (
        message,
        f'{sender} has asked for your feedback on {project}. Use the form to report a problem, '
        'ask for a change, suggest an improvement or ask a question. You can add screenshots, '
        'and you do not need an account.',
        f'Open the feedback form: {url}',
    ) if x)
    return subject, html, text


@csrf_exempt
@require_http_methods(["POST"])
def api_project_feedback_send(request, name):
    """Email the feedback form to anyone - a client, an inspector, a supplier -
    with or without a Sentinel login. Makes the link first if there isn't one."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email
    from .views import _graph_send_simple
    from . import email_layout as el

    err = _require_module(request, 'tasks')
    if err:
        return err
    if not ProjectMeta.objects.filter(name=name).exists():
        return JsonResponse({'detail': 'Project not found.'}, status=404)
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = {}

    raw = data.get('recipients') or []
    if isinstance(raw, str):
        raw = [raw]
    addresses, seen, invalid = [], set(), []
    for chunk in raw:
        for a in str(chunk).replace(';', ',').replace('\n', ',').split(','):
            a = a.strip().strip('<>').strip()
            if not a or a.lower() in seen:
                continue
            try:
                validate_email(a)
            except ValidationError:
                invalid.append(a)
                continue
            seen.add(a.lower())
            addresses.append(a)
    if invalid:
        return JsonResponse({'detail': f'Not an email address: {", ".join(invalid[:5])}.'}, status=400)
    if not addresses:
        return JsonResponse({'detail': 'Add at least one email address.'}, status=400)
    if len(addresses) > MAX_RECIPIENTS:
        return JsonResponse({'detail': f'Send to at most {MAX_RECIPIENTS} people at a time.'}, status=400)

    link = FeedbackLink.objects.filter(project_name=name).first()
    if link is None:
        link = FeedbackLink.objects.create(project_name=name, token=secrets.token_urlsafe(24),
                                           created_by=request.user)
    elif not link.is_active:
        return JsonResponse({'detail': 'The feedback link is turned off. Turn it on before sending it.'},
                            status=400)

    url = _link_url(link)
    sender = request.user.get_full_name() or request.user.username
    subject, html, text = _invite_email(name, url, sender, str(data.get('message') or '').strip()[:2000])
    banner = el.banner_attachment()
    sent, failed = [], []
    for address in addresses:
        ok, msg = _graph_send_simple(address, subject, body_html=html, body_text=text,
                                     attachments=[banner] if banner else [])
        if ok:
            sent.append(address)
        else:
            failed.append(address)
            logger.error('[feedback] sending the form to %s failed: %s', address, msg)

    if sent:
        activity.record(request, 'sent', 'feedback', label='Feedback form',
                        detail=f'to {", ".join(sent)}'[:300], project=name)
    body = {'sent': sent, 'failed': failed, 'url': url,
            'link': {'url': url, 'token': link.token, 'active': link.is_active}}
    if not sent:
        return JsonResponse({**body, 'detail': 'The email could not be sent. Try again in a minute.'}, status=502)
    return JsonResponse(body)


@require_http_methods(["GET"])
def api_feedback_attachment(request, pk):
    """A screenshot, shown to signed-in staff only."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    a = FeedbackAttachment.objects.filter(id=pk).first()
    if a is None or not a.file:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    try:
        fh = a.file.open('rb')
    except (OSError, ValueError):
        return JsonResponse({'detail': 'That screenshot is no longer on disk.'}, status=410)
    # Shown inline (it was re-saved by Pillow, so it is a plain image), with
    # nothing else allowed to run in its context.
    resp = FileResponse(fh, content_type=a.content_type)
    resp['Content-Disposition'] = 'inline'
    resp['X-Content-Type-Options'] = 'nosniff'
    resp['Content-Security-Policy'] = "default-src 'none'; sandbox"
    resp['Cache-Control'] = 'private, max-age=3600'
    return resp
