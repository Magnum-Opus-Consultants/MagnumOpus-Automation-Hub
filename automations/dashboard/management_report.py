"""The weekly management report: eight sections, and the chase that follows it.

Built to a brief that asked for a holistic weekly view of client delivery and
departmental capacity, and was explicit that the report must "drive execution -
not merely record activity". So this module does two things:

`build()` assembles the eight required sections:

    1. clients and active projects
    2. current tasks, deliverables and deadlines
    3. completed, outstanding and blocked work
    4. responsible persons and agreed actions
    5. support tickets, risks and technical debt
    6. SLA, hosting and service requirements
    7. team capacity and weekly priorities
    8. matters requiring escalation or a management decision

`chase()` is the execution half: it tells owners what is theirs, asks them to
confirm, counts how many weeks an action has been reported without moving, and
flags what should be escalated. A report nobody is answerable to is a document;
this is the part that makes it a process.

Sections are computed for a named week rather than "now", so last week's report
still reads as last week's report.
"""
import logging
from datetime import date, timedelta

from django.contrib.auth.models import User
from django.db.models import Q
from django.utils import timezone

from . import email_layout as el
from .models import (ManagementAction, ManagementReport, ProjectMeta,
                     ProjectTask, RiskItem, ServiceAgreement, SupportTicket,
                     TaskActivity, WeeklyFocus)

logger = logging.getLogger(__name__)

DONE_STATES = {'done', 'review_pending', 'discrepancy'}
ACCEPTED_STATES = {'done'}
BLOCKED_STATES = {'in_progress_guidance', 'on_hold'}
ACTIVE_PROJECT_STATES = {'planned', 'in_progress', 'in_progress_guidance',
                         'completed_review_pending', 'completed_discrepancy'}

# A working week, for the capacity figure. Stated here rather than assumed
# elsewhere so it can be argued with in one place.
HOURS_PER_PERSON_PER_WEEK = 40


def week_start_for(d=None):
    """The Monday of that week."""
    d = d or timezone.localdate()
    return d - timedelta(days=d.weekday())


def _who(user):
    if user is None:
        return ''
    return user.get_full_name() or user.username


def _iso(d):
    return d.isoformat() if d else None


# ══════════════════════════════════════════════════════════════════════════════
# The eight sections
# ══════════════════════════════════════════════════════════════════════════════

def _clients_and_projects(projects, tasks, agreements):
    """Section 1: each client and active project."""
    by_client = {}
    for p in projects:
        client = p.client or 'Unassigned client'
        mine = [t for t in tasks if t.project_name == p.name]
        done = [t for t in mine if t.status in DONE_STATES]
        entry = by_client.setdefault(client, {
            'client': client, 'projects': [], 'tasks': 0, 'done': 0,
            'overdue': 0, 'blocked': 0, 'agreement': None})
        today = timezone.localdate()
        overdue = [t for t in mine if t.end_date and t.end_date < today
                   and t.status not in DONE_STATES]
        blocked = [t for t in mine if t.status in BLOCKED_STATES]
        entry['projects'].append({
            'name': p.name,
            'status': p.status, 'status_display': p.get_status_display(),
            'priority': p.priority,
            'is_active': p.status in ACTIVE_PROJECT_STATES,
            'start_date': _iso(p.start_date), 'end_date': _iso(p.end_date),
            'quoted_hours': float(p.quoted_hours) if p.quoted_hours else None,
            'actual_hours': float(sum((t.actual_hours or 0) for t in mine)) or None,
            'tasks': len(mine), 'done': len(done),
            'overdue': len(overdue), 'blocked': len(blocked),
            'progress': round(len(done) * 100 / len(mine)) if mine else 0,
            'team': [_who(u) for u in p.assigned_users.all()],
        })
        entry['tasks'] += len(mine)
        entry['done'] += len(done)
        entry['overdue'] += len(overdue)
        entry['blocked'] += len(blocked)

    for a in agreements:
        row = by_client.get(a.client)
        if row and not row['agreement']:
            row['agreement'] = {
                'tier': a.get_tier_display(),
                'response_hours': a.response_hours,
                'resolution_hours': a.resolution_hours,
                'support_window': a.support_window,
                'hosting_provider': a.hosting_provider,
                'renewal_date': _iso(a.renewal_date),
                'renews_in_days': a.renews_in_days,
            }
    return sorted(by_client.values(), key=lambda r: (-r['overdue'], -r['tasks']))


