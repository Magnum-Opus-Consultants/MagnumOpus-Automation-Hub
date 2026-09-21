"""The handbook: how we work, and how to get access to the things we run.

Two kinds of content, deliberately kept apart:

* Articles - written rules, policies and how-tos. Anyone with the module can read.
* Server access - hostnames, SSH users and passwords. Superusers only, and the
  password is never included in a list response; it is fetched one server at a
  time so a single careless screen-share cannot leak the estate.
"""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import HandbookArticle, ServerRecord
from .views import _require_module

logger = logging.getLogger(__name__)

_CATEGORIES = [c[0] for c in HandbookArticle.CATEGORY_CHOICES]


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _article(a, full=False):
    out = {
        'id': a.id,
        'title': a.title,
        'category': a.category,
        'category_display': a.get_category_display(),
        'summary': a.summary,
        'is_pinned': a.is_pinned,
        'for_new_starters': a.for_new_starters,
        'order': a.order,
        'updated_at': a.updated_at.isoformat() if a.updated_at else None,
        'updated_by': a.updated_by.username if a.updated_by else '',
        'length': len(a.body or ''),
    }
    if full:
        out['body'] = a.body
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Articles
# ══════════════════════════════════════════════════════════════════════════════

def api_handbook(request):
    """Every article. Bodies are included - they are short and the page shows one
    immediately, so a second round trip per article would only add latency."""
    err = _require_module(request, 'handbook')
    if err:
        return err

    qs = HandbookArticle.objects.select_related('updated_by')
    category = (request.GET.get('category') or '').strip()
    if category:
        qs = qs.filter(category=category)

    rows = [_article(a, full=True) for a in qs]
    return JsonResponse({
        'articles': rows,
        'total': len(rows),
        'categories': list(HandbookArticle.CATEGORY_CHOICES),
        'new_starter_count': sum(1 for r in rows if r['for_new_starters']),
    })


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_handbook_save(request, pk=None):
    err = _require_module(request, 'handbook')
    if err:
        return err
    data = _body(request)

    a = HandbookArticle.objects.filter(pk=pk).first() if pk else None
    if pk and a is None:
        return JsonResponse({'detail': 'Article not found.'}, status=404)
    if a is None:
        a = HandbookArticle()

    if 'title' in data or a.pk is None:
        title = (data.get('title') or '').strip()
        if not title:
            return JsonResponse({'detail': 'title is required.'}, status=400)
        a.title = title[:200]
    if 'category' in data:
        if data['category'] not in _CATEGORIES:
            return JsonResponse(
                {'detail': 'category must be one of: ' + ', '.join(_CATEGORIES) + '.'},
                status=400)
        a.category = data['category']
    for f in ('summary', 'body'):
        if f in data:
            setattr(a, f, (data.get(f) or '').strip())
    for f in ('is_pinned', 'for_new_starters'):
        if f in data:
            setattr(a, f, bool(data.get(f)))
    if 'order' in data:
        try:
            a.order = int(data.get('order') or 0)
        except (TypeError, ValueError):
            return JsonResponse({'detail': 'order must be a whole number.'}, status=400)

    a.updated_by = request.user if request.user.is_authenticated else None
    a.save()
    return JsonResponse(_article(a, full=True), status=201 if pk is None else 200)


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_handbook_delete(request, pk):
    err = _require_module(request, 'handbook')
    if err:
        return err
    a = HandbookArticle.objects.filter(pk=pk).first()
    if a is None:
        return JsonResponse({'detail': 'Article not found.'}, status=404)
    title = a.title
    a.delete()
    return JsonResponse({'ok': True, 'deleted': title})


# ══════════════════════════════════════════════════════════════════════════════
# Server access
# ══════════════════════════════════════════════════════════════════════════════

def _server_row(srv, with_secrets=False):
    row = {
        'id': srv.id,
        'name': srv.name,
        'company': srv.company,
        'group': srv.group,
        'ip': srv.ip,
        'hostname': srv.hostname,
        'os': srv.os,
        'provider': srv.provider,
        'ssh_user': srv.ssh_user,
        'ssh_ip': srv.ssh_ip,
        'ssh_key': srv.ssh_key,
        'netbird_ip': srv.netbird_ip,
        'lan_ip': srv.lan_ip,
        'access': srv.access,
        'notes': srv.notes,
        # Whether a password exists, without sending it.
        'has_password': bool(srv.password),
    }
    if with_secrets:
        row['password'] = srv.password
    return row


def api_server_access(request):
    """Server access details. Passwords are never in this response."""
    err = _require_module(request, 'handbook')
    if err:
        return err
    if not request.user.is_superuser:
        return JsonResponse(
            {'detail': 'Server access details are restricted to administrators.'},
            status=403)

    rows = [_server_row(s) for s in ServerRecord.objects.all().order_by('order', 'name')]
    return JsonResponse({
        'servers': rows,
        'total': len(rows),
        'with_passwords': sum(1 for r in rows if r['has_password']),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_server_secret(request, pk):
    """Reveal one server's password.

    A POST for one record at a time, and logged: a GET returning every password
    at once is the thing that turns a shared screen into an incident.
    """
    err = _require_module(request, 'handbook')
    if err:
        return err
    if not request.user.is_superuser:
        return JsonResponse(
            {'detail': 'Server passwords are restricted to administrators.'}, status=403)

    srv = ServerRecord.objects.filter(pk=pk).first()
    if srv is None:
        return JsonResponse({'detail': 'Server not found.'}, status=404)
    if not srv.password:
        return JsonResponse({'detail': 'No password is stored for this server.'}, status=404)

    logger.warning('[handbook] %s revealed the password for server %s (%s)',
                   request.user.username, srv.id, srv.name)
    return JsonResponse({'id': srv.id, 'name': srv.name, 'password': srv.password})
