"""The Up Management Report, computed. Nothing on this report is typed into it.

Every figure and every line of commentary is derived from what the platform
already holds - projects, tasks, activity, tickets, risks and service
agreements. There are no fields to fill in, because a weekly report that
depends on someone remembering to fill it in is a weekly report that is
sometimes wrong and sometimes missing.

Where the template asks for something that is a judgement rather than a fact,
it is derived from a measurable proxy and labelled as such:

* Sprint - the week's position inside the project's own start-to-end window.
* Comments - assembled from what actually happened: what closed, what is
  blocked, what is late.
* Split goal - each client's share of the open work, which is what the split
  currently *is*; the template's version was an intention, and an intention
  nobody records is not reportable.
* Staff morale - computed from workload pressure (overdue share, capacity
  overrun, blocked work) and named "delivery pressure" on the report, because
  claiming to measure how people feel from their task list would be dishonest.

Automated report syncs are excluded throughout: the tracker holds 401 rows of
five report names repeated daily, and counting them made this report claim 405
open tasks against 4 real ones.
"""
import logging
from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from .management_report import (BLOCKED_STATES, DONE_STATES, _who,
                                week_start_for)
from .models import (ManagementReport, ProjectMeta, ProjectTask, RiskItem,
                     ServiceAgreement, SupportTicket, TaskActivity)

logger = logging.getLogger(__name__)

DELIVERY_STREAMS = ['web', 'app', 'api']
STREAM_LABELS = dict(ProjectTask.STREAM_CHOICES)

# A working week per person, for the pressure calculation.
HOURS_PER_PERSON_PER_WEEK = 40

# How the computed pressure maps onto the template's five-point row. Ordered
# worst to best, matching the document.
PRESSURE_SCALE = [
    ('depleted', 'Depleted'),
    ('inefficient', 'Inefficient'),
    ('cruising', 'Cruising'),
    ('momentum', 'Maintaining Momentum'),
    ('visionary', 'Pro-Active & Visionary Mindset'),
]


def _iso(d):
    return d.isoformat() if d else None


def _client_of(project_name, projects):
    p = projects.get(project_name)
    return (p.client or p.name) if p else 'Unallocated'


def _open(tasks):
    return [t for t in tasks
            if t.status not in DONE_STATES and t.status != 'cancelled']


# ══════════════════════════════════════════════════════════════════════════════
# Derivations that replace what used to be typed
# ══════════════════════════════════════════════════════════════════════════════