def _deadlines(tasks, week_start):
    """Section 2: current tasks, deliverables and deadlines."""
    week_end = week_start + timedelta(days=6)
    today = timezone.localdate()

    def row(t):
        return {
            'project': t.project_name or '(no project)',
            'title': t.title,
            'status': t.status, 'status_display': t.get_status_display(),
            'priority': t.priority,
            'development': t.get_development_status_display()
                           if t.development_status else '',
            'due': _iso(t.end_date),
            'owners': [_who(u) for u in t.assigned_users.all()],
            'estimated_hours': float(t.estimated_hours) if t.estimated_hours else None,
            'days_late': (today - t.end_date).days if t.end_date and t.end_date < today else 0,
        }

    open_tasks = [t for t in tasks if t.status not in DONE_STATES
                  and t.status != 'cancelled']
    all_overdue = [t for t in open_tasks if t.end_date and t.end_date < today]
    return {
        # Counted separately from the list below, which is truncated for
        # display. Reading the headline off a capped list reported 40 overdue
        # tasks when there were 405.
        'overdue_count': len(all_overdue),
        'due_this_week': [row(t) for t in open_tasks
                          if t.end_date and week_start <= t.end_date <= week_end],
        'due_next_week': [row(t) for t in open_tasks
                          if t.end_date
                          and week_end < t.end_date <= week_end + timedelta(days=7)],
        'overdue': sorted(
            [row(t) for t in open_tasks if t.end_date and t.end_date < today],
            key=lambda r: -r['days_late'])[:40],
        'no_due_date': len([t for t in open_tasks if not t.end_date]),
    }


def _work_state(tasks, week_start):
    """Section 3: completed, outstanding and blocked work."""
    week_end = week_start + timedelta(days=6)
    completed_this_week = [
        t for t in tasks
        if t.completed_at
        and week_start <= timezone.localtime(t.completed_at).date() <= week_end]
    return {
        'completed_this_week': [
            {'project': t.project_name or '(no project)', 'title': t.title,
             'owners': [_who(u) for u in t.assigned_users.all()],
             'when': _iso(timezone.localtime(t.completed_at).date())}
            for t in completed_this_week],
        'completed_total': len([t for t in tasks if t.status in DONE_STATES]),
        'accepted_total': len([t for t in tasks if t.status in ACCEPTED_STATES]),
        'outstanding': len([t for t in tasks if t.status not in DONE_STATES
                            and t.status != 'cancelled']),
        'blocked': [
            {'project': t.project_name or '(no project)', 'title': t.title,
             'status_display': t.get_status_display(),
             'owners': [_who(u) for u in t.assigned_users.all()]}
            for t in tasks if t.status in BLOCKED_STATES],
        # Work finished but not yet agreed by the client, which is the state
        # people forget to chase and the reason those statuses exist.
        'awaiting_client_sign_off': [
            {'project': t.project_name or '(no project)', 'title': t.title,
             'status_display': t.get_status_display()}
            for t in tasks if t.status in ('review_pending', 'discrepancy')],
    }


def _people_and_actions(tasks, week_start):
    """Section 4: responsible persons and agreed actions."""
    load = {}
    for t in tasks:
        if t.status in DONE_STATES or t.status == 'cancelled':
            continue
        for u in t.assigned_users.all():
            row = load.setdefault(u.id, {
                'person': _who(u), 'open_tasks': 0, 'overdue': 0,
                'hours': 0.0, 'projects': set()})
            row['open_tasks'] += 1
            row['hours'] += float(t.estimated_hours or 0)
            if t.project_name:
                row['projects'].add(t.project_name)
            if t.end_date and t.end_date < timezone.localdate():
                row['overdue'] += 1
    people = []
    for row in load.values():
        row['projects'] = sorted(row['projects'])
        people.append(row)
    people.sort(key=lambda r: (-r['overdue'], -r['open_tasks']))

    actions = ManagementAction.objects.select_related('owner', 'raised_by')
    return {
        'people': people,
        'unassigned_open_tasks': len([
            t for t in tasks
            if t.status not in DONE_STATES and t.status != 'cancelled'
            and not t.assigned_users.exists()]),
        'actions': [_action_row(a) for a in actions.filter(
            status__in=('open', 'acknowledged', 'in_progress', 'blocked'))],
        'actions_closed_this_week': [
            _action_row(a) for a in actions.filter(
                status='done',
                completed_at__date__gte=week_start,
                completed_at__date__lte=week_start + timedelta(days=6))],
    }


