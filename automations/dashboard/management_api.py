"""The management report API: read the week, and act on it.

Reading is one endpoint returning all eight sections. The write endpoints are
the ones that matter, because the brief asked for a report that drives
execution: raising an action, acknowledging one, recording a decision, setting
the week's priorities, and logging tickets and risks.
"""
import json
import logging
from datetime import timedelta

from django.contrib.auth.models import User
from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import management_report as mr
from . import up_report
from .models import (ClientWeekNote, CompanyFocus, ManagementAction,
                     ManagementReport, RiskItem, ServiceAgreement,
                     StaffFocus, SupportTicket, WeeklyFocus)
from .views import _require_module

logger = logging.getLogger(__name__)

# Managers read this; it is not a per-project view. Gated on the tracker module
# for now so existing access grants apply without a new permission to hand out.
MODULE = 'tasks'


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _week(request):
    raw = request.GET.get('week') or ''
    parsed = parse_date(raw) if raw else None
    return mr.week_start_for(parsed) if parsed else mr.week_start_for()


@require_http_methods(["GET"])
def api_management_report(request):
    """The whole week. Live figures, unless a stored week is asked for."""
    err = _require_module(request, MODULE)
    if err:
        return err
    week = _week(request)

    # A past week comes from what was published, not from recomputing it -
    # otherwise last week's report silently changes after the meeting.
    stored = ManagementReport.objects.filter(week_start=week).first()
    live = week == mr.week_start_for()
    data = mr.build(week) if live or stored is None else stored.payload

    return JsonResponse({
        **data,
        'is_live': live,
        'stored': None if stored is None else {
            'status': stored.status, 'summary': stored.summary,
            'recipients': stored.recipients,
            'sent_at': stored.sent_at.isoformat() if stored.sent_at else None,
            'prepared_by': mr._who(stored.prepared_by),
        },
        'weeks_available': [w.isoformat() for w in
                            ManagementReport.objects.values_list(
                                'week_start', flat=True).order_by('-week_start')[:12]],
        'people': [{'id': u.id, 'name': u.get_full_name() or u.username}
                   for u in User.objects.filter(is_active=True).order_by(
                       'first_name', 'username')],
        'choices': {
            'action_status': [{'value': v, 'label': l}
                              for v, l in ManagementAction.STATUS_CHOICES],
            'risk_kind': [{'value': v, 'label': l} for v, l in RiskItem.KINDS],
            'risk_severity': [{'value': v, 'label': l} for v, l in RiskItem.SEVERITY],
            'risk_likelihood': [{'value': v, 'label': l}
                                for v, l in RiskItem.LIKELIHOOD],
            'risk_status': [{'value': v, 'label': l}
                            for v, l in RiskItem.STATUS_CHOICES],
            'ticket_status': [{'value': v, 'label': l}
                              for v, l in SupportTicket.STATUS_CHOICES],
            'ticket_priority': [{'value': v, 'label': l}
                                for v, l in SupportTicket.PRIORITY_CHOICES],
            'ticket_source': [{'value': v, 'label': l} for v, l in SupportTicket.SOURCES],
            'sla_tier': [{'value': v, 'label': l} for v, l in ServiceAgreement.TIERS],
        },
    })


@require_http_methods(["GET"])
def api_up_report(request):
    """The report in the shape of the V3 template management already reads."""
    err = _require_module(request, MODULE)
    if err:
        return err
    week = _week(request)
    return JsonResponse({
        **up_report.build(week),
        'weeks_available': [w.isoformat() for w in
                            ManagementReport.objects.values_list(
                                'week_start', flat=True).order_by('-week_start')[:12]],
        'is_current_week': week == mr.week_start_for(),
    })


@require_http_methods(["GET"])
def api_up_dashboard(request):
    """The same figures, shaped for charts rather than for the document."""
    err = _require_module(request, MODULE)
    if err:
        return err
    week = _week(request)
    return JsonResponse({
        **up_report.dashboard(week),
        'weeks_available': [w.isoformat() for w in
                            ManagementReport.objects.values_list(
                                'week_start', flat=True).order_by('-week_start')[:12]],
        'is_current_week': week == mr.week_start_for(),
    })