def _sprint_label(project, week_start):
    """Which sprint of the project this week is.

    Counted in two-week blocks from the project's start date, which is the
    common shape and needs nothing entered. A project with no start date has
    no sprint to report, and says so rather than inventing one.
    """
    if project is None or not project.start_date:
        return ''
    days = (week_start - project.start_date).days
    if days < 0:
        return 'Not started'
    sprint = days // 14 + 1
    if project.end_date:
        total = max(1, ((project.end_date - project.start_date).days // 14) + 1)
        return f'Sprint {sprint} of {total}'
    return f'Sprint {sprint}'


def _issue_number(week_start):
    """The report's sequence number, counted from the first week recorded."""
    first = (ManagementReport.objects.order_by('week_start')
             .values_list('week_start', flat=True).first())
    if not first:
        return '1'
    weeks = max(0, (week_start - first).days // 7)
    return str(weeks + 1)


def _last_touched(client, projects, activity):
    """When anything on this client last moved."""
    names = {p.name for p in projects.values()
             if (p.client or p.name) == client}
    dates = [a.created_at for a in activity if a.project_name in names]
    return _iso(timezone.localtime(max(dates)).date()) if dates else None


def _commentary(card, own, week_start):
    """The comments column, written from what happened.

    Assembled from facts rather than left blank: what closed this week, what is
    stuck and why, and what is late. If nothing happened it says so, which is
    itself the useful reading.
    """
    bits = []
    wins = card['wins_this_week']
    if wins:
        bits.append(f'Closed {len(wins)} item(s) this week: '
                    + '; '.join(w['title'] for w in wins[:4])
                    + ('…' if len(wins) > 4 else '') + '.')
    blocked = [t for t in own if t.status in BLOCKED_STATES]
    if blocked:
        by_state = {}
        for t in blocked:
            by_state.setdefault(t.get_status_display(), []).append(t.title)
        bits.append('Held up: ' + '; '.join(
            f'{state} - {", ".join(titles[:2])}'
            for state, titles in by_state.items()) + '.')
    today = timezone.localdate()
    late = [t for t in _open(own) if t.end_date and t.end_date < today]
    if late:
        worst = max(late, key=lambda t: (today - t.end_date).days)
        bits.append(f'{len(late)} item(s) past due, the oldest by '
                    f'{(today - worst.end_date).days} days ({worst.title}).')
    pending = [t for t in own if t.status in ('review_pending', 'discrepancy')]
    if pending:
        bits.append(f'{len(pending)} item(s) awaiting client sign-off.')
    if not bits:
        bits.append('No movement recorded this week.')
    return ' '.join(bits)


def _delivery_pressure(tasks, people_count):
    """The five-point row, computed from workload rather than asked about.

    Three measurable signals: how much of the open work is late, whether the
    committed hours exceed the team's week, and how much is blocked. Reported
    as "delivery pressure" because that is what it measures - calling it
    morale would be claiming to know something this cannot know.
    """
    open_tasks = _open(tasks)
    if not open_tasks:
        return {'value': 'cruising', 'label': 'Cruising',
                'reason': 'No open delivery work.', 'score': 2,
                'signals': {}}

    today = timezone.localdate()
    late = [t for t in open_tasks if t.end_date and t.end_date < today]
    blocked = [t for t in open_tasks if t.status in BLOCKED_STATES]
    committed = sum(float(t.estimated_hours or 0) for t in open_tasks)
    capacity = max(1, people_count) * HOURS_PER_PERSON_PER_WEEK

    late_share = len(late) / len(open_tasks)
    blocked_share = len(blocked) / len(open_tasks)
    load = committed / capacity if capacity else 0

    # Start at the top and come down for each pressure signal.
    score = 4
    reasons = []
    # Graduated, because the first version scored 100% overdue as "Cruising" -
    # a scale that cannot say "this is bad" is not worth putting on a report.
    if late_share >= 0.75:
        score -= 3
        reasons.append(f'{late_share:.0%} of open work is past due')
    elif late_share >= 0.5:
        score -= 2
        reasons.append(f'{late_share:.0%} of open work is past due')
    elif late_share >= 0.2:
        score -= 1
        reasons.append(f'{late_share:.0%} of open work is past due')
    if load > 1.2:
        score -= 1
        reasons.append(f'committed hours are {load:.0%} of capacity')
    if blocked_share >= 0.2:
        score -= 1
        reasons.append(f'{blocked_share:.0%} of open work is blocked')
    score = max(0, min(4, score))

    value, label = PRESSURE_SCALE[score]
    return {
        'value': value, 'label': label, 'score': score,
        'reason': ('; '.join(reasons) + '.') if reasons
                  else 'No overdue, capacity or blocking pressure detected.',
        'signals': {
            'open': len(open_tasks), 'overdue': len(late),
            'blocked': len(blocked),
            'committed_hours': round(committed, 1),
            'capacity_hours': capacity,
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
# 1. Highlights / Wins
# ══════════════════════════════════════════════════════════════════════════════

def _highlights(week_start, projects, tasks, activity):
    week_end = week_start + timedelta(days=6)
    tickets = list(SupportTicket.objects.all())

    by_client = {}
    for t in tasks:
        by_client.setdefault(_client_of(t.project_name, projects), []).append(t)

    cards = []
    for client, own in sorted(by_client.items()):
        client_projects = [p for p in projects.values()
                           if (p.client or p.name) == client]
        dated = [p for p in client_projects if p.end_date]
        soonest = min(dated, key=lambda p: p.end_date) if dated else (
            client_projects[0] if client_projects else None)

        streams = {}
        for key in DELIVERY_STREAMS + ['support', 'internal', '']:
            in_stream = [t for t in own if (t.stream or '') == key]
            if not in_stream and key not in DELIVERY_STREAMS:
                continue
            done = [t for t in in_stream if t.status in DONE_STATES]
            streams[key or 'unclassified'] = {
                'label': STREAM_LABELS.get(key, 'Unclassified'),
                'completed': len(done),
                'outstanding': len(_open(in_stream)),
                'completed_this_week': len([
                    t for t in done if t.completed_at
                    and week_start <= timezone.localtime(t.completed_at).date() <= week_end]),
            }

        mine = [k for k in tickets if k.client == client]
        card = {
            'client': client,
            'projects': [p.name for p in client_projects],
            'sprint': _sprint_label(soonest, week_start),
            'project': soonest.name if soonest else '',
            'project_due_date': _iso(soonest.end_date) if soonest else None,
            'streams': streams,
            'development': {
                'completed': len([t for t in own if t.status in DONE_STATES]),
                'outstanding': len(_open(own)),
            },
            'tickets': {
                'raised_total': len(mine),
                'open': len([k for k in mine if k.is_open]),
                'closed': len([k for k in mine if not k.is_open]),
                'raised_this_week': len([
                    k for k in mine
                    if week_start <= timezone.localtime(k.opened_at).date() <= week_end]),
            },
            'wins_this_week': [
                {'title': t.title, 'stream': STREAM_LABELS.get(t.stream or '', ''),
                 'owners': [_who(u) for u in t.assigned_users.all()]}
                for t in own
                if t.completed_at
                and week_start <= timezone.localtime(t.completed_at).date() <= week_end],
            'blocked': len([t for t in own if t.status in BLOCKED_STATES]),
            'last_report_update': _last_touched(client, projects, activity),
        }
        card['comments'] = _commentary(card, own, week_start)
        cards.append(card)
    return cards


# ══════════════════════════════════════════════════════════════════════════════
# 2. Risk
# ══════════════════════════════════════════════════════════════════════════════

def _risk_table(projects, tasks):
    """The register, plus the risks the tracker can see for itself.

    A recorded risk is reported as entered. On top of that, conditions the
    system can detect - work stalled a long time, no owner, a project with no
    dates - are reported as observed risks, so the section is not empty just
    because nobody has written anything down.
    """
    rows = [
        {'id': r.id, 'source': 'register', 'days_late': 0,
         'description': r.title, 'detail': r.detail,
         'kind': r.get_kind_display(), 'owner': _who(r.owner),
         'resolution_time': r.resolution_time,
         'severity': r.severity, 'severity_display': r.get_severity_display(),
         'mitigation': r.mitigation, 'status_display': r.get_status_display(),
         'client': r.client, 'project': r.project_name,
         'review_date': _iso(r.review_date), 'review_overdue': r.review_overdue,
         'score': r.score, 'devops_url': r.devops_url}
        for r in RiskItem.objects.select_related('owner') if r.is_open
    ]

    today = timezone.localdate()
    observed = []

    very_late = [t for t in _open(tasks)
                 if t.end_date and (today - t.end_date).days >= 14]
    for t in sorted(very_late, key=lambda x: x.end_date)[:8]:
        days = (today - t.end_date).days
        # The project name is only worth naming when it is not simply the task
        # title again, and a project literally called "None" is worse than
        # saying nothing.
        where = (t.project_name or '').strip()
        prefix = (f'{where}: ' if where and where.lower() != 'none'
                  and where.lower() != (t.title or '').strip().lower() else '')
        observed.append({
            'id': None, 'source': 'observed',
            'description': f'{prefix}{t.title} is {days} days late',
            'days_late': days,
            'kind': 'Late work',
            'owner': ', '.join(_who(u) for u in t.assigned_users.all()),
            'resolution_time': '',
            'severity': 'high' if days >= 30 else 'medium',
            'severity_display': 'High' if days >= 30 else 'Medium',
            'mitigation': '', 'status_display': 'Observed',
            'client': _client_of(t.project_name, projects),
            'project': t.project_name, 'review_date': None,
            'review_overdue': False, 'score': 6 if days >= 30 else 4,
            'devops_url': '',
        })

    unowned = [t for t in _open(tasks) if not t.assigned_users.exists()]
    if len(unowned) >= 3:
        observed.append({
            'id': None, 'source': 'observed',
            'description': f'{len(unowned)} open jobs have nobody assigned '
                           'to them',
            'days_late': 0,
            'kind': 'No owner', 'owner': '', 'resolution_time': '',
            'severity': 'medium', 'severity_display': 'Medium',
            'mitigation': '', 'status_display': 'Observed',
            'client': '', 'project': '', 'review_date': None,
            'review_overdue': False, 'score': 4, 'devops_url': '',
        })

    undated = [p for p in projects.values() if not p.end_date]
    if undated:
        observed.append({
            'id': None, 'source': 'observed',
            'description': f'{len(undated)} projects have no finish date, so '
                           'nothing can be planned for them: '
                           + ', '.join(p.name for p in undated[:4]),
            'days_late': 0,
            'kind': 'No dates', 'owner': '', 'resolution_time': '',
            'severity': 'low', 'severity_display': 'Low',
            'mitigation': '', 'status_display': 'Observed',
            'client': '', 'project': '', 'review_date': None,
            'review_overdue': False, 'score': 2, 'devops_url': '',
        })

    return sorted(rows + observed, key=lambda r: -r['score'])


# ══════════════════════════════════════════════════════════════════════════════
# 3. Focus matrix
# ══════════════════════════════════════════════════════════════════════════════

def _focus_matrix(projects, tasks, buckets):
    """Where the effort actually is, from hours and item counts.

    The template asked for a planned split. Nothing in the platform records an
    intention, so this reports the real one: each person's open hours across
    clients, and each client's share of the open work.
    """
    open_tasks = _open(tasks)

    hours, items = {}, {}
    for t in open_tasks:
        bucket = _client_of(t.project_name, projects)
        est = float(t.estimated_hours or 0)
        assignees = list(t.assigned_users.all())
        for u in assignees:
            hours[(u.id, bucket)] = hours.get((u.id, bucket), 0) + est
            items[(u.id, bucket)] = items.get((u.id, bucket), 0) + 1

    # Only people who actually hold work: a matrix of empty columns for every
    # account on the system is noise.
    active_ids = {uid for (uid, _b) in items}
    people = [u for u in User.objects.filter(id__in=active_ids)
              .order_by('first_name', 'username')]

    totals_by_person = {}
    for (uid, _b), v in items.items():
        totals_by_person[uid] = totals_by_person.get(uid, 0) + v

    staff_rows = []
    for bucket in buckets:
        cells = []
        for u in people:
            n = items.get((u.id, bucket), 0)
            total = totals_by_person.get(u.id, 0)
            cells.append({
                'person_id': u.id,
                'share_pct': round(n * 100 / total, 1) if total else None,
                'items': n or None,
                'hours': round(hours.get((u.id, bucket), 0), 1) or None,
            })
        staff_rows.append({'bucket': bucket, 'cells': cells,
                           'items': sum(c['items'] or 0 for c in cells)})

    person_totals = []
    for u in people:
        p_hours = sum(hours.get((u.id, b), 0) for b in buckets)
        person_totals.append({
            'person_id': u.id, 'person': _who(u),
            'initials': ''.join(x[0] for x in (_who(u) or 'U').split()[:2]).upper(),
            'items': totals_by_person.get(u.id, 0),
            'hours': round(p_hours, 1),
            'over_capacity': p_hours > HOURS_PER_PERSON_PER_WEEK,
        })

    total_open = len(open_tasks) or 1
    week_start = week_start_for()
    week_end = week_start + timedelta(days=6)
    company_rows = []
    for bucket in buckets:
        own = [t for t in tasks if _client_of(t.project_name, projects) == bucket]
        own_open = _open(own)
        done_week = [t for t in own if t.completed_at
                     and week_start <= timezone.localtime(t.completed_at).date() <= week_end]
        dates = [t.end_date for t in own_open if t.end_date]
        support = [t for t in own if t.stream == 'support']
        company_rows.append({
            'bucket': bucket,
            # The share of open work this client represents. That is the split
            # as it stands, which is the thing a manager can act on.
            'share_pct': round(len(own_open) * 100 / total_open, 1),
            'support_pct': round(len(support) * 100 / len(own), 1) if own else 0.0,
            'work_items_done': len(done_week),
            'to_be_completed': len(own_open),
            'due_date': _iso(min(dates)) if dates else None,
        })

    return {
        'people': person_totals,
        'staff_rows': staff_rows,
        'company_rows': company_rows,
        'unassigned_items': len([t for t in open_tasks
                                 if not t.assigned_users.exists()]),
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. Financial components
# ══════════════════════════════════════════════════════════════════════════════

def _financial(buckets, projects, tasks):
    """Read from the service agreements, with the next deliverable computed."""
    agreements = {a.client: a for a in
                  ServiceAgreement.objects.filter(is_active=True)
                  .select_related('owner')}
    rows = []
    for bucket in buckets:
        a = agreements.get(bucket)
        own_open = _open([t for t in tasks
                          if _client_of(t.project_name, projects) == bucket])
        dated = [t for t in own_open if t.end_date]
        nxt = min(dated, key=lambda t: t.end_date) if dated else None
        rows.append({
            'bucket': bucket,
            # The next thing actually due, rather than a sentence about it.
            'next_deliverable': (f'{nxt.title} ({nxt.end_date:%d %b})'
                                 if nxt else ''),
            'next_invoice_date': _iso(a.next_invoice_date) if a else None,
            'sla_active': bool(a and (a.response_hours or a.resolution_hours)),
            'sla_summary': (f'{a.get_tier_display()}, {a.response_hours}h/'
                            f'{a.resolution_hours}h' if a and a.response_hours
                            else (a.get_tier_display() if a else '')),
            'hosting_capacity': (a.hosting_capacity or a.hosting_provider) if a else '',
            'is_reconciled': bool(a and a.is_reconciled),
            'monthly_fee': float(a.monthly_fee) if a and a.monthly_fee else None,
            'renewal_date': _iso(a.renewal_date) if a else None,
            'owner': _who(a.owner) if a else '',
            'has_agreement': a is not None,
        })
    return rows


# ══════════════════════════════════════════════════════════════════════════════
# 5. Plan for next week
# ══════════════════════════════════════════════════════════════════════════════

def _next_week(week_start, buckets, projects, tasks):
    """What is actually due next week, per client, with who holds it."""
    start = week_start + timedelta(days=7)
    end = start + timedelta(days=6)
    today = timezone.localdate()

    rows = []
    for bucket in buckets:
        own_open = _open([t for t in tasks
                          if _client_of(t.project_name, projects) == bucket])
        due = [t for t in own_open if t.end_date and start <= t.end_date <= end]
        carried = [t for t in own_open if t.end_date and t.end_date < today]
        items = [
            {'title': t.title, 'due': _iso(t.end_date),
             'owner': ', '.join(_who(u) for u in t.assigned_users.all()),
             'stream': STREAM_LABELS.get(t.stream or '', ''),
             'is_overdue': False}
            for t in sorted(due, key=lambda x: x.end_date)
        ] + [
            {'title': t.title, 'due': _iso(t.end_date),
             'owner': ', '.join(_who(u) for u in t.assigned_users.all()),
             'stream': STREAM_LABELS.get(t.stream or '', ''),
             'is_overdue': True}
            for t in sorted(carried, key=lambda x: x.end_date)[:5]
        ]
        owners = sorted({o for i in items for o in i['owner'].split(', ') if o})
        dates = [t.end_date for t in due]
        note_parts = []
        if due:
            note_parts.append(f'{len(due)} item(s) due next week.')
        if carried:
            note_parts.append(f'{len(carried)} overdue item(s) carried in.')
        if not note_parts:
            note_parts.append('Nothing scheduled for next week.')
        rows.append({
            'bucket': bucket,
            'note': ' '.join(note_parts),
            'due_date': _iso(min(dates)) if dates else None,
            'responsibility': ', '.join(owners) or 'unassigned',
            'items': items,
        })
    return {'rows': rows}


# ══════════════════════════════════════════════════════════════════════════════
# Assembly
# ══════════════════════════════════════════════════════════════════════════════

def build(week_start=None):
    """The whole report, computed. No inputs."""
    week_start = week_start or week_start_for()
    week_end = week_start + timedelta(days=6)

    projects = {p.name: p for p in
                ProjectMeta.objects.filter(is_automated=False)
                .select_related('workspace').prefetch_related('assigned_users')}
    tasks = list(ProjectTask.objects.filter(project_name__in=projects)
                 .prefetch_related('assigned_users'))
    activity = list(TaskActivity.objects.filter(
        created_at__gte=timezone.now() - timedelta(days=120)))

    buckets = []
    for p in projects.values():
        name = p.client or p.name
        if name not in buckets:
            buckets.append(name)

    highlights = _highlights(week_start, projects, tasks, activity)
    focus = _focus_matrix(projects, tasks, buckets)
    pressure = _delivery_pressure(tasks, len(focus['people']))

    excluded = ProjectMeta.objects.filter(is_automated=True).count()

    return {
        'header': {
            'title': 'Up Management Report',
            # Nobody types this: the platform produced it.
            'developed_by': 'Sentinel (computed from the project tracker)',
            'developed_for': 'Management',
            'week_start': _iso(week_start),
            'week_ending': _iso(week_end),
            'issue_number': _issue_number(week_start),
            'report_version': 'V3',
            'generated_at': timezone.now().isoformat(),
        },
        'buckets': buckets,
        'highlights': highlights,
        'risks': _risk_table(projects, tasks),
        'focus': focus,
        'pressure': pressure,
        'financial': _financial(buckets, projects, tasks),
        'next_week': _next_week(week_start, buckets, projects, tasks),
        'streams': [{'value': v, 'label': l}
                    for v, l in ProjectTask.STREAM_CHOICES],
        'notes': {
            'unclassified_tasks': len([t for t in _open(tasks) if not t.stream]),
            'automated_projects_excluded': excluded,
            'projects_without_client': len([p for p in projects.values()
                                            if not p.client]),
            'projects_without_dates': len([p for p in projects.values()
                                           if not p.end_date]),
        },
        # Said plainly, because a computed report has to be answerable.
        'how_it_is_derived': [
            'Sprint: the week\'s position in two-week blocks from the project start date.',
            'Comments: assembled from what closed, what is blocked and what is late.',
            'Last update: the most recent recorded change on that client\'s projects.',
            'Focus %: each person\'s share of their own open items, by client.',
            'Split: each client\'s share of all open delivery work.',
            'Delivery pressure: overdue share, committed hours against capacity, '
            'and blocked share. It measures workload, not how people feel.',
            'Next deliverable and next week: the open tasks with the nearest due dates.',
            'Financial: read from the client\'s service agreement.',
        ],
    }


# ══════════════════════════════════════════════════════════════════════════════
# The same figures, shaped for charts
# ══════════════════════════════════════════════════════════════════════════════

def _verdict(totals, pressure, notes, focus, risks, oldest_days, streams):
    """One plain sentence saying what is going on, plus what to do about it.

    Computed here rather than in the page so the words are part of the report
    and not a front-end flourish: the same sentence can go in the PDF or an
    email without being written twice.

    Deliberately free of the report's own vocabulary - no "delivery pressure",
    no "outstanding", no "accountability risk". A reader who has never seen
    this report before should get it on the first pass.
    """
    late = pressure['signals']['overdue']
    open_now = totals['outstanding']

    if open_now == 0:
        tone, headline = 'good', 'Nothing is open. Everything raised has been finished.'
    elif late == 0:
        tone = 'good'
        headline = (f'{open_now} job{"" if open_now == 1 else "s"} still open, '
                    'and none of them are late.')
    elif late == open_now:
        tone = 'bad'
        headline = (f'All {late} open job{"" if late == 1 else "s"} '
                    f'{"is" if late == 1 else "are"} late - the oldest by '
                    f'{oldest_days} days.')
    else:
        tone = 'warn'
        headline = (f'{late} of the {open_now} open jobs '
                    f'{"is" if late == 1 else "are"} late - the oldest by '
                    f'{oldest_days} days.')

    # What to do next, worst first. Each line names the number, so it reads as
    # a job of work rather than a complaint.
    actions = []
    if focus['unassigned_items']:
        actions.append(f'Give the {focus["unassigned_items"]} open '
                       f'job{"" if focus["unassigned_items"] == 1 else "s"} '
                       'an owner - right now nobody is responsible for any '
                       'of them.')
    if notes['projects_without_dates']:
        actions.append(f'Put a finish date on '
                       f'{notes["projects_without_dates"]} project'
                       f'{"" if notes["projects_without_dates"] == 1 else "s"} '
                       'so the report can tell you what is due when.')
    if totals['blocked']:
        actions.append(f'{totals["blocked"]} job'
                       f'{" is" if totals["blocked"] == 1 else "s are"} '
                       'blocked and need a decision from someone.')
    if len(streams) < 2 and totals['completed'] + totals['outstanding']:
        actions.append('Mark each job as WEB, APP, API, support or internal, '
                       'and the report will show where the effort goes.')
    if notes['projects_without_client']:
        actions.append(f'{notes["projects_without_client"]} project'
                       f'{"" if notes["projects_without_client"] == 1 else "s"} '
                       'have no client attached, so they are listed under '
                       'their own name.')

    return {'tone': tone, 'headline': headline, 'actions': actions[:4],
            'scale_label': pressure['label'], 'scale_reason': pressure['reason']}


def dashboard(week_start=None):
    """The report as a dashboard payload.

    Same computation, different shape: series ready to draw rather than table
    rows. Built on top of build() rather than beside it, so a chart and the PDF
    can never disagree about a number.

    Includes the table-view rows for every chart, because a chart whose values
    are only reachable by hovering fails an accessibility check - and a manager
    reading a printout has no hover.
    """
    data = build(week_start)
    cards = data['highlights']
    risks = data['risks']

    # Part-to-whole by stream. Four segments, wildly unequal - the one place a
    # donut is honestly the right form here.
    streams = {}
    for card in cards:
        for key, s in card['streams'].items():
            row = streams.setdefault(key, {'label': s['label'], 'completed': 0,
                                           'outstanding': 0})
            row['completed'] += s['completed']
            row['outstanding'] += s['outstanding']
    stream_rows = [
        {'key': k, 'label': v['label'],
         'total': v['completed'] + v['outstanding'],
         'completed': v['completed'], 'outstanding': v['outstanding']}
        for k, v in streams.items()
        if v['completed'] or v['outstanding']
    ]
    stream_rows.sort(key=lambda r: -r['total'])

    # Completed against outstanding per client. A stacked bar, not a pie: seven
    # clients with several identical shares is exactly the case a pie misreads.
    client_rows = sorted(
        ({'client': c['client'],
          'completed': c['development']['completed'],
          'outstanding': c['development']['outstanding'],
          'overdue': sum(1 for r in risks
                         if r.get('client') == c['client']
                         and r.get('days_late')),
          'blocked': c['blocked'],
          'total': c['development']['completed'] + c['development']['outstanding']}
         for c in cards),
        key=lambda r: -r['total'])

    severity_order = ['critical', 'high', 'medium', 'low']
    severity = {s: 0 for s in severity_order}
    for r in risks:
        if r['severity'] in severity:
            severity[r['severity']] += 1

    # Overdue ageing, in bands. Bands rather than a count per task: the reader
    # wants "how bad", not a list of 141s.
    ages = [r['days_late'] for r in risks if r.get('days_late')]
    bands = [('1-7 days', 1, 7), ('8-30 days', 8, 30),
             ('31-90 days', 31, 90), ('90+ days', 91, 10 ** 6)]
    ageing = [{'band': label,
               'count': sum(1 for a in ages if low <= a <= high)}
              for label, low, high in bands]
    # The single worst case, so a reader who does not need the bands can be
    # told "oldest is 141 days" in one line instead.
    oldest_overdue_days = max(ages) if ages else 0

    tickets = {
        'open': sum(c['tickets']['open'] for c in cards),
        'closed': sum(c['tickets']['closed'] for c in cards),
        'raised_this_week': sum(c['tickets']['raised_this_week'] for c in cards),
    }
    totals = {
        'clients': len(cards),
        'completed': sum(c['development']['completed'] for c in cards),
        'outstanding': sum(c['development']['outstanding'] for c in cards),
        'closed_this_week': sum(
            s['completed_this_week'] for c in cards
            for s in c['streams'].values()),
        'blocked': sum(c['blocked'] for c in cards),
        'risks': len(risks),
        'severe_risks': severity['critical'] + severity['high'],
    }

    return {
        'header': data['header'],
        'verdict': _verdict(totals, data['pressure'], data['notes'],
                            data['focus'], risks, oldest_overdue_days,
                            stream_rows),
        'pressure': data['pressure'],
        'totals': totals,
        'tickets': tickets,
        'streams': stream_rows,
        'clients': client_rows,
        'severity': [{'severity': s, 'count': severity[s]}
                     for s in severity_order],
        'ageing': ageing,
        'oldest_overdue_days': oldest_overdue_days,
        'focus': data['focus'],
        'financial': data['financial'],
        'next_week': data['next_week'],
        'risks': risks,
        'notes': data['notes'],
        'how_it_is_derived': data['how_it_is_derived'],
    }
