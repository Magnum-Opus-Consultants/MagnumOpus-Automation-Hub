"""Token-authenticated public API, for external AI agents to file tasks.

Separate from api_platform.py because the auth model is different: these
endpoints are reached with an `Authorization: Bearer <token>` header instead of
a browser session, so they are CSRF-exempt and never touch request.user.

The token maps to one Django user; anything created is attributed to them.
"""
import json
import logging
from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import activity
from .models import ApiToken, ProjectTask

logger = logging.getLogger(__name__)

_STATUSES = [c[0] for c in ProjectTask.STATUS_CHOICES]
_PRIORITIES = [c[0] for c in ProjectTask.PRIORITY_CHOICES]


def _auth(request, scope='tasks'):
    """Resolve the bearer token. Returns (ApiToken, None) or (None, JsonResponse)."""
    header = request.META.get('HTTP_AUTHORIZATION', '')
    raw = ''
    if header.startswith('Bearer '):
        raw = header[7:].strip()
    elif header.startswith('Token '):
        raw = header[6:].strip()
    if not raw:
        # X-Api-Key is accepted too - some agent frameworks cannot set
        # Authorization headers.
        raw = (request.META.get('HTTP_X_API_KEY') or '').strip()
    if not raw:
        return None, JsonResponse(
            {'detail': 'Missing API token. Send header: Authorization: Bearer <token>'},
            status=401)

    tok = ApiToken.objects.filter(token_hash=ApiToken.hash_token(raw)).select_related('user').first()
    if tok is None or not tok.is_active:
        return None, JsonResponse({'detail': 'Invalid or revoked API token.'}, status=401)
    if not tok.user.is_active:
        return None, JsonResponse({'detail': 'The user for this token is disabled.'}, status=403)
    if not tok.allows(scope):
        return None, JsonResponse(
            {'detail': f'This token is not scoped for "{scope}".'}, status=403)

    # Touch last_used without a full save, so concurrent calls cannot clobber
    # other fields.
    ApiToken.objects.filter(pk=tok.pk).update(last_used_at=timezone.now())
    # Let activity recording see who really acted: the entry should say the
    # work came through this token, not that the user did it by hand.
    request.api_token = tok
    return tok, None


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return None


def _task_out(t):
    return {
        'id': t.id,
        'title': t.title,
        'description': t.description,
        'status': t.status,
        'priority': t.priority,
        'project': t.project_name,
        'parent': t.parent_id,
        'start_date': t.start_date.isoformat() if t.start_date else None,
        'due_date': t.end_date.isoformat() if t.end_date else None,
        'created_at': t.created_at.isoformat() if t.created_at else None,
    }


@csrf_exempt
@require_http_methods(["GET"])
def whoami(request):
    """Cheap call for an agent to verify its token works before doing real work."""
    tok, err = _auth(request)
    if err:
        return err
    return JsonResponse({
        'ok': True,
        'user': tok.user.username,
        'token_name': tok.name,
        'scopes': [s.strip() for s in tok.scopes.split(',') if s.strip()],
    })


@csrf_exempt
@require_http_methods(["GET"])
def activity_feed(request):
    """What people and agents have been doing — the gateway.

    Answers "what did Ethan do today" in one call, in two shapes at once:

      * `summary` — one line per person: "Ethan created 3 tasks, completed 1".
      * `entries` — the individual events behind it, each already a sentence.

    Both are returned because the useful answer depends on the question, and a
    caller that has to fetch twice to decide will just always fetch the long
    one.

    Query parameters: `actor` (username or name), `type` (task, repository,
    document), `since` (ISO date or datetime), `days`, `q`, `limit`.
    """
    tok, err = _auth(request, scope='activity')
    if err:
        return err

    since = None
    raw_since = (request.GET.get('since') or '').strip()
    if raw_since:
        since = parse_datetime(raw_since)
        if since is None:
            day = parse_date(raw_since)
            if day:
                since = timezone.make_aware(
                    timezone.datetime.combine(day, timezone.datetime.min.time()))
        if since is None:
            return JsonResponse(
                {'detail': 'since must be an ISO date or datetime.'}, status=400)
    elif request.GET.get('days'):
        try:
            since = timezone.now() - timedelta(days=max(0, int(request.GET['days'])))
        except ValueError:
            return JsonResponse({'detail': 'days must be a number.'}, status=400)

    try:
        limit = int(request.GET.get('limit') or 50)
    except ValueError:
        limit = 50

    entries = activity.feed(
        limit=limit,
        actor=(request.GET.get('actor') or '').strip(),
        object_type=(request.GET.get('type') or '').strip(),
        since=since,
        search=(request.GET.get('q') or '').strip(),
    )
    return JsonResponse({
        'ok': True,
        'count': len(entries),
        'summary': activity.summary(entries),
        'entries': entries,
    })


