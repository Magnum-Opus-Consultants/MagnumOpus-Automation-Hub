"""The Gantt: projects on a timeline, each expanding into its weeks.

The shape is taken from the E-Click dashboard, which is the standard this was
asked to match. Its Gantt is not a flat list of task bars - it is two levels:

    Project ────────────────────────────────  one bar, status colour, progress
      └ Week 1  ██████                        tasks in that week, done vs total
        Week 2      ████████
        Week 3          ██████

That second level is the point. A project bar tells you a project runs from
March to June; the week rows tell you where the work actually sits inside it,
which is the question people open a Gantt to answer.

Dates come from the project when it has them and are otherwise derived from its
tasks, so a project nobody has dated still appears on the chart rather than
vanishing from it.
"""
import logging
from datetime import date, timedelta

from django.utils import timezone

from .models import ProjectMeta, ProjectTask

logger = logging.getLogger(__name__)

# Reused from the reporting side so a bar and a report never disagree about
# what "done" means.
DONE_STATES = {'done', 'review_pending', 'discrepancy'}
BLOCKED_STATES = {'in_progress_guidance', 'on_hold'}

# Bar colours by project status. Held here rather than in the component so the
# legend, the bars and any future export all read from one list.
STATUS_COLOURS = {
    'planned':                  {'bar': '#94a3b8', 'label': 'Planned'},
    'in_progress':              {'bar': '#2563eb', 'label': 'In progress'},
    'in_progress_guidance':     {'bar': '#f59e0b', 'label': 'Guidance required'},
    'completed_review_pending': {'bar': '#0891b2', 'label': 'Review pending'},
    'completed_discrepancy':    {'bar': '#c026d3', 'label': 'Data discrepancy'},
    'completed':                {'bar': '#16a34a', 'label': 'Completed'},
    'on_hold':                  {'bar': '#78716c', 'label': 'On hold'},
    'cancelled':                {'bar': '#dc2626', 'label': 'Cancelled'},
    'unassigned':               {'bar': '#a8a29e', 'label': 'Not on a project'},
}


def _task_dates(task):
    """The span a task occupies, falling back to the day it was created.

    A task with no dates would otherwise contribute nothing to a week row, so
    the week that task was created in is where it counts.
    """
    start = task.start_date or task.end_date
    end = task.end_date or task.start_date
    if start is None:
        created = timezone.localtime(task.created_at).date() if task.created_at else None
        return created, created
    return start, end


def _week_start(d):
    """The Monday of that week."""
    return d - timedelta(days=d.weekday())


def _iso_week(d):
    return d.isocalendar()[1]


def _weeks_between(start, end, cap=26):
    """Week-start dates from `start` to `end`.

    Capped: a project running three years would otherwise render a hundred and
    fifty rows nobody scrolls through. The cap is reported so the UI can say the
    view was trimmed rather than pretending that is the whole project.
    """
    out, cursor = [], _week_start(start)
    last = _week_start(end)
    while cursor <= last and len(out) < cap:
        out.append(cursor)
        cursor += timedelta(days=7)
    return out, (cursor <= last)


def _progress(tasks):
    if not tasks:
        return 0
    done = sum(1 for t in tasks if t.status in DONE_STATES)
    return round(done * 100.0 / len(tasks))


def _span_from_tasks(tasks):
    """The earliest and latest dates any of these tasks touch."""
    starts, ends = [], []
    for t in tasks:
        s, e = _task_dates(t)
        if s:
            starts.append(s)
        if e:
            ends.append(e)
    return (min(starts) if starts else None), (max(ends) if ends else None)