@require_http_methods(["GET"])
def api_up_report_pdf(request):
    """The report as the V3 document, for sending upstairs."""
    err = _require_module(request, MODULE)
    if err:
        return err
    from django.http import HttpResponse

    from . import up_report_pdf

    week = _week(request)
    data = up_report_pdf.render(week)
    resp = HttpResponse(data, content_type='application/pdf')
    name = up_report_pdf.filename(week)
    # inline so it previews in the browser; the browser's own save button
    # keeps the filename.
    disposition = 'attachment' if request.GET.get('download') else 'inline'
    resp['Content-Disposition'] = f'{disposition}; filename="{name}"'
    resp['Content-Length'] = str(len(data))
    return resp


@csrf_exempt
@require_http_methods(["POST"])
def api_up_report_email(request):
    """Email the PDF to management and record that it went."""
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    to = data.get('recipients') or []
    if isinstance(to, str):
        to = [a.strip() for a in to.split(',')]
    to = [a for a in to if a and a.strip()]
    if not to:
        return JsonResponse({'detail': 'At least one recipient is required.'},
                            status=400)
    from . import up_report_send
    row, outcome = up_report_send.send(
        week_start=_week(request), recipients=to,
        user=request.user if request.user.is_authenticated else None,
        summary=(data.get('summary') or '').strip()[:4000])
    return JsonResponse({'ok': bool(outcome['sent']), 'status': row.status,
                         **outcome})


@csrf_exempt
@require_http_methods(["POST"])
def api_client_note_save(request):
    """The typed half of a client card: sprint, comments, next week."""
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    client = (data.get('client') or '').strip()
    if not client:
        return JsonResponse({'detail': 'A client is required.'}, status=400)
    note, _made = ClientWeekNote.objects.get_or_create(
        week_start=_week(request), client=client[:200])
    for f, cap in (('sprint', 80), ('comments', 4000), ('next_week_note', 4000)):
        if f in data:
            setattr(note, f, (data.get(f) or '').strip()[:cap])
    for f in ('project_due_date', 'last_report_update', 'next_week_due'):
        if f in data:
            setattr(note, f, parse_date(data[f]) if data.get(f) else None)
    if 'next_week_owner' in data:
        note.next_week_owner_id = data['next_week_owner'] or None
    note.save()
    return JsonResponse({'ok': True, 'id': note.id})


@csrf_exempt
@require_http_methods(["POST"])
def api_focus_matrix_save(request):
    """A cell of the staff focus matrix, or a company focus row."""
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    week = _week(request)
    kind = data.get('kind')

    if kind == 'staff':
        person = data.get('person')
        bucket = (data.get('bucket') or '').strip()
        if not person or not bucket:
            return JsonResponse({'detail': 'person and bucket are required.'},
                                status=400)
        try:
            pct = round(float(data.get('planned_pct') or 0), 1)
        except (TypeError, ValueError):
            return JsonResponse({'detail': 'planned_pct must be a number.'},
                                status=400)
        row, _made = StaffFocus.objects.update_or_create(
            week_start=week, person_id=person, bucket=bucket[:200],
            defaults={'planned_pct': pct})
        return JsonResponse({'ok': True, 'id': row.id})

    if kind == 'company':
        bucket = (data.get('bucket') or '').strip()
        if not bucket:
            return JsonResponse({'detail': 'bucket is required.'}, status=400)
        defaults = {}
        for f in ('split_goal_pct', 'support_pct'):
            if f in data:
                try:
                    defaults[f] = round(float(data.get(f) or 0), 1)
                except (TypeError, ValueError):
                    return JsonResponse({'detail': f'{f} must be a number.'},
                                        status=400)
        if 'note' in data:
            defaults['note'] = (data.get('note') or '').strip()[:300]
        if 'due_date' in data:
            defaults['due_date'] = (parse_date(data['due_date'])
                                    if data.get('due_date') else None)
        row, _made = CompanyFocus.objects.update_or_create(
            week_start=week, bucket=bucket[:200], defaults=defaults)
        return JsonResponse({'ok': True, 'id': row.id})

    return JsonResponse({'detail': 'kind must be "staff" or "company".'},
                        status=400)