@csrf_exempt
@require_http_methods(["GET", "POST"])
def tasks(request):
    tok, err = _auth(request)
    if err:
        return err

    if request.method == 'GET':
        qs = ProjectTask.objects.all()
        status = (request.GET.get('status') or '').strip()
        if status == 'open':
            qs = qs.exclude(status='done')
        elif status:
            if status not in _STATUSES:
                return JsonResponse(
                    {'detail': f'status must be "open" or one of: {", ".join(_STATUSES)}.'},
                    status=400)
            qs = qs.filter(status=status)
        priority = (request.GET.get('priority') or '').strip()
        if priority:
            if priority not in _PRIORITIES:
                return JsonResponse(
                    {'detail': f'priority must be one of: {", ".join(_PRIORITIES)}.'},
                    status=400)
            qs = qs.filter(priority=priority)
        project = (request.GET.get('project') or '').strip()
        if project:
            qs = qs.filter(project_name=project)
        parent = (request.GET.get('parent') or '').strip()
        if parent == 'none':
            qs = qs.filter(parent__isnull=True)
        elif parent.isdigit():
            qs = qs.filter(parent_id=int(parent))

        try:
            limit = min(max(int(request.GET.get('limit', 100)), 1), 500)
        except (TypeError, ValueError):
            limit = 100
        rows = [_task_out(t) for t in qs.order_by('-created_at')[:limit]]
        return JsonResponse({'tasks': rows, 'count': len(rows), 'total': qs.count()})

    # ── POST: create a task or a subtask ─────────────────────────────────────
    data = _body(request)
    if data is None:
        return JsonResponse({'detail': 'Body must be valid JSON.'}, status=400)
    if not isinstance(data, dict):
        return JsonResponse({'detail': 'Body must be a JSON object.'}, status=400)

    title = (data.get('title') or '').strip()
    if not title:
        return JsonResponse({'detail': 'title is required.'}, status=400)

    errors = []
    status = (data.get('status') or 'todo').strip()
    if status not in _STATUSES:
        errors.append(f'status must be one of: {", ".join(_STATUSES)}.')
    priority = (data.get('priority') or 'medium').strip()
    if priority not in _PRIORITIES:
        errors.append(f'priority must be one of: {", ".join(_PRIORITIES)}.')

    parent = None
    if data.get('parent') not in (None, ''):
        parent = ProjectTask.objects.filter(id=data.get('parent')).first()
        if parent is None:
            errors.append('parent does not match an existing task.')
        elif parent.parent_id is not None:
            # One level of nesting only - the UI renders tasks and subtasks,
            # not an arbitrary tree.
            errors.append('parent is itself a subtask; only one level of nesting is supported.')

    dates = {}
    for src, field in (('start_date', 'start_date'), ('due_date', 'end_date'), ('end_date', 'end_date')):
        if data.get(src):
            try:
                parsed = parse_date(str(data[src]))
            except ValueError:
                parsed = None
            if not parsed:
                errors.append(f'{src} must be a date in YYYY-MM-DD format.')
            else:
                dates[field] = parsed

    if errors:
        return JsonResponse({'detail': ' '.join(errors), 'errors': errors}, status=400)

    task = ProjectTask.objects.create(
        title=title[:255],
        description=(data.get('description') or '').strip(),
        status=status,
        priority=priority,
        project_name=(data.get('project') or data.get('project_name') or '').strip()[:100],
        parent=parent,
        **dates,
    )
    logger.info('[public-api] %s created task %s via token %s', tok.user.username, task.id, tok.prefix)
    activity.record(request, 'created', 'task', obj=task, label=task.title,
                    project=task.project_name or '')
    return JsonResponse(_task_out(task), status=201)


@csrf_exempt
@require_http_methods(["GET", "PATCH", "DELETE"])
def task_detail(request, pk):
    tok, err = _auth(request)
    if err:
        return err

    task = ProjectTask.objects.filter(pk=pk).first()
    if task is None:
        return JsonResponse({'detail': 'Task not found.'}, status=404)

    if request.method == 'GET':
        out = _task_out(task)
        out['subtasks'] = [_task_out(s) for s in task.subtasks.all()]
        return JsonResponse(out)

    if request.method == 'DELETE':
        title, project = task.title, task.project_name or ''
        task.delete()
        activity.record(request, 'deleted', 'task', object_id=pk, label=title,
                        project=project)
        return JsonResponse({'ok': True, 'deleted': pk})

    was_status = task.status
    data = _body(request)
    if not isinstance(data, dict):
        return JsonResponse({'detail': 'Body must be a JSON object.'}, status=400)

    if 'title' in data:
        title = (data.get('title') or '').strip()
        if not title:
            return JsonResponse({'detail': 'title cannot be blank.'}, status=400)
        task.title = title[:255]
    if 'description' in data:
        task.description = (data.get('description') or '').strip()
    if 'status' in data:
        if data['status'] not in _STATUSES:
            return JsonResponse(
                {'detail': f'status must be one of: {", ".join(_STATUSES)}.'}, status=400)
        task.status = data['status']
    if 'priority' in data:
        if data['priority'] not in _PRIORITIES:
            return JsonResponse(
                {'detail': f'priority must be one of: {", ".join(_PRIORITIES)}.'}, status=400)
        task.priority = data['priority']
    if 'project' in data or 'project_name' in data:
        task.project_name = (data.get('project') or data.get('project_name') or '').strip()[:100]
    task.save()
    verb = ('completed' if task.status == 'done' and was_status != 'done'
            else 'reopened' if was_status == 'done' and task.status != 'done'
            else 'updated')
    activity.record(request, verb, 'task', obj=task, label=task.title,
                    project=task.project_name or '')
    return JsonResponse(_task_out(task))
