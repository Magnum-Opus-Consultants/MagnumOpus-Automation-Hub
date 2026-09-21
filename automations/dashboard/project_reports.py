"""Reporting on projects: the figures, and sending them to someone.

Modelled on the reports page of the E-Click tracker, which is the standard this
was asked to meet. Two halves:

* `metrics()` computes everything a report shows, in one pass, from the
  database. Nothing is cached: a report is a claim about right now, and a stale
  number is worse than a slow page.
* `send()` renders those figures through the platform's own email shell and
  records a SentReport row with the payload as it was at that moment.

That last point is the difference between reporting and anecdote. Recomputing
last month's figures today gives different numbers - tasks moved, hours were
logged - so a report you may be asked to stand behind has to keep its own copy
of what it said.
"""
import logging
from datetime import timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.db.models import Avg, Count, F, Q, Sum
from django.utils import timezone

from . import email_layout as el
from .models import ProjectMeta, ProjectTask, SentReport, TaskActivity

logger = logging.getLogger(__name__)

# Which task states count as finished. Three of them are "done" in the sense
# that the work stopped, but only one is done in the sense the client agreed -
# so a report has to be able to say both.
DONE_STATES = {'done', 'review_pending', 'discrepancy'}
ACCEPTED_STATES = {'done'}
BLOCKED_STATES = {'in_progress_guidance', 'on_hold'}
OPEN_STATES = {'backlog', 'todo', 'in_progress', 'in_progress_guidance',
               'review', 'on_hold'}


def _num(v):
    """A Decimal or None as a float, for JSON."""
    if v is None:
        return None
    return float(v) if isinstance(v, Decimal) else v


def _pct(part, whole):
    return round(part * 100.0 / whole, 1) if whole else 0.0


def project_row(project, tasks):
    """One project's figures, computed from tasks already in memory.

    Takes the task list rather than querying, so building the whole report is
    one query for tasks rather than one per project.
    """
    mine = [t for t in tasks if t.project_name == project.name]
    top = [t for t in mine if t.parent_id is None]
    done = [t for t in mine if t.status in DONE_STATES]
    accepted = [t for t in mine if t.status in ACCEPTED_STATES]
    blocked = [t for t in mine if t.status in BLOCKED_STATES]

    est = sum((t.estimated_hours or 0) for t in mine)
    act = sum((t.actual_hours or 0) for t in mine)

    today = timezone.localdate()
    overdue = [t for t in mine
               if t.end_date and t.end_date < today and t.status not in DONE_STATES]

    # Cycle time on the tasks that actually recorded when they finished.
    timed = [t for t in mine if t.completed_at and t.created_at]
    avg_days = (round(sum((t.completed_at - t.created_at).days for t in timed)
                      / len(timed), 1) if timed else None)

    return {
        'name': project.name,
        'client': project.client,
        'client_email': project.client_email,
        'status': project.status,
        'status_display': project.get_status_display(),
        'priority': project.priority,
        'priority_display': project.get_priority_display(),
        'color': project.color,
        'icon': project.icon,
        'workspace': project.workspace.name if project.workspace_id else '',
        'start_date': project.start_date.isoformat() if project.start_date else None,
        'end_date': project.end_date.isoformat() if project.end_date else None,
        'quoted_hours': _num(project.quoted_hours),
        'assigned': [u.get_full_name() or u.username
                     for u in project.assigned_users.all()],
        'tasks_total': len(mine),
        'tasks_top_level': len(top),
        'subtasks': len(mine) - len(top),
        'tasks_done': len(done),
        'tasks_accepted': len(accepted),
        'tasks_blocked': len(blocked),
        'tasks_overdue': len(overdue),
        # Two completion rates on purpose: work finished, and work signed off.
        'completion_rate': _pct(len(done), len(mine)),
        'accepted_rate': _pct(len(accepted), len(mine)),
        'estimated_hours': _num(est),
        'actual_hours': _num(act),
        'hours_variance': _num(act - est) if (est or act) else None,
        'avg_days_to_complete': avg_days,
        'overdue_titles': [t.title for t in overdue[:5]],
    }


