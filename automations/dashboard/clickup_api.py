"""Endpoints for linking a project to a ClickUp list and watching the sync.

The token itself is never returned by anything here - only whether one is
configured. A leaked token is regenerated in ClickUp, not read back out of this
application.
"""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import clickup
from .models import ProjectMeta, ProjectTask
from .views import _require_module

logger = logging.getLogger(__name__)

MODULE = 'tasks'


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


@require_http_methods(["GET"])
def api_clickup_status(request):
    """Whether the integration is on, and how the sync is doing."""
    err = _require_module(request, MODULE)
    if err:
        return err

    # Looking at this page is a good moment to check for anything raised in
    # ClickUp since the last sweep. Started in the background so the page does
    # not wait on ClickUp to render.
    if request.GET.get('pull') == '1':
        clickup.pull_soon()

    linked = ProjectMeta.objects.exclude(clickup_list_id='')
    waiting = ProjectTask.objects.filter(clickup_dirty=True).count()
    failing = (ProjectTask.objects.filter(clickup_dirty=True)
               .exclude(clickup_error='').count())
    return JsonResponse({
        'configured': clickup.configured(),
        'linked_projects': [
            {'name': m.name, 'list_id': m.clickup_list_id,
             'list_name': m.clickup_list_name}
            for m in linked
        ],
        'waiting': waiting,
        'failing': failing,
        'synced': ProjectTask.objects.exclude(clickup_task_id='').count(),
    })


@require_http_methods(["GET"])
def api_clickup_lists(request):
    """The workspace tree, for choosing which list a project pushes to."""
    err = _require_module(request, MODULE)
    if err:
        return err
    if not clickup.configured():
        return JsonResponse(
            {'detail': 'No ClickUp token. Set CLICKUP_API_TOKEN in the .env '
                       'file and restart the server.'}, status=400)
    try:
        return JsonResponse({'workspaces': clickup.workspace_tree()})
    except clickup.ClickUpError as exc:
        return JsonResponse({'detail': str(exc)}, status=502)


@csrf_exempt
@require_http_methods(["POST"])
def api_clickup_link(request):
    """Point a project at a ClickUp list, or clear the link.

    Linking marks the project's existing tasks dirty rather than pushing them
    on the spot: a project can carry hundreds, and the retry is already the
    thing that knows how to work through a backlog within the rate limit.
    """
    err = _require_module(request, MODULE)
    if err:
        return err

    data = _body(request)
    name = (data.get('project') or '').strip()
    if not name:
        return JsonResponse({'detail': 'Which project?'}, status=400)

    meta, _made = ProjectMeta.objects.get_or_create(name=name)
    list_id = (data.get('list_id') or '').strip()
    meta.clickup_list_id = list_id[:40]
    meta.clickup_list_name = (data.get('list_name') or '').strip()[:200]
    meta.save(update_fields=['clickup_list_id', 'clickup_list_name'])

    queued = 0
    if list_id:
        queued = ProjectTask.objects.filter(project_name=name).update(
            clickup_dirty=True)
        # Start straight away rather than leaving the backlog for the next
        # sweep - a link that appears to do nothing for five minutes is what
        # makes people look for a manual sync button.
        clickup.push_project_soon(name)

    return JsonResponse({
        'project': name,
        'list_id': meta.clickup_list_id,
        'list_name': meta.clickup_list_name,
        'queued': queued,
    })


@require_http_methods(["GET"])
def api_clickup_people(request):
    """Who in the tracker is who in ClickUp, and who cannot be matched."""
    err = _require_module(request, MODULE)
    if err:
        return err
    from django.contrib.auth.models import User

    try:
        roster = clickup.members() if clickup.configured() else []
    except clickup.ClickUpError as exc:
        return JsonResponse({'detail': str(exc)}, status=502)
    by_id = {m['id']: m for m in roster}

    people = []
    for u in User.objects.select_related('profile').order_by('username'):
        explicit = (getattr(getattr(u, 'profile', None), 'clickup_user_id', '')
                    or '').strip()
        matched = clickup.clickup_id_for_user(u) if roster else ''
        people.append({
            'id': u.id,
            'username': u.username,
            'full_name': u.get_full_name(),
            'email': u.email,
            'clickup_id': matched,
            'clickup_name': by_id.get(matched, {}).get('name', ''),
            # How the match was made, so an accidental one is obvious.
            'matched_by': 'manual' if explicit else ('email' if matched else ''),
        })

    # Named so the UI can say which ClickUp workspace these members come from -
    # the mapping is global precisely because a member id is issued per
    # workspace, and saying so is what stops it reading as per project.
    workspace = ''
    try:
        if clickup.configured():
            teams = clickup._request('GET', '/team').get('teams', [])
            workspace = teams[0]['name'] if teams else ''
    except clickup.ClickUpError:
        workspace = ''

    return JsonResponse({'people': people, 'members': roster,
                         'workspace': workspace})


@csrf_exempt
@require_http_methods(["POST"])
def api_clickup_person_link(request):
    """Say outright which ClickUp member a tracker user is."""
    err = _require_module(request, MODULE)
    if err:
        return err
    from django.contrib.auth.models import User
    from .models import UserProfile

    data = _body(request)
    u = User.objects.filter(pk=data.get('user')).first()
    if u is None:
        return JsonResponse({'detail': 'No such user.'}, status=404)

    profile, _ = UserProfile.objects.get_or_create(user=u)
    profile.clickup_user_id = (data.get('clickup_id') or '').strip()[:20]
    profile.save(update_fields=['clickup_user_id'])
    return JsonResponse({'user': u.username,
                         'clickup_id': profile.clickup_user_id})


@csrf_exempt
@require_http_methods(["POST"])
def api_clickup_pull(request):
    """Bring across anything raised in ClickUp, now."""
    err = _require_module(request, MODULE)
    if err:
        return err
    if not clickup.configured():
        return JsonResponse(
            {'detail': 'No ClickUp token. Set CLICKUP_API_TOKEN in the .env '
                       'file and restart the server.'}, status=400)
    added, removed, failed = clickup.pull_all()
    return JsonResponse({'added': added, 'removed': removed, 'failed': failed})


@csrf_exempt
@require_http_methods(["POST"])
def api_clickup_sync(request):
    """Push everything waiting, now, and report what happened."""
    err = _require_module(request, MODULE)
    if err:
        return err
    if not clickup.configured():
        return JsonResponse(
            {'detail': 'No ClickUp token. Set CLICKUP_API_TOKEN in the .env '
                       'file and restart the server.'}, status=400)

    pushed, failed = clickup.retry_dirty(limit=200)
    waiting = ProjectTask.objects.filter(clickup_dirty=True).count()
    sample = (ProjectTask.objects.filter(clickup_dirty=True)
              .exclude(clickup_error='')
              .values_list('clickup_error', flat=True)[:1])
    return JsonResponse({
        'pushed': pushed, 'failed': failed, 'waiting': waiting,
        'last_error': sample[0] if sample else '',
    })