def _action_row(a):
    return {
        'id': a.id, 'title': a.title, 'detail': a.detail,
        'project': a.project_name, 'client': a.client,
        'owner': _who(a.owner), 'raised_by': _who(a.raised_by),
        'due': _iso(a.due_date), 'status': a.status,
        'status_display': a.get_status_display(),
        'is_overdue': a.is_overdue,
        'needs_decision': a.needs_decision, 'decision': a.decision,
        'notified': bool(a.notified_at),
        'acknowledged': bool(a.acknowledged_at),
        'awaiting_acknowledgement': a.awaiting_acknowledgement,
        'times_reported': a.times_reported,
        'devops_url': a.devops_url,
    }


def _tickets_risks_debt(week_start):
    """Section 5: support tickets, risks and technical debt."""
    week_end = week_start + timedelta(days=6)
    tickets = SupportTicket.objects.select_related('owner')
    open_tickets = [t for t in tickets if t.is_open]
    risks = list(RiskItem.objects.select_related('owner'))

    return {
        'tickets': {
            'open': len(open_tickets),
            'opened_this_week': tickets.filter(
                opened_at__date__gte=week_start,
                opened_at__date__lte=week_end).count(),
            'resolved_this_week': tickets.filter(
                resolved_at__date__gte=week_start,
                resolved_at__date__lte=week_end).count(),
            'response_breaches': [
                {'reference': t.reference or str(t.pk), 'client': t.client,
                 'subject': t.subject, 'priority': t.priority,
                 'owner': _who(t.owner), 'age_days': t.age_days}
                for t in open_tickets if t.response_breached],
            'resolution_breaches': [
                {'reference': t.reference or str(t.pk), 'client': t.client,
                 'subject': t.subject, 'priority': t.priority,
                 'owner': _who(t.owner), 'age_days': t.age_days}
                for t in open_tickets if t.resolution_breached],
            'oldest': [
                {'reference': t.reference or str(t.pk), 'client': t.client,
                 'subject': t.subject, 'status_display': t.get_status_display(),
                 'owner': _who(t.owner), 'age_days': t.age_days,
                 'devops_url': t.devops_url}
                for t in sorted(open_tickets, key=lambda x: x.opened_at)[:10]],
        },
        'risks': [
            {'id': r.id, 'kind': r.kind, 'kind_display': r.get_kind_display(),
             'title': r.title, 'project': r.project_name, 'client': r.client,
             'severity': r.severity, 'severity_display': r.get_severity_display(),
             'likelihood_display': r.get_likelihood_display(),
             'score': r.score, 'status_display': r.get_status_display(),
             'owner': _who(r.owner), 'mitigation': r.mitigation,
             'review_date': _iso(r.review_date),
             'review_overdue': r.review_overdue, 'devops_url': r.devops_url}
            for r in sorted([r for r in risks if r.is_open],
                            key=lambda x: -x.score)],
        'technical_debt_count': len([r for r in risks
                                     if r.kind == 'technical_debt' and r.is_open]),
        'reviews_overdue': len([r for r in risks if r.review_overdue]),
    }


def _service_requirements(agreements):
    """Section 6: SLA, hosting and service requirements."""
    return [
        {'client': a.client, 'project': a.project_name,
         'tier': a.get_tier_display(),
         'response_hours': a.response_hours,
         'resolution_hours': a.resolution_hours,
         'support_window': a.support_window,
         'hosting_provider': a.hosting_provider,
         'environment_url': a.environment_url,
         'backup_schedule': a.backup_schedule,
         'renewal_date': _iso(a.renewal_date),
         'renews_in_days': a.renews_in_days,
         'monthly_fee': float(a.monthly_fee) if a.monthly_fee else None,
         'owner': _who(a.owner), 'notes': a.notes}
        for a in agreements]