def _loose_row(tasks):
    """A row for work that is not on any project.

    Shown as a project so it appears in the same table rather than being
    described in a footnote nobody reads.
    """
    today = timezone.localdate()
    done = [t for t in tasks if t.status in DONE_STATES]
    blocked = [t for t in tasks if t.status in BLOCKED_STATES]
    overdue = [t for t in tasks
               if t.end_date and t.end_date < today and t.status not in DONE_STATES]
    est = sum((t.estimated_hours or 0) for t in tasks)
    act = sum((t.actual_hours or 0) for t in tasks)
    return {
        'name': '(not on a project)', 'client': '', 'client_email': '',
        'status': 'unassigned', 'status_display': 'Unassigned',
        'priority': '', 'priority_display': '', 'color': '', 'icon': '',
        'workspace': '', 'start_date': None, 'end_date': None,
        'quoted_hours': None, 'assigned': [],
        'tasks_total': len(tasks),
        'tasks_top_level': len([t for t in tasks if t.parent_id is None]),
        'subtasks': len([t for t in tasks if t.parent_id is not None]),
        'tasks_done': len(done),
        'tasks_accepted': len([t for t in tasks if t.status in ACCEPTED_STATES]),
        'tasks_blocked': len(blocked), 'tasks_overdue': len(overdue),
        'completion_rate': _pct(len(done), len(tasks)),
        'accepted_rate': _pct(len([t for t in tasks if t.status in ACCEPTED_STATES]),
                              len(tasks)),
        'estimated_hours': _num(est), 'actual_hours': _num(act),
        'hours_variance': _num(act - est) if (est or act) else None,
        'avg_days_to_complete': None,
        'overdue_titles': [t.title for t in overdue[:5]],
        'is_unassigned': True,
    }