def _project_entry(name, label, status, tasks, meta=None, show_weeks=True):
    """One project row plus its week rows."""
    today = timezone.localdate()

    start = getattr(meta, 'start_date', None)
    end = getattr(meta, 'end_date', None)
    derived_start, derived_end = _span_from_tasks(tasks)
    # The project's own dates win; task dates fill the gaps. A project dated
    # only at one end still gets a bar rather than a zero-width sliver.
    start = start or derived_start or today
    end = end or derived_end or (start + timedelta(days=27))
    if end < start:
        start, end = end, start
    dates_derived = not (getattr(meta, 'start_date', None)
                         and getattr(meta, 'end_date', None))

    weeks, trimmed = ([], False)
    if show_weeks:
        week_starts, trimmed = _weeks_between(start, end)
        for i, ws in enumerate(week_starts, start=1):
            we = ws + timedelta(days=6)
            # A task counts towards a week if its span overlaps that week.
            in_week = []
            for t in tasks:
                ts, te = _task_dates(t)
                if ts and te and ts <= we and te >= ws:
                    in_week.append(t)
            done = [t for t in in_week if t.status in DONE_STATES]
            weeks.append({
                'week_number': i,
                'iso_week': _iso_week(ws),
                'start_date': ws.isoformat(),
                'end_date': we.isoformat(),
                'total_tasks': len(in_week),
                'completed_tasks': len(done),
                'blocked_tasks': len([t for t in in_week
                                      if t.status in BLOCKED_STATES]),
                'progress': _progress(in_week),
                'is_current': ws <= today <= we,
                'titles': [t.title for t in in_week[:6]],
            })

    overdue = [t for t in tasks
               if t.end_date and t.end_date < today and t.status not in DONE_STATES]

    return {
        'name': name,
        'label': label,
        'status': status,
        'status_label': STATUS_COLOURS.get(status, {}).get('label', status),
        'color': STATUS_COLOURS.get(status, {}).get('bar', '#94a3b8'),
        'client': getattr(meta, 'client', '') or '',
        'priority': getattr(meta, 'priority', '') or '',
        'icon': getattr(meta, 'icon', '') or '',
        'accent': getattr(meta, 'color', '') or '',
        'workspace': (meta.workspace.name
                      if meta is not None and meta.workspace_id else ''),
        # The commonest development type on the project's tasks, which is what
        # the reference app shows on the project row.
        'development_status': _dominant_development(tasks),
        'start_date': start.isoformat(),
        'end_date': end.isoformat(),
        'dates_derived': dates_derived,
        'total_tasks': len(tasks),
        'completed_tasks': len([t for t in tasks if t.status in DONE_STATES]),
        'blocked_tasks': len([t for t in tasks if t.status in BLOCKED_STATES]),
        'overdue_tasks': len(overdue),
        'progress': _progress(tasks),
        'weeks': weeks,
        'weeks_trimmed': trimmed,
    }


def _dominant_development(tasks):
    counts = {}
    for t in tasks:
        if t.development_status:
            counts[t.development_status] = counts.get(t.development_status, 0) + 1
    if not counts:
        return ''
    return max(counts.items(), key=lambda kv: kv[1])[0]


def chart(workspace='', include_unassigned=True, show_weeks=True):
    """Everything the Gantt needs, in two queries.

    Returns the rows plus the overall span, so the component does not have to
    work out the timeline bounds a second time and risk disagreeing with the
    bars it is drawing.
    """
    # Automated projects are left off the chart: a bar for five report names
    # repeated every day for a year tells nobody anything, and it dwarfs the
    # real projects beside it.
    projects = list(ProjectMeta.objects.filter(is_automated=False)
                    .select_related('workspace'))
    if workspace:
        projects = [p for p in projects if p.workspace and p.workspace.name == workspace]
    names = {p.name for p in projects}

    all_tasks = list(ProjectTask.objects.all())
    by_project = {}
    for t in all_tasks:
        by_project.setdefault(t.project_name or '', []).append(t)

    rows = [_project_entry(p.name, p.name, p.status,
                           by_project.get(p.name, []), meta=p,
                           show_weeks=show_weeks)
            for p in projects]

    if include_unassigned and not workspace:
        automated = set(ProjectMeta.objects.filter(is_automated=True)
                        .values_list('name', flat=True))
        loose = [t for t in all_tasks
                 if (t.project_name or '') not in names
                 and (t.project_name or '') not in automated]
        if loose:
            rows.append(_project_entry(
                '', 'Not on a project', 'unassigned', loose, meta=None,
                show_weeks=show_weeks))

    # Sort the way someone reads a Gantt: what is running now, then what is
    # late, then everything else by start date.
    today = timezone.localdate()
    def _key(r):
        running = not (r['end_date'] < today.isoformat()
                       or r['start_date'] > today.isoformat())
        return (0 if running else 1, -r['overdue_tasks'], r['start_date'])
    rows.sort(key=_key)

    starts = [r['start_date'] for r in rows] or [today.isoformat()]
    ends = [r['end_date'] for r in rows] or [today.isoformat()]
    span_start = date.fromisoformat(min(starts))
    span_end = date.fromisoformat(max(ends))
    # Always show today, even when every project is in the past or the future -
    # a Gantt without the present on it is hard to read.
    span_start = min(span_start, today)
    span_end = max(span_end, today)
    # A little air either side so a bar never starts flush against the edge.
    span_start = _week_start(span_start) - timedelta(days=7)
    span_end = _week_start(span_end) + timedelta(days=13)

    return {
        'generated_at': timezone.now().isoformat(),
        'today': today.isoformat(),
        'span_start': span_start.isoformat(),
        'span_end': span_end.isoformat(),
        'span_days': (span_end - span_start).days or 1,
        'projects': rows,
        'legend': [{'status': k, 'label': v['label'], 'color': v['bar']}
                   for k, v in STATUS_COLOURS.items()],
        'development_labels': dict(ProjectTask.DEVELOPMENT_CHOICES),
        'workspaces': sorted({p.workspace.name for p in projects
                              if p.workspace_id}),
    }