def _capacity_and_priorities(tasks, week_start, people_rows):
    """Section 7: team capacity and weekly priorities."""
    week_end = week_start + timedelta(days=6)
    committed = sum(
        float(t.estimated_hours or 0) for t in tasks
        if t.status not in DONE_STATES and t.status != 'cancelled'
        and t.end_date and week_start <= t.end_date <= week_end)

    active_people = max(1, len(people_rows))
    available = active_people * HOURS_PER_PERSON_PER_WEEK

    focus = WeeklyFocus.objects.filter(week_start=week_start).select_related('owner')
    last = WeeklyFocus.objects.filter(
        week_start=week_start - timedelta(days=7))

    return {
        'people_with_work': len(people_rows),
        'hours_per_person': HOURS_PER_PERSON_PER_WEEK,
        'available_hours': available,
        'committed_hours': round(committed, 1),
        'utilisation_pct': round(committed * 100 / available, 1) if available else 0,
        'over_committed': [p['person'] for p in people_rows
                           if p['hours'] > HOURS_PER_PERSON_PER_WEEK],
        'priorities': [
            {'id': f.id, 'title': f.title, 'project': f.project_name,
             'client': f.client, 'owner': _who(f.owner),
             'is_done': f.is_done, 'carried_over': f.carried_over,
             'note': f.note}
            for f in focus],
        'last_week_carried': [
            {'title': f.title, 'owner': _who(f.owner)}
            for f in last if not f.is_done],
    }


def _escalations(tasks, actions_section, register):
    """Section 8: matters requiring escalation or a management decision.

    `register` is the section-5 payload, which holds both the tickets and the
    risks.

    Assembled from the other sections rather than typed by hand, so something
    cannot be quietly left off the escalation list while appearing as a breach
    three sections earlier.
    """
    out = []

    for a in actions_section['actions']:
        if a['needs_decision'] and not a['decision']:
            out.append({'kind': 'decision', 'title': a['title'],
                        'owner': a['owner'], 'why': 'Needs a management decision',
                        'reference': f'action {a["id"]}'})
        elif a['is_overdue']:
            out.append({'kind': 'action', 'title': a['title'],
                        'owner': a['owner'],
                        'why': f'Action overdue (due {a["due"]})',
                        'reference': f'action {a["id"]}'})
        elif a['times_reported'] >= 3 and a['status'] == 'open':
            out.append({'kind': 'stalled', 'title': a['title'],
                        'owner': a['owner'],
                        'why': f'Reported {a["times_reported"]} weeks running '
                               f'without moving',
                        'reference': f'action {a["id"]}'})

    for t in register['tickets']['resolution_breaches']:
        out.append({'kind': 'sla', 'title': f'{t["client"]}: {t["subject"]}',
                    'owner': t['owner'], 'why': 'SLA resolution time breached',
                    'reference': t['reference']})

    for r in register['risks']:
        if r['severity'] in ('critical', 'high') and not r['mitigation']:
            out.append({'kind': 'risk', 'title': r['title'], 'owner': r['owner'],
                        'why': f'{r["severity_display"]} {r["kind_display"].lower()} '
                               f'with no mitigation recorded',
                        'reference': f'risk {r["id"]}'})

    today = timezone.localdate()
    very_late = [t for t in tasks
                 if t.end_date and t.status not in DONE_STATES
                 and (today - t.end_date).days >= 14]
    for t in very_late[:10]:
        out.append({'kind': 'delivery',
                    'title': f'{t.project_name or "(no project)"}: {t.title}',
                    'owner': ', '.join(_who(u) for u in t.assigned_users.all()),
                    'why': f'{(today - t.end_date).days} days past its due date',
                    'reference': f'task {t.id}'})

    if actions_section['unassigned_open_tasks'] > 20:
        out.append({'kind': 'accountability',
                    'title': f'{actions_section["unassigned_open_tasks"]} open tasks '
                             f'have nobody assigned',
                    'owner': '', 'why': 'No responsible person recorded',
                    'reference': 'tracker'})
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Assembly
# ══════════════════════════════════════════════════════════════════════════════

