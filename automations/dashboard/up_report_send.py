"""Send the Up Management Report upstairs, with the PDF attached.

The email is a covering note, not the report: management asked for the document
they already read, so the PDF is the deliverable and the body exists to say
what changed and what needs a decision before they open it.

Runs weekly on its own. The brief asked for a reliable weekly view, and a
report that only appears when somebody remembers to produce it is not one.
"""
import logging
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from . import email_layout as el
from . import up_report, up_report_pdf
from .management_report import _who, week_start_for
from .models import ManagementReport

logger = logging.getLogger(__name__)


def _base_url():
    return getattr(settings, 'PLATFORM_BASE_URL', 'https://workspace.moc-pty.com')


def recipients_default():
    raw = getattr(settings, 'UP_REPORT_TO', '') or ''
    return [a.strip() for a in raw.split(',') if a.strip()]


def build_email(data, summary=''):
    """The covering note. Short on purpose - the detail is in the PDF."""
    header = data['header']
    ending = header['week_ending']
    cards = data['highlights']
    risks = data['risks']

    completed = sum(
        s.get('completed_this_week', 0)
        for c in cards for s in c['streams'].values())
    outstanding = sum(c['development']['outstanding'] for c in cards)
    open_tickets = sum(c['tickets']['open'] for c in cards)
    severe = [r for r in risks if r['severity'] in ('critical', 'high')]

    title = f'Up Management Report - week ending {ending}'
    blocks = [
        el.heading(title,
                   f'{len(cards)} client(s), {outstanding} item(s) outstanding'),
    ]
    if summary:
        blocks.append(el.para(summary))
    blocks.append(el.fact_row([
        ('Completed', str(completed)),
        ('Outstanding', str(outstanding)),
        ('Open tickets', str(open_tickets)),
        ('Risks', str(len(risks))),
        ('Morale', dict(ManagementReport.MORALE_CHOICES).get(
            header.get('staff_morale', ''), 'not recorded')),
    ]))

    # The two things a manager would want to see before opening an attachment.
    if severe:
        blocks.append(el.para('Risks needing attention:'))
        blocks.append(el.bullet_list(
            [f'{r["description"]} - {r["severity_display"]}'
             + (f', {r["owner"]}' if r['owner'] else '')
             + ('  (no mitigation recorded)' if not r['mitigation'] else '')
             for r in severe[:8]]))

    next_week = [r for r in data['next_week']['rows'] if r['note'] or r['items']]
    if next_week:
        blocks.append(el.para('Planned for next week:'))
        blocks.append(el.bullet_list(
            [f'{r["bucket"]}: {r["note"] or ", ".join(i["title"] for i in r["items"])}'
             for r in next_week[:8]]))

    blocks.append(el.para('The full report is attached as a PDF, in the usual '
                          'format.', muted=True, size=13))
    blocks.append(el.button('Open it on the platform', f'{_base_url()}/up-report'))

    html = el.render(title, blocks,
                     preheader=f'{outstanding} outstanding, {len(severe)} '
                               f'risk(s) needing attention.',
                     footer_note='Generated from the project tracker. '
                                 'Automated report syncs are excluded.')
    text = (f'{title}\n\n'
            + (f'{summary}\n\n' if summary else '')
            + f'Completed {completed} | Outstanding {outstanding} | '
              f'Open tickets {open_tickets} | Risks {len(risks)}\n\n'
              f'The full report is attached.\n{_base_url()}/up-report\n')
    return title, html, text


def send(week_start=None, recipients=(), user=None, summary='', save=True):
    """Generate the PDF, email it, and record the week as sent."""
    import base64

    from .views import _graph_send_simple

    week_start = week_start or week_start_for()
    data = up_report.build(week_start)
    pdf_bytes = up_report_pdf.render(week_start, data=data)
    title, html, text = build_email(data, summary=summary)

    to = [a.strip() for a in (recipients or recipients_default()) if a and a.strip()]
    if not to:
        raise ValueError('The report needs at least one recipient.')

    attachments = [{
        'name': up_report_pdf.filename(week_start),
        'contentType': 'application/pdf',
        'contentBytes': base64.b64encode(pdf_bytes).decode('ascii'),
    }]
    banner = el.banner_attachment()
    if banner:
        attachments.append(banner)

    sent, errors = [], []
    for address in to:
        ok, msg = _graph_send_simple(address, title, body_html=html,
                                     body_text=text, attachments=attachments)
        (sent if ok else errors).append(address if ok else f'{address}: {msg}')
        if not ok:
            logger.error('[up-report] to %s failed: %s', address, msg)

    row = None
    if save:
        row, _made = ManagementReport.objects.update_or_create(
            week_start=week_start,
            defaults={
                'title': title,
                'payload': data,
                'summary': summary or (row.summary if row else ''),
                'status': 'sent' if sent else 'published',
                'prepared_by': user,
                'recipients': ', '.join(to),
                'sent_at': timezone.now() if sent else None,
            })
    logger.info('[up-report] week ending %s: %s bytes to %s (%s errors)',
                data['header']['week_ending'], len(pdf_bytes), sent, len(errors))
    return row, {'sent': sent, 'errors': errors, 'pdf_bytes': len(pdf_bytes)}


def autosend_enabled():
    """Whether the weekly send is allowed to go out on its own.

    Off unless UP_REPORT_AUTOSEND is explicitly true. This report goes to
    upper management, so it does not start mailing anyone because a scheduler
    job happened to be registered - somebody has to turn it on deliberately.
    """
    return str(getattr(settings, 'UP_REPORT_AUTOSEND', '')).lower() in (
        '1', 'true', 'yes', 'on')


def weekly_job():
    """The scheduled run. Never raises: a failed send must not stop the rest.

    Reports on the week that has just finished rather than the current one, so
    the figures cover a complete week.

    Refuses to send unless both switches are set: the autosend flag and a
    recipient list. Two conditions rather than one because the cost of this
    going out before it should is a wrong report in a manager's inbox.
    """
    if not autosend_enabled():
        logger.info('[up-report] autosend is off; not sending')
        return {'skipped': 'autosend disabled'}
    to = recipients_default()
    if not to:
        logger.info('[up-report] no UP_REPORT_TO configured; not sending')
        return {'skipped': 'no recipients'}
    try:
        last_week = week_start_for() - timedelta(days=7)
        _row, outcome = send(week_start=last_week, recipients=to)
        return outcome
    except Exception:                                            # noqa: BLE001
        logger.exception('[up-report] the weekly send failed')
        return None