@csrf_exempt
@require_http_methods(["POST"])
def api_report_header_save(request):
    """The header block and the morale line - the judgements on the report."""
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    week = _week(request)
    row, _made = ManagementReport.objects.get_or_create(week_start=week)
    for f, cap in (('summary', 4000), ('morale_note', 300),
                   ('issue_number', 20), ('report_version', 10),
                   ('developed_by', 120)):
        if f in data:
            setattr(row, f, (data.get(f) or '').strip()[:cap])
    if 'staff_morale' in data:
        valid = dict(ManagementReport.MORALE_CHOICES)
        if data['staff_morale'] and data['staff_morale'] not in valid:
            return JsonResponse({'detail': 'Unknown morale value.'}, status=400)
        row.staff_morale = data['staff_morale'] or ''
    row.save()
    return JsonResponse({'ok': True})


@csrf_exempt
@require_http_methods(["POST"])
def api_management_save(request):
    """Store this week's figures, with the summary management should read first."""
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    row = mr.save(week_start=_week(request),
                  user=request.user if request.user.is_authenticated else None,
                  summary=(data.get('summary') or '').strip()[:4000],
                  publish=bool(data.get('publish')))
    return JsonResponse({'ok': True, 'week_start': row.week_start.isoformat(),
                         'status': row.status})


@csrf_exempt
@require_http_methods(["POST"])
def api_management_chase(request):
    """Notify owners, count the week, carry unfinished priorities forward."""
    err = _require_module(request, MODULE)
    if err:
        return err
    notify = bool(_body(request).get('notify', True))
    return JsonResponse({'ok': True, **mr.chase(week_start=_week(request),
                                                notify=notify)})


@csrf_exempt
@require_http_methods(["POST"])
def api_management_send(request):
    """Email the report to management."""
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    to = data.get('recipients') or []
    if isinstance(to, str):
        to = [a.strip() for a in to.split(',')]
    if not [a for a in to if a and a.strip()]:
        return JsonResponse({'detail': 'At least one recipient is required.'},
                            status=400)
    row, outcome = mr.send(
        week_start=_week(request), recipients=to,
        user=request.user if request.user.is_authenticated else None,
        summary=(data.get('summary') or '').strip()[:4000])
    return JsonResponse({'ok': bool(outcome['sent']), 'status': row.status,
                         **outcome})