def metrics(days=30, project_name='', workspace=''):
    """Everything a report shows, in one pass."""
    since = timezone.now() - timedelta(days=days)

    projects = ProjectMeta.objects.prefetch_related('assigned_users', 'workspace')
    if project_name:
        projects = projects.filter(name=project_name)
    if workspace:
        projects = projects.filter(workspace__name=workspace)
    projects = list(projects)
    names = {p.name for p in projects}

    tasks = list(ProjectTask.objects.filter(project_name__in=names)
                 if names else ProjectTask.objects.none())

    rows = [project_row(p, tasks) for p in projects]

    # Tasks that belong to no project at all. Counting only tasks with a
    # project_name made the first run of this report claim 24 tasks when the
    # tracker held 429 - the rest simply were not on a project yet. A report
    # that quietly omits 94% of the work is worse than no report.
    loose = []
    if not project_name and not workspace:
        loose = list(ProjectTask.objects.filter(
            Q(project_name='') | Q(project_name=None)
            | ~Q(project_name__in=names)))
        if loose:
            rows.append(_loose_row(loose))
            tasks = tasks + loose

    rows.sort(key=lambda r: (-r['tasks_overdue'], -r['tasks_total']))

    # Counted from the task list already in memory, so these always describe
    # exactly the tasks the totals describe - including the loose ones.
    by_status, by_dev = {}, {}
    for t in tasks:
        by_status[t.status] = by_status.get(t.status, 0) + 1
        if t.development_status:
            by_dev[t.development_status] = by_dev.get(t.development_status, 0) + 1
    proj_by_status = {}
    for p in projects:
        proj_by_status[p.status] = proj_by_status.get(p.status, 0) + 1

    # Who did what in the window. Read from the activity log rather than from
    # task timestamps, so it reflects people's actions rather than row edits.
    people = []
    acts = (TaskActivity.objects.filter(created_at__gte=since)
            .exclude(user=None).values('user__username', 'user__first_name',
                                       'user__last_name')
            .annotate(n=Count('id')).order_by('-n')[:12])
    for a in acts:
        full = f"{a['user__first_name']} {a['user__last_name']}".strip()
        people.append({'user': full or a['user__username'], 'changes': a['n']})

    open_tasks = [t for t in tasks if t.status in OPEN_STATES]
    done_tasks = [t for t in tasks if t.status in DONE_STATES]
    blocked = [t for t in tasks if t.status in BLOCKED_STATES]
    today = timezone.localdate()
    overdue = [t for t in tasks
               if t.end_date and t.end_date < today and t.status not in DONE_STATES]
    due_soon = [t for t in tasks
                if t.end_date and today <= t.end_date <= today + timedelta(days=7)
                and t.status not in DONE_STATES]

    est = sum((t.estimated_hours or 0) for t in tasks)
    act = sum((t.actual_hours or 0) for t in tasks)

    return {
        'window_days': days,
        'generated_at': timezone.now().isoformat(),
        'scope': {'project': project_name, 'workspace': workspace},
        'totals': {
            'projects': len(projects),
            'projects_by_status': proj_by_status,
            'tasks': len(tasks),
            'tasks_open': len(open_tasks),
            'tasks_done': len(done_tasks),
            'tasks_blocked': len(blocked),
            'tasks_overdue': len(overdue),
            'tasks_due_next_7_days': len(due_soon),
            'completion_rate': _pct(len(done_tasks), len(tasks)),
            'estimated_hours': _num(est),
            'actual_hours': _num(act),
            'hours_variance': _num(act - est) if (est or act) else None,
        },
        'tasks_by_status': by_status,
        'tasks_by_development_type': by_dev,
        'projects': rows,
        'people': people,
        'overdue': [
            {'project': t.project_name, 'title': t.title,
             'due': t.end_date.isoformat() if t.end_date else None,
             'status': t.status,
             'days_late': (today - t.end_date).days if t.end_date else None}
            for t in sorted(overdue, key=lambda x: x.end_date or today)[:25]
        ],
        'blocked': [
            {'project': t.project_name, 'title': t.title, 'status': t.status,
             'status_display': t.get_status_display()}
            for t in blocked[:25]
        ],
        'recent_activity': [
            {'when': a.created_at.isoformat(), 'summary': a.summary,
             'project': a.project_name}
            for a in TaskActivity.objects.filter(created_at__gte=since)
            .select_related('user')[:30]
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Sending
# ══════════════════════════════════════════════════════════════════════════════

def _status_table(rows):
    """The per-project table that carries the report."""
    if not rows:
        return el.para('No projects in scope.', muted=True, size=13)
    head = ''.join(
        f'<th align="{a}" style="padding:8px 10px;border:1px solid {el.LINE};'
        f'background:{el.WASH};font-family:{el.FONT};font-size:11px;'
        f'text-transform:uppercase;letter-spacing:.3px;color:{el.MUTED}">{h}</th>'
        for h, a in (('Project', 'left'), ('Client', 'left'), ('Status', 'left'),
                     ('Tasks', 'right'), ('Done', 'right'), ('Overdue', 'right'),
                     ('Hours est/act', 'right')))
    body = []
    for r in rows:
        late = r['tasks_overdue']
        body.append(
            f'<tr style="background:{"#fdecea" if late else "#ffffff"}">'
            f'<td style="padding:8px 10px;border:1px solid {el.LINE};'
            f'font-family:{el.FONT};font-size:13px;color:{el.INK}">'
            f'{el.esc(r["name"])}</td>'
            f'<td style="padding:8px 10px;border:1px solid {el.LINE};'
            f'font-family:{el.FONT};font-size:13px;color:{el.MUTED}">'
            f'{el.esc(r["client"] or "—")}</td>'
            f'<td style="padding:8px 10px;border:1px solid {el.LINE};'
            f'font-family:{el.FONT};font-size:12px;color:{el.INK}">'
            f'{el.esc(r["status_display"])}</td>'
            f'<td align="right" style="padding:8px 10px;border:1px solid {el.LINE};'
            f'font-family:{el.FONT};font-size:13px">{r["tasks_total"]}</td>'
            f'<td align="right" style="padding:8px 10px;border:1px solid {el.LINE};'
            f'font-family:{el.FONT};font-size:13px">{r["tasks_done"]}'
            f' <span style="color:{el.MUTED}">({r["completion_rate"]}%)</span></td>'
            f'<td align="right" style="padding:8px 10px;border:1px solid {el.LINE};'
            f'font-family:{el.FONT};font-size:13px;'
            f'color:{"#c5221f" if late else el.MUTED}">{late or "—"}</td>'
            f'<td align="right" style="padding:8px 10px;border:1px solid {el.LINE};'
            f'font-family:{el.FONT};font-size:12px;color:{el.MUTED}">'
            f'{r["estimated_hours"] or 0:g} / {r["actual_hours"] or 0:g}</td>'
            f'</tr>')
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'width="100%" style="border-collapse:collapse;margin:0 0 18px">'
            f'<tr>{head}</tr>{"".join(body)}</table>')


def build_email(data, report_type='general', title='', message='',
                for_client=False):
    """The report as HTML and text.

    `for_client` drops the internal columns - hours against quote, and who is
    behind - because a client report is about their work, not about us.
    """
    t = data['totals']
    rows = data['projects']
    heading = title or {
        'general': 'Project status report',
        'project': f'{rows[0]["name"] if rows else "Project"} status report',
        'client': f'{rows[0]["client"] if rows else "Client"} project update',
        'weekly': 'Weekly project report',
        'complete': 'Complete project report',
    }.get(report_type, 'Project report')

    blocks = [
        el.heading(heading,
                   f'{t["projects"]} project{"" if t["projects"] == 1 else "s"}, '
                   f'{t["tasks"]} task{"" if t["tasks"] == 1 else "s"}, '
                   f'last {data["window_days"]} days'),
    ]
    if message:
        blocks.append(el.para(message))

    facts = [('Open', str(t['tasks_open'])), ('Done', str(t['tasks_done'])),
             ('Overdue', str(t['tasks_overdue'])),
             ('Due in 7 days', str(t['tasks_due_next_7_days']))]
    if not for_client:
        facts.append(('Blocked', str(t['tasks_blocked'])))
    blocks.append(el.fact_row(facts))
    blocks.append(el.raw(_status_table(rows)))

    if data['overdue'] and not for_client:
        blocks.append(el.para('Past their due date:'))
        blocks.append(el.bullet_list(
            [f'{o["project"]}: {o["title"]} — {o["days_late"]} day'
             f'{"" if o["days_late"] == 1 else "s"} late'
             for o in data['overdue'][:10]]))

    if data['blocked'] and not for_client:
        blocks.append(el.para('Waiting on a decision or on hold:'))
        blocks.append(el.bullet_list(
            [f'{b["project"]}: {b["title"]} — {b["status_display"]}'
             for b in data['blocked'][:10]]))

    if for_client and rows:
        r = rows[0]
        if r['end_date']:
            blocks.append(el.para(f'Target completion: {r["end_date"]}.',
                                  muted=True, size=13))

    html = el.render(heading, blocks,
                     preheader=f'{t["tasks_done"]} of {t["tasks"]} tasks done, '
                               f'{t["tasks_overdue"]} overdue.',
                     footer_note='Generated by Sentinel from the project tracker.')

    text_rows = '\n'.join(
        f'{r["name"]} ({r["client"] or "no client"}): {r["status_display"]}, '
        f'{r["tasks_done"]}/{r["tasks_total"]} done, {r["tasks_overdue"]} overdue'
        for r in rows)
    text = (f'{heading}\n{"=" * len(heading)}\n\n'
            + (f'{message}\n\n' if message else '')
            + f'Open {t["tasks_open"]} | Done {t["tasks_done"]} | '
              f'Overdue {t["tasks_overdue"]}\n\n{text_rows}\n')
    return heading, html, text


def send(report_type='general', recipients=(), days=30, project_name='',
         workspace='', title='', message='', user=None, for_client=False):
    """Send a report and record what was sent. Returns the SentReport row."""
    from .views import _graph_send_simple

    data = metrics(days=days, project_name=project_name, workspace=workspace)
    heading, html, text = build_email(data, report_type, title, message,
                                      for_client=for_client)

    to = [a.strip() for a in recipients if a and a.strip()]
    if not to:
        raise ValueError('A report needs at least one recipient.')

    banner = el.banner_attachment()
    ok, errors = [], []
    for address in to:
        sent, msg = _graph_send_simple(
            address, heading, body_html=html, body_text=text,
            attachments=[banner] if banner else [])
        (ok if sent else errors).append(address if sent else f'{address}: {msg}')
        if not sent:
            logger.error('[project-report] to %s failed: %s', address, msg)

    status = 'sent' if not errors else ('partial' if ok else 'failed')
    row = SentReport.objects.create(
        report_type=report_type, title=heading, sent_by=user,
        recipients=', '.join(to), custom_message=message,
        payload=data, project_name=project_name,
        status=status, error='; '.join(errors)[:2000])

    # The activity feed should show that a client was told something.
    TaskActivity.objects.create(
        project_name=project_name, user=user, kind='report',
        field=report_type, new_value=', '.join(to)[:300],
        note=heading[:300])

    logger.info('[project-report] %s to %s: %s', report_type, to, status)
    return row
