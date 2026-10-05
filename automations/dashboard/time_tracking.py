"""Time tracking on tasks, ClickUp-style.

Time is not typed into a box any more; it is the sum of entries - timer runs
and time added by hand - each with who, when, how long and an optional note.
The task's actual_hours is kept equal to that sum so reports, charts and the
board's time chips need no changes.

One running timer per person. Starting a timer stops that person's other
timer, never anybody else's.
"""
import json
import re
from datetime import datetime, time as dtime

from django.db.models import Sum
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import ProjectTask, TimeEntry
from .views import _require_module

# Under half a minute on a timer is a mis-click, not work.
MIN_TIMER_SECONDS = 30
MAX_ENTRY_SECONDS = 24 * 3600


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _name(user):
    return (user.get_full_name() or user.username) if user else ''


def parse_duration(text):
    """Seconds from "1h 30m", "45m", "1:30", "2" (hours) or "1.5"; None if unreadable."""
    t = (text or '').strip().lower().replace(',', '.')
    if not t:
        return None
    m = re.fullmatch(r'(\d+):([0-5]?\d)', t)
    if m:
        return int(m.group(1)) * 3600 + int(m.group(2)) * 60
    if re.fullmatch(r'\d+(\.\d+)?', t):
        return int(round(float(t) * 3600))
    parts = re.findall(r'(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\b', t)
    leftover = re.sub(r'(\d+(?:\.\d+)?)\s*(h|hr|hrs|hour|hours|m|min|mins|minute|minutes)\b', '', t)
    if not parts or leftover.strip():
        return None
    return int(round(sum(float(n) * (3600 if u.startswith('h') else 60) for n, u in parts)))


def recompute(task):
    """Keep the task's actual_hours equal to its entries."""
    total = TimeEntry.objects.filter(task=task, ended_at__isnull=False).aggregate(
        s=Sum('seconds'))['s'] or 0
    task.actual_hours = round(total / 3600, 2) if total else None
    task.save(update_fields=['actual_hours', 'updated_at'])


def running_for(user):
    """This person's running timer, if any."""
    if not user or not user.is_authenticated:
        return None
    return TimeEntry.objects.filter(user=user, ended_at__isnull=True).select_related('task').first()


def _stop(entry, now):
    secs = int((now - entry.started_at).total_seconds())
    if secs < MIN_TIMER_SECONDS:
        task = entry.task
        entry.delete()
        recompute(task)
        return
    entry.ended_at = now
    entry.seconds = min(secs, MAX_ENTRY_SECONDS)
    entry.save(update_fields=['ended_at', 'seconds'])
    recompute(entry.task)


def toggle_timer(request, task, action):
    """Start or stop the requesting person's timer on `task`."""
    now = timezone.now()
    mine = running_for(request.user)
    if action == 'start':
        if mine and mine.task_id == task.id:
            return
        if mine:
            _stop(mine, now)
        TimeEntry.objects.create(task=task, user=request.user, user_name=_name(request.user),
                                 started_at=now, source='timer')
    elif action == 'stop':
        if mine and mine.task_id == task.id:
            _stop(mine, now)
    else:
        raise ValueError("action must be 'start' or 'stop'.")


def _entry(e, me):
    return {
        'id': e.id, 'user': e.user_name or _name(e.user), 'mine': bool(me and e.user_id == me.id),
        'started_at': e.started_at.isoformat(),
        'ended_at': e.ended_at.isoformat() if e.ended_at else None,
        'seconds': e.seconds, 'note': e.note, 'source': e.source,
        'running': e.ended_at is None,
    }


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_task_time(request, pk):
    """A task's time entries (GET), or add time by hand (POST)."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    task = ProjectTask.objects.filter(id=pk).first()
    if task is None:
        return JsonResponse({'detail': 'Not found.'}, status=404)

    if request.method == 'POST':
        data = _body(request)
        secs = parse_duration(str(data.get('duration') or ''))
        if not secs or secs <= 0:
            return JsonResponse({'detail': 'Enter a time like 1h 30m, 45m or 2.'}, status=400)
        if secs > MAX_ENTRY_SECONDS:
            return JsonResponse({'detail': 'One entry can be at most 24 hours.'}, status=400)
        day = parse_date(str(data.get('date') or '')) or timezone.localdate()
        start = timezone.make_aware(datetime.combine(day, dtime(9, 0)))
        TimeEntry.objects.create(
            task=task, user=request.user, user_name=_name(request.user),
            started_at=start, ended_at=start + timezone.timedelta(seconds=secs), seconds=secs,
            note=str(data.get('note') or '').strip()[:300], source='manual')
        recompute(task)

    entries = TimeEntry.objects.filter(task=task).select_related('user')
    done = [e for e in entries if e.ended_at]
    return JsonResponse({
        'entries': [_entry(e, request.user) for e in entries],
        'total_seconds': sum(e.seconds for e in done),
        'by_person': _by_person(done),
    })


def _by_person(entries):
    totals = {}
    for e in entries:
        key = e.user_name or _name(e.user) or 'Unknown'
        totals[key] = totals.get(key, 0) + e.seconds
    return [{'user': k, 'seconds': v} for k, v in sorted(totals.items(), key=lambda kv: -kv[1])]


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_task_time_delete(request, pk, entry_id):
    """Remove a time entry: your own, or anybody's for an administrator."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    e = TimeEntry.objects.filter(id=entry_id, task_id=pk).select_related('task').first()
    if e is None:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    if e.user_id != request.user.id and not request.user.is_superuser:
        return JsonResponse({'detail': 'You can only remove your own time.'}, status=403)
    task = e.task
    e.delete()
    recompute(task)
    return JsonResponse({'ok': True})
