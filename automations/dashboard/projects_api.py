"""Project endpoints: the Gantt, and editing the project record behind it.

Kept apart from the task API because a project is now its own record with a
client, a status and dates, rather than just a string on a task.
"""
import json
import logging

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import project_gantt, project_reports
from .models import ProjectMeta, TaskActivity
from .views import _require_module

logger = logging.getLogger(__name__)


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


@require_http_methods(["GET"])
def api_project_gantt(request):
    """Projects on a timeline, each with its weekly breakdown."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    return JsonResponse(project_gantt.chart(
        workspace=request.GET.get('workspace', '').strip(),
        include_unassigned=request.GET.get('unassigned', '1') != '0',
        show_weeks=request.GET.get('weeks', '1') != '0',
    ))


@require_http_methods(["GET"])
def api_projects(request):
    """The project records, for the editor and the pickers."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    rows = []
    for p in ProjectMeta.objects.select_related('workspace').prefetch_related(
            'assigned_users'):
        rows.append({
            'name': p.name, 'client': p.client, 'client_email': p.client_email,
            'client_contact': p.client_contact,
            'status': p.status, 'status_display': p.get_status_display(),
            'priority': p.priority, 'priority_display': p.get_priority_display(),
            'description': p.description,
            'start_date': p.start_date.isoformat() if p.start_date else None,
            'end_date': p.end_date.isoformat() if p.end_date else None,
            'quoted_hours': float(p.quoted_hours) if p.quoted_hours else None,
            'color': p.color, 'icon': p.icon, 'logo_url': p.logo_url,
            'workspace': p.workspace.name if p.workspace_id else '',
            'assigned': [{'id': u.id,
                          'name': u.get_full_name() or u.username}
                         for u in p.assigned_users.all()],
        })
    return JsonResponse({
        'projects': rows,
        'statuses': [{'value': v, 'label': l}
                     for v, l in ProjectMeta.STATUS_CHOICES],
        'priorities': [{'value': v, 'label': l}
                       for v, l in ProjectMeta.PRIORITY_CHOICES],
    })


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_project_update(request, name):
    """Edit the project record. Every change lands in the activity log."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    project = ProjectMeta.objects.filter(name=name).first()
    if project is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    data = _body(request)
    user = request.user if request.user.is_authenticated else None
    changed, fields = [], []

    def note(kind, field, old, new):
        changed.append(TaskActivity(
            project_name=project.name, user=user, kind=kind, field=field,
            old_value=str(old or '')[:300], new_value=str(new or '')[:300]))

    for field, cap in (('client', 200), ('client_email', 254),
                       ('client_contact', 200), ('description', 4000)):
        if field in data:
            new = (data.get(field) or '').strip()[:cap]
            if new != getattr(project, field):
                note('edited', field, getattr(project, field), new)
                setattr(project, field, new)
                fields.append(field)

    for field, choices, kind in (
            ('status', ProjectMeta.STATUS_CHOICES, 'status'),
            ('priority', ProjectMeta.PRIORITY_CHOICES, 'priority')):
        if field in data:
            if data[field] not in dict(choices):
                return JsonResponse({'detail': f'Unknown {field}.'}, status=400)
            if data[field] != getattr(project, field):
                note(kind, field, getattr(project, field), data[field])
                setattr(project, field, data[field])
                fields.append(field)

    for field in ('start_date', 'end_date'):
        if field in data:
            raw = data.get(field) or None
            if raw:
                from django.utils.dateparse import parse_date
                parsed = parse_date(raw)
                if parsed is None:
                    return JsonResponse({'detail': f'{field} must be YYYY-MM-DD.'},
                                        status=400)
            else:
                parsed = None
            if parsed != getattr(project, field):
                note('dates', field, getattr(project, field), parsed)
                setattr(project, field, parsed)
                fields.append(field)

    if 'quoted_hours' in data:
        raw = data.get('quoted_hours')
        try:
            parsed = None if raw in (None, '') else round(float(raw), 2)
        except (TypeError, ValueError):
            return JsonResponse({'detail': 'quoted_hours must be a number.'},
                                status=400)
        if parsed != (float(project.quoted_hours) if project.quoted_hours else None):
            note('hours', 'quoted_hours', project.quoted_hours, parsed)
            project.quoted_hours = parsed
            fields.append('quoted_hours')

    if 'assigned' in data:
        ids = data.get('assigned') or []
        if not isinstance(ids, list):
            return JsonResponse({'detail': 'assigned must be a list of user ids.'},
                                status=400)
        before = sorted(u.id for u in project.assigned_users.all())
        project.assigned_users.set(ids)
        after = sorted(u.id for u in project.assigned_users.all())
        if before != after:
            note('assigned', 'assigned_users', before, after)

    if fields:
        project.save(update_fields=fields + ['updated_at'])
    if changed:
        TaskActivity.objects.bulk_create(changed)

    return JsonResponse({'ok': True, 'changed': fields,
                         'activity': len(changed)})


@require_http_methods(["GET"])
def api_project_activity(request, name):
    """What has happened on this project, newest first."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    try:
        limit = min(int(request.GET.get('limit', 50)), 300)
    except ValueError:
        limit = 50
    rows = (TaskActivity.objects.filter(project_name=name)
            .select_related('user', 'task')[:limit])
    return JsonResponse({'activity': [
        {'id': a.id, 'kind': a.kind, 'summary': a.summary,
         'task': a.task.title if a.task_id else '',
         'when': a.created_at.isoformat()}
        for a in rows]})


@require_http_methods(["GET"])
def api_project_metrics(request):
    """The reporting figures, for the reports page."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    try:
        days = min(max(int(request.GET.get('days', 30)), 1), 365)
    except ValueError:
        days = 30
    return JsonResponse(project_reports.metrics(
        days=days,
        project_name=request.GET.get('project', '').strip(),
        workspace=request.GET.get('workspace', '').strip()))
