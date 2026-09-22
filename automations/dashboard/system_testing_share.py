"""Shared reviewer links: one project, three columns, no account.

A client reviews alongside the team and records their own verdict. Handing them
a platform login would give them every project, so a share link carries a token
scoped to a single project and to exactly the three fields a reviewer fills in:

    Client Test / Review Status   ->  iteration.tested
    Readiness Status              ->  iteration.readiness
    Client Feedback / Comments    ->  iteration.client_feedback

Nothing else is reachable. The endpoints below never look at request.user, never
accept a project id from the caller, and refuse any other field - so the limits
are enforced by what the code can do, not by what the shared page happens to
render.
"""
import json
import logging

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import TestProject, TestShareLink, TestIteration, TestItem
from .views import _require_module

logger = logging.getLogger(__name__)

MODULE = 'system_testing'

# The only fields a shared link may write. Anything else in the payload is
# ignored rather than trusted.
EDITABLE = ('tested', 'readiness', 'client_feedback')


def _base_url():
    return (getattr(settings, 'PUBLIC_BASE_URL', '')
            or 'https://workspace.moc-pty.com').rstrip('/')


def _link_url(share):
    return f'{_base_url()}/readiness/{share.token}'


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _share_json(share):
    return {
        'id': share.id,
        'token': share.token,
        'label': share.label,
        'is_active': share.is_active,
        'url': _link_url(share),
        'path': f'/readiness/{share.token}',
        'created_at': share.created_at.isoformat() if share.created_at else None,
        'created_by': share.created_by.username if share.created_by else '',
        'last_opened_at': (share.last_opened_at.isoformat()
                           if share.last_opened_at else None),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Owner side: create, list and revoke links
# ══════════════════════════════════════════════════════════════════════════════

@require_http_methods(["GET"])
def api_share_links(request, pk):
    err = _require_module(request, MODULE)
    if err:
        return err
    p = TestProject.objects.filter(pk=pk).first()
    if p is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)
    return JsonResponse(
        {'links': [_share_json(s) for s in p.share_links.all()]})


@csrf_exempt
@require_http_methods(["POST"])
def api_share_link_create(request, pk):
    err = _require_module(request, MODULE)
    if err:
        return err
    p = TestProject.objects.filter(pk=pk).first()
    if p is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    data = _body(request)
    share = TestShareLink.objects.create(
        project=p,
        token=TestShareLink.new_token(),
        label=(data.get('label') or '').strip()[:120],
        created_by=request.user if request.user.is_authenticated else None)
    return JsonResponse({'link': _share_json(share)})


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_share_link_revoke(request, pk):
    """Revoke rather than delete, so a link that leaked stays dead on the record."""
    err = _require_module(request, MODULE)
    if err:
        return err
    share = TestShareLink.objects.filter(pk=pk).first()
    if share is None:
        return JsonResponse({'detail': 'Link not found.'}, status=404)
    share.is_active = False
    share.save(update_fields=['is_active'])
    return JsonResponse({'link': _share_json(share)})


# ══════════════════════════════════════════════════════════════════════════════
# Reviewer side: no session, token only
# ══════════════════════════════════════════════════════════════════════════════

def _resolve(token):
    """(share, None) for a usable link, or (None, JsonResponse) explaining why not."""
    share = TestShareLink.objects.filter(token=token).select_related('project').first()
    if share is None:
        return None, JsonResponse({'detail': 'This link is not valid.'}, status=404)
    if not share.is_active:
        return None, JsonResponse(
            {'detail': 'This link has been revoked. Ask for a new one.'}, status=403)
    return share, None


def _public_item(r):
    """One row as a reviewer sees it.

    The issue, its description and the development status are shown because a
    verdict without them is meaningless, but they are read-only here - the three
    fields in EDITABLE are the reviewer's to set.
    """
    it = r.item
    return {
        'iteration_id': r.id,
        'issue': it.issue,
        'description': it.description,
        'bucket_display': it.get_bucket_display(),
        'dev_status_display': r.get_dev_status_display(),
        'pass_number': r.number,
        'carried_over': r.number > 1,
        'tested': r.tested,
        'tested_display': r.get_tested_display(),
        'readiness': r.readiness,
        'readiness_display': r.get_readiness_display(),
        'client_feedback': r.client_feedback,
    }