def build(week_start=None):
    """The whole report for a week."""
    week_start = week_start or week_start_for()
    # Delivery only: automated report syncs are excluded, or the figures
    # describe a scheduler rather than a department.
    projects = list(ProjectMeta.objects.filter(is_automated=False)
                    .select_related('workspace')
                    .prefetch_related('assigned_users'))
    names = {p.name for p in projects}
    tasks = list(ProjectTask.objects.filter(project_name__in=names)
                 .prefetch_related('assigned_users'))
    agreements = list(ServiceAgreement.objects.filter(is_active=True)
                      .select_related('owner'))

    clients = _clients_and_projects(projects, tasks, agreements)
    deadlines = _deadlines(tasks, week_start)
    work = _work_state(tasks, week_start)
    people = _people_and_actions(tasks, week_start)
    tickets = _tickets_risks_debt(week_start)
    services = _service_requirements(agreements)
    capacity = _capacity_and_priorities(tasks, week_start, people['people'])
    # `tickets` carries both the ticket figures and the risk register.
    escalations = _escalations(tasks, people, tickets)

    active = [p for c in clients for p in c['projects'] if p['is_active']]

    return {
        'week_start': _iso(week_start),
        'week_end': _iso(week_start + timedelta(days=6)),
        'generated_at': timezone.now().isoformat(),
        'headline': {
            'clients': len(clients),
            'active_projects': len(active),
            'open_tasks': work['outstanding'],
            'completed_this_week': len(work['completed_this_week']),
            'overdue': deadlines['overdue_count'],
            'blocked': len(work['blocked']),
            'open_tickets': tickets['tickets']['open'],
            'open_risks': len(tickets['risks']),
            'open_actions': len(people['actions']),
            'escalations': len(escalations),
            'utilisation_pct': capacity['utilisation_pct'],
        },
        'clients_and_projects': clients,
        'deadlines': deadlines,
        'work': work,
        'people_and_actions': people,
        'tickets_risks_debt': tickets,
        'service_requirements': services,
        'capacity_and_priorities': capacity,
        'escalations': escalations,
    }


def save(week_start=None, user=None, summary='', publish=False):
    """Store the week's report, so what management read stays readable."""
    week_start = week_start or week_start_for()
    data = build(week_start)
    row, _created = ManagementReport.objects.update_or_create(
        week_start=week_start,
        defaults={
            'title': f'Management report - week of {week_start:%d %b %Y}',
            'payload': data,
            'summary': summary,
            'status': 'published' if publish else 'draft',
            'prepared_by': user,
        })
    return row

# ══════════════════════════════════════════════════════════════════════════════
# The execution half
# ══════════════════════════════════════════════════════════════════════════════

def _base_url():
    from django.conf import settings
    return getattr(settings, 'PLATFORM_BASE_URL', 'https://workspace.moc-pty.com')


def chase(week_start=None, notify=True):
    """Make the report drive something.

    The brief was explicit that the report must not merely record activity, so
    this is the part that acts:

    * every open action counts one more week of having been reported, which is
      what turns "still outstanding" into a number somebody can be asked about
    * an unnotified action with an owner gets an email naming what is theirs,
      by when, and asking them to confirm the date is achievable
    * priorities that did not get done last week are carried into this week
      rather than quietly disappearing from the record

    Returns what it actually did, so the page can report that rather than
    claim it.
    """
    week_start = week_start or week_start_for()
    result = {'reported': 0, 'notified': [], 'failed': [], 'carried_over': 0}

    open_actions = list(ManagementAction.objects.filter(
        status__in=('open', 'acknowledged', 'in_progress', 'blocked')
    ).select_related('owner', 'raised_by'))

    for a in open_actions:
        a.times_reported = (a.times_reported or 0) + 1
        a.save(update_fields=['times_reported', 'updated_at'])
        result['reported'] += 1

    if notify:
        for a in open_actions:
            if a.notified_at or not (a.owner and a.owner.email):
                continue
            ok, detail = _notify_owner(a)
            if ok:
                a.notified_at = timezone.now()
                a.save(update_fields=['notified_at', 'updated_at'])
                result['notified'].append(a.owner.email)
            else:
                result['failed'].append(f'{a.owner.email}: {detail}')

    # Last week's unfinished priorities become this week's, marked as carried
    # so the report can show what keeps slipping instead of losing it.
    previous = WeeklyFocus.objects.filter(
        week_start=week_start - timedelta(days=7), is_done=False)
    for f in previous:
        if WeeklyFocus.objects.filter(week_start=week_start,
                                      title=f.title).exists():
            continue
        WeeklyFocus.objects.create(
            week_start=week_start, title=f.title,
            project_name=f.project_name, client=f.client, owner=f.owner,
            order=f.order, carried_over=True,
            note=f'Carried over from week of {f.week_start:%d %b}')
        result['carried_over'] += 1

    logger.info('[mgmt] chase for %s: %s reported, %s notified, %s carried',
                week_start, result['reported'], len(result['notified']),
                result['carried_over'])
    return result