# ══════════════════════════════════════════════════════════════════════════════
# The things a manager adds during the review
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_http_methods(["POST"])
def api_action_save(request):
    """Raise an action, or move one along.

    `id` present means update. Setting the status to done stamps the completion
    time, which is what lets the next report say the item was closed out rather
    than just disappeared.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    user = request.user if request.user.is_authenticated else None

    if data.get('id'):
        a = ManagementAction.objects.filter(pk=data['id']).first()
        if a is None:
            return JsonResponse({'detail': 'Action not found.'}, status=404)
    else:
        title = (data.get('title') or '').strip()
        if not title:
            return JsonResponse({'detail': 'An action needs a title.'}, status=400)
        a = ManagementAction(title=title[:255], raised_by=user,
                             week_start=_week(request))

    for f, cap in (('title', 255), ('detail', 4000), ('project_name', 100),
                   ('client', 200), ('decision', 4000), ('devops_url', 500)):
        if f in data:
            setattr(a, f, (data.get(f) or '').strip()[:cap])

    if 'owner' in data:
        a.owner_id = data['owner'] or None
        # A new owner has not been told yet, so the chase can pick it up again.
        a.notified_at = None
    if 'due_date' in data:
        a.due_date = parse_date(data['due_date']) if data.get('due_date') else None
    if 'needs_decision' in data:
        a.needs_decision = bool(data['needs_decision'])
    if 'status' in data:
        if data['status'] not in dict(ManagementAction.STATUS_CHOICES):
            return JsonResponse({'detail': 'Unknown status.'}, status=400)
        a.status = data['status']
        if a.status == 'acknowledged' and not a.acknowledged_at:
            a.acknowledged_at = timezone.now()
        if a.status == 'done' and not a.completed_at:
            a.completed_at = timezone.now()
        if a.status not in ('done', 'cancelled'):
            a.completed_at = None
    if data.get('decision') and not a.decided_at:
        a.decided_at = timezone.now()

    a.save()
    return JsonResponse({'ok': True, 'id': a.id, 'status': a.status})


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_action_delete(request, pk):
    err = _require_module(request, MODULE)
    if err:
        return err
    n, _ = ManagementAction.objects.filter(pk=pk).delete()
    return JsonResponse({'ok': bool(n)}, status=200 if n else 404)


@csrf_exempt
@require_http_methods(["POST"])
def api_risk_save(request):
    """Log a risk, a piece of technical debt or a dependency."""
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    if data.get('id'):
        r = RiskItem.objects.filter(pk=data['id']).first()
        if r is None:
            return JsonResponse({'detail': 'Not found.'}, status=404)
    else:
        title = (data.get('title') or '').strip()
        if not title:
            return JsonResponse({'detail': 'A title is required.'}, status=400)
        r = RiskItem(title=title[:255],
                     raised_by=request.user if request.user.is_authenticated else None)

    for f, cap in (('title', 255), ('detail', 4000), ('project_name', 100),
                   ('client', 200), ('impact', 4000), ('mitigation', 4000),
                   ('devops_url', 500)):
        if f in data:
            setattr(r, f, (data.get(f) or '').strip()[:cap])
    for f, choices in (('kind', RiskItem.KINDS), ('severity', RiskItem.SEVERITY),
                       ('likelihood', RiskItem.LIKELIHOOD),
                       ('status', RiskItem.STATUS_CHOICES)):
        if f in data:
            if data[f] not in dict(choices):
                return JsonResponse({'detail': f'Unknown {f}.'}, status=400)
            setattr(r, f, data[f])
    if 'owner' in data:
        r.owner_id = data['owner'] or None
    if 'review_date' in data:
        r.review_date = (parse_date(data['review_date'])
                         if data.get('review_date') else None)
    r.save()
    return JsonResponse({'ok': True, 'id': r.id, 'score': r.score})


@csrf_exempt
@require_http_methods(["POST"])
def api_ticket_save(request):
    """Log a support ticket, with its SLA clock set from the agreement."""
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    if data.get('id'):
        t = SupportTicket.objects.filter(pk=data['id']).first()
        if t is None:
            return JsonResponse({'detail': 'Not found.'}, status=404)
    else:
        subject = (data.get('subject') or '').strip()
        if not subject:
            return JsonResponse({'detail': 'A subject is required.'}, status=400)
        t = SupportTicket(subject=subject[:255], opened_at=timezone.now())

    for f, cap in (('reference', 40), ('client', 200), ('project_name', 100),
                   ('subject', 255), ('detail', 4000), ('devops_url', 500)):
        if f in data:
            setattr(t, f, (data.get(f) or '').strip()[:cap])
    for f, choices in (('status', SupportTicket.STATUS_CHOICES),
                       ('priority', SupportTicket.PRIORITY_CHOICES),
                       ('source', SupportTicket.SOURCES)):
        if f in data:
            if data[f] not in dict(choices):
                return JsonResponse({'detail': f'Unknown {f}.'}, status=400)
            setattr(t, f, data[f])
    if 'owner' in data:
        t.owner_id = data['owner'] or None

    if t.status in ('resolved', 'closed') and not t.resolved_at:
        t.resolved_at = timezone.now()
    if t.status not in ('resolved', 'closed'):
        t.resolved_at = None
    if t.status != 'open' and not t.first_response_at:
        # Anything past "open" means somebody has picked it up.
        t.first_response_at = timezone.now()

    # The SLA clock comes from the client's agreement, so a breach is a fact
    # rather than a judgement made later.
    if not t.response_due_at or not t.resolution_due_at:
        agreement = ServiceAgreement.objects.filter(
            client=t.client, is_active=True).order_by('-project_name').first()
        if agreement:
            if agreement.response_hours and not t.response_due_at:
                t.response_due_at = t.opened_at + timedelta(
                    hours=agreement.response_hours)
            if agreement.resolution_hours and not t.resolution_due_at:
                t.resolution_due_at = t.opened_at + timedelta(
                    hours=agreement.resolution_hours)
    t.save()
    return JsonResponse({'ok': True, 'id': t.id,
                         'response_due': t.response_due_at.isoformat()
                         if t.response_due_at else None})


@csrf_exempt
@require_http_methods(["POST"])
def api_focus_save(request):
    """Set, tick off or clear this week's priorities."""
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    week = _week(request)

    if data.get('id'):
        f = WeeklyFocus.objects.filter(pk=data['id']).first()
        if f is None:
            return JsonResponse({'detail': 'Not found.'}, status=404)
        if 'is_done' in data:
            f.is_done = bool(data['is_done'])
        for field, cap in (('title', 255), ('note', 300),
                           ('project_name', 100), ('client', 200)):
            if field in data:
                setattr(f, field, (data.get(field) or '').strip()[:cap])
        if 'owner' in data:
            f.owner_id = data['owner'] or None
        f.save()
        return JsonResponse({'ok': True, 'id': f.id, 'is_done': f.is_done})

    title = (data.get('title') or '').strip()
    if not title:
        return JsonResponse({'detail': 'A priority needs a title.'}, status=400)
    last = WeeklyFocus.objects.filter(week_start=week).order_by('-order').first()
    f = WeeklyFocus.objects.create(
        week_start=week, title=title[:255],
        project_name=(data.get('project_name') or '').strip()[:100],
        client=(data.get('client') or '').strip()[:200],
        owner_id=data.get('owner') or None,
        note=(data.get('note') or '').strip()[:300],
        order=(last.order + 1) if last else 0)
    return JsonResponse({'ok': True, 'id': f.id}, status=201)


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_focus_delete(request, pk):
    err = _require_module(request, MODULE)
    if err:
        return err
    n, _ = WeeklyFocus.objects.filter(pk=pk).delete()
    return JsonResponse({'ok': bool(n)}, status=200 if n else 404)