@require_http_methods(["GET"])
def public_readiness(request, token):
    """The one project this link is for. No ids are accepted from the caller."""
    share, err = _resolve(token)
    if err:
        return err

    # Imported here rather than at module scope: system_testing imports this
    # module's urls indirectly, and a top-level import would be circular.
    from .system_testing import (_rollup, _sum_rollups, _vocabularies,
                                 window_label)

    TestShareLink.objects.filter(pk=share.pk).update(last_opened_at=timezone.now())

    p = share.project
    areas, rollups = [], []
    for a in p.areas.prefetch_related('versions__iterations__item'):
        versions = list(a.versions.all())
        sheets = []
        for v in versions:
            rows = sorted(v.iterations.select_related('item'),
                          key=lambda r: (r.item.order, r.item_id))
            sheets.append({
                'version_id': v.id,
                'label': v.label,
                'rollup': _rollup(rows),
                'items': [_public_item(r) for r in rows],
            })
        latest = sheets[-1] if sheets else None
        roll = latest['rollup'] if latest else _rollup([])
        rollups.append(roll)
        areas.append({
            'id': a.id,
            'name': a.name,
            'current_version': versions[-1].label if versions else '',
            'current_version_id': latest['version_id'] if latest else None,
            'rollup': roll,
            'sheets': sheets,
        })

    vocab = _vocabularies()
    return JsonResponse({
        'project': {
            'name': p.name,
            'client': p.client,
            'summary': p.summary,
            'testing_window': window_label(p),
            'version_label': p.version_label,
            'rollup': _sum_rollups(rollups),
        },
        'areas': areas,
        # Only the vocabularies a reviewer can choose from, plus the legend so
        # the definitions they are judging against are in front of them.
        'vocabularies': {
            'tested': vocab['tested'],
            'readiness': vocab['readiness'],
            'legend': vocab['legend'],
        },
        'editable': list(EDITABLE),
        'from_company': 'Magnum Opus Consultants',
    })


def _since(request):
    """The `since` timestamp, tolerating an unencoded "+" in the offset.

    A query string decodes "+" as a space, so an ISO timestamp that was not
    URL-encoded arrives as "...T10:00:00 00:00" and will not parse. Falling back
    to "everything changed" would send the whole sheet back and cause exactly
    the full re-render this endpoint exists to avoid, so the space is repaired
    before giving up.
    """
    raw = (request.GET.get('since') or '').strip()
    if not raw:
        return None
    stamp = parse_datetime(raw)
    if stamp is None and ' ' in raw:
        stamp = parse_datetime(raw.replace(' ', '+'))
    return stamp


@require_http_methods(["GET"])
def public_readiness_changes(request, token):
    """The reviewer's half of the live sync.

    Same reasoning as the platform side: the team edits the same rows, and the
    reviewer should see that without the page reloading under them mid-sentence.
    Only the passes touched since `since` come back.
    """
    share, err = _resolve(token)
    if err:
        return err

    from .system_testing import _rollup

    since = _since(request)
    now = timezone.now()

    changed, areas = [], []
    for a in share.project.areas.prefetch_related('versions__iterations__item'):
        sheets = []
        for v in a.versions.all():
            rows = sorted(v.iterations.select_related('item'),
                          key=lambda r: (r.item.order, r.item_id))
            sheets.append({'version_id': v.id, 'rollup': _rollup(rows),
                           'count': len(rows)})
            for r in rows:
                if since is None or (r.updated_at and r.updated_at > since):
                    changed.append({'area_id': a.id, 'version_id': v.id,
                                    'item': _public_item(r)})
        latest = sheets[-1] if sheets else None
        areas.append({'id': a.id,
                      'rollup': latest['rollup'] if latest else _rollup([]),
                      'sheets': sheets})

    return JsonResponse({'server_time': now.isoformat(), 'changed': changed,
                         'areas': areas})


@csrf_exempt
@require_http_methods(["POST"])
def public_readiness_save(request, token, pk):
    """Record a reviewer's verdict on one row.

    The iteration is looked up *through* the link's project, so a token cannot
    be pointed at a row belonging to anything else, and only EDITABLE fields are
    read off the payload.
    """
    share, err = _resolve(token)
    if err:
        return err

    from .system_testing import (_coerce, _READY_ALIASES, _TESTED_ALIASES)

    r = TestIteration.objects.filter(
        pk=pk, item__area__project=share.project).select_related('item').first()
    if r is None:
        return JsonResponse({'detail': 'That row is not part of this project.'},
                            status=404)

    data = _body(request)
    if 'tested' in data:
        r.tested = _coerce(data.get('tested'), TestItem.TESTED_CHOICES,
                           _TESTED_ALIASES, r.tested)
    if 'readiness' in data:
        r.readiness = _coerce(data.get('readiness'), TestItem.READINESS_CHOICES,
                              _READY_ALIASES, r.readiness)
    if 'client_feedback' in data:
        r.client_feedback = (data.get('client_feedback') or '').strip()
    r.save(update_fields=['tested', 'readiness', 'client_feedback', 'updated_at'])

    from .system_testing import _rollup
    rows = list(r.version.iterations.select_related('item'))
    return JsonResponse({'item': _public_item(r), 'rollup': _rollup(rows)})