def _notify_owner(action):
    """Tell one person what is theirs, and ask them to confirm the date."""
    from .views import _graph_send_simple

    due = (f'due {action.due_date:%d %b %Y}' if action.due_date
           else 'no date set')
    blocks = [
        el.heading('An action is assigned to you', action.title),
        el.fact_row([
            ('Due', action.due_date.strftime('%d %b')
             if action.due_date else 'not set'),
            ('Project', action.project_name or '-'),
            ('Client', action.client or '-'),
            ('Raised by', _who(action.raised_by) or 'Management review'),
        ]),
    ]
    if action.detail:
        blocks.append(el.para(action.detail))
    blocks.append(el.para(
        'Please confirm you have seen this and that the date is achievable. '
        'If it is not, say so now rather than at the next review.'))
    blocks.append(el.button('Open the management report',
                            f'{_base_url()}/management'))

    subject = f'Action assigned: {action.title[:60]}'
    html = el.render(subject, blocks,
                     preheader=f'{action.title[:80]} - {due}',
                     footer_note='From the weekly management report.')
    text = (f'An action is assigned to you\n\n{action.title}\n{due}\n\n'
            f'{action.detail}\n\n{_base_url()}/management\n')
    return _graph_send_simple(action.owner.email, subject,
                              body_html=html, body_text=text)


def send(week_start=None, recipients=(), user=None, summary=''):
    """Email the report to management and mark the week sent."""
    from .views import _graph_send_simple

    week_start = week_start or week_start_for()
    row = save(week_start=week_start, user=user, summary=summary, publish=True)
    data = row.payload
    h = data['headline']

    title = f'Management report - week of {week_start:%d %b %Y}'
    blocks = [
        el.heading(title,
                   f'{h["clients"]} client(s), {h["active_projects"]} active '
                   f'project(s), {h["open_tasks"]} open task(s)'),
    ]
    if summary:
        blocks.append(el.para(summary))
    blocks.append(el.fact_row([
        ('Completed', str(h['completed_this_week'])),
        ('Overdue', str(h['overdue'])),
        ('Blocked', str(h['blocked'])),
        ('Tickets', str(h['open_tickets'])),
        ('Risks', str(h['open_risks'])),
        ('Escalations', str(h['escalations'])),
    ]))

    # Escalations first: it is the section management is reading for.
    if data['escalations']:
        blocks.append(el.heading('Requires a decision or escalation'))
        blocks.append(el.bullet_list(
            [f'{e["title"]} - {e["why"]}'
             + (f' ({e["owner"]})' if e['owner'] else '')
             for e in data['escalations'][:12]]))

    prios = data['capacity_and_priorities']['priorities']
    if prios:
        blocks.append(el.heading('Priorities this week'))
        blocks.append(el.bullet_list(
            [p['title'] + (f' - {p["owner"]}' if p['owner'] else '')
             + (' (carried over)' if p['carried_over'] else '')
             for p in prios]))

    actions = data['people_and_actions']['actions']
    if actions:
        blocks.append(el.heading('Open actions'))
        blocks.append(el.bullet_list(
            [f'{a["title"]} - {a["owner"] or "unassigned"}'
             + (f', due {a["due"]}' if a['due'] else '')
             + (' [OVERDUE]' if a['is_overdue'] else '')
             for a in actions[:15]]))

    blocks.append(el.button('Open the full report', f'{_base_url()}/management'))

    html = el.render(title, blocks,
                     preheader=f'{h["escalations"]} item(s) need a decision; '
                               f'{h["overdue"]} overdue.',
                     footer_note='Prepared from the Sentinel project tracker.')
    text = (f'{title}\n\nClients {h["clients"]} | Active projects '
            f'{h["active_projects"]} | Open tasks {h["open_tasks"]}\n'
            f'Overdue {h["overdue"]} | Blocked {h["blocked"]} | '
            f'Escalations {h["escalations"]}\n\n{_base_url()}/management\n')

    to = [a.strip() for a in recipients if a and a.strip()]
    banner = el.banner_attachment()
    sent, errors = [], []
    for address in to:
        ok, msg = _graph_send_simple(address, title, body_html=html,
                                     body_text=text,
                                     attachments=[banner] if banner else [])
        (sent if ok else errors).append(address if ok else f'{address}: {msg}')

    row.recipients = ', '.join(to)
    row.status = 'sent' if sent else 'published'
    row.sent_at = timezone.now() if sent else None
    row.save(update_fields=['recipients', 'status', 'sent_at', 'updated_at'])
    logger.info('[mgmt] report for %s sent to %s (%s errors)',
                week_start, sent, len(errors))
    return row, {'sent': sent, 'errors': errors}