@csrf_exempt
@require_http_methods(["POST"])
def api_agreement_save(request):
    """Record what we have promised a client."""
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    if data.get('id'):
        a = ServiceAgreement.objects.filter(pk=data['id']).first()
        if a is None:
            return JsonResponse({'detail': 'Not found.'}, status=404)
    else:
        client = (data.get('client') or '').strip()
        if not client:
            return JsonResponse({'detail': 'A client is required.'}, status=400)
        a = ServiceAgreement(client=client[:200])

    for f, cap in (('client', 200), ('project_name', 100),
                   ('support_window', 120), ('hosting_provider', 120),
                   ('hosting_notes', 4000), ('environment_url', 500),
                   ('backup_schedule', 120), ('notes', 4000)):
        if f in data:
            setattr(a, f, (data.get(f) or '').strip()[:cap])
    if 'tier' in data:
        if data['tier'] not in dict(ServiceAgreement.TIERS):
            return JsonResponse({'detail': 'Unknown tier.'}, status=400)
        a.tier = data['tier']
    for f in ('response_hours', 'resolution_hours'):
        if f in data:
            raw = data.get(f)
            try:
                setattr(a, f, None if raw in (None, '') else int(raw))
            except (TypeError, ValueError):
                return JsonResponse({'detail': f'{f} must be a whole number of hours.'},
                                    status=400)
    if 'monthly_fee' in data:
        raw = data.get('monthly_fee')
        try:
            a.monthly_fee = None if raw in (None, '') else round(float(raw), 2)
        except (TypeError, ValueError):
            return JsonResponse({'detail': 'monthly_fee must be a number.'},
                                status=400)
    if 'renewal_date' in data:
        a.renewal_date = (parse_date(data['renewal_date'])
                          if data.get('renewal_date') else None)
    if 'owner' in data:
        a.owner_id = data['owner'] or None
    if 'is_active' in data:
        a.is_active = bool(data['is_active'])
    a.save()
    return JsonResponse({'ok': True, 'id': a.id})
