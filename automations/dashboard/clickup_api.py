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

    return JsonResponse({
        'project': name,
        'list_id': meta.clickup_list_id,
        'list_name': meta.clickup_list_name,
        'queued': queued,
    })


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
