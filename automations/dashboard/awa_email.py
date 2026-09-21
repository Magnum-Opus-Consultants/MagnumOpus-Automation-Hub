"""The AWA reports status email, in the platform's own shell.

The scripts used to build this by hand: an inline-styled table assembled with
string concatenation, sent through a separate Graph app with its own
credentials. It worked, but it looked nothing like anything else the business
sends, and it was a second email system to keep alive.

Same information, same plain-English errors, rendered through email_layout so
it arrives looking like the rest of the platform and sent down the path that is
already proven.
"""
import logging

from django.conf import settings
from django.utils import timezone

from . import email_layout as el
from .models import AwaReportState

logger = logging.getLogger(__name__)

GOOD = '#137333'
BAD = '#c5221f'
QUIET = '#5f6368'


def _fmt_rows(n):
    return '—' if n is None else f'{n:,}'


def _fmt_when(dt):
    if not dt:
        return 'never'
    return timezone.localtime(dt).strftime('%d %b %Y %H:%M')


def _table(runs):
    """The run, as a table. Built here rather than in email_layout because the
    shape is specific to this email: four columns, and a failed row carries its
    explanation underneath rather than in a column of its own."""
    states = {s.script: s for s in AwaReportState.objects.all()}
    head = (
        f'<tr style="background:{el.WASH}">'
        f'<th align="left" style="padding:9px 12px;border:1px solid {el.LINE};'
        f'font-family:{el.FONT};font-size:12px;color:{el.MUTED}">Report</th>'
        f'<th align="left" style="padding:9px 12px;border:1px solid {el.LINE};'
        f'font-family:{el.FONT};font-size:12px;color:{el.MUTED}">Status</th>'
        f'<th align="right" style="padding:9px 12px;border:1px solid {el.LINE};'
        f'font-family:{el.FONT};font-size:12px;color:{el.MUTED}">Rows</th>'
        f'<th align="left" style="padding:9px 12px;border:1px solid {el.LINE};'
        f'font-family:{el.FONT};font-size:12px;color:{el.MUTED}">'
        f'Last successful pull</th></tr>')

    rows = []
    for r in runs:
        state = states.get(r.script)
        last_rows = state.last_rows if state else None
        last_ok = state.last_success_at if state else None

        if r.outcome == 'skipped':
            status = f'<span style="color:{QUIET}">Not scheduled today</span>'
            shown = _fmt_rows(last_rows) + (' (last)' if last_rows is not None else '')
            bg, note = '#fafafa', ''
        elif r.outcome == 'ok':
            status = f'<span style="color:{GOOD}">&#10004; Updated</span>'
            shown = _fmt_rows(r.rows if r.rows is not None else last_rows)
            bg, note = '#ffffff', ''
        else:
            status = f'<span style="color:{BAD}">&#10008; Failed</span>'
            shown = _fmt_rows(last_rows) + (' (last good)' if last_rows is not None else '')
            bg = '#fdecea'
            note = (f'<br><span style="color:{BAD};font-size:12px">'
                    f'{el.esc(r.error)}</span>')

        rows.append(
            f'<tr style="background:{bg}">'
            f'<td style="padding:9px 12px;border:1px solid {el.LINE};'
            f'font-family:{el.FONT};font-size:13px;color:{el.INK}">'
            f'{el.esc(r.name)}{note}</td>'
            f'<td style="padding:9px 12px;border:1px solid {el.LINE};'
            f'font-family:{el.FONT};font-size:13px;white-space:nowrap">{status}</td>'
            f'<td align="right" style="padding:9px 12px;border:1px solid {el.LINE};'
            f'font-family:{el.FONT};font-size:13px;color:{el.INK}">{shown}</td>'
            f'<td style="padding:9px 12px;border:1px solid {el.LINE};'
            f'font-family:{el.FONT};font-size:12px;color:{el.MUTED};'
            f'white-space:nowrap">{_fmt_when(last_ok)}</td></tr>')

    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'width="100%" style="border-collapse:collapse;margin:0 0 18px">'
            f'{head}{"".join(rows)}</table>')


def _base_url():
    return getattr(settings, 'PLATFORM_BASE_URL', 'https://workspace.moc-pty.com')


def send_status(batch, runs):
    """Email the outcome of one batch to whoever watches these reports."""
    from .views import _graph_send_simple

    ok = [r for r in runs if r.outcome == 'ok']
    failed = [r for r in runs if r.outcome == 'failed']
    skipped = [r for r in runs if r.outcome == 'skipped']
    ran = len(ok) + len(failed)
    finished = timezone.localtime(timezone.now())

    overall = 'all good' if not failed else (
        f'{len(failed)} failed' if len(failed) > 1 else '1 failed')
    subject = (f'CargoWise reports - {overall} - '
               f'{finished.strftime("%d %b %Y %H:%M")}')

    blocks = [
        el.heading('CargoWise report run',
                   f'{len(ok)} of {ran} scheduled reports updated'
                   + (f', {len(skipped)} not scheduled today' if skipped else '')),
        el.fact_row([
            ('Finished', finished.strftime('%d %b %H:%M')),
            ('Updated', str(len(ok))),
            ('Failed', str(len(failed))),
            ('Rows pulled', f'{sum(r.rows or 0 for r in ok):,}'),
        ]),
        el.raw(_table(runs)),
    ]

    if failed:
        blocks.append(el.para(
            'The reports that failed still show their last good data on '
            'SharePoint. They are retried on the next run, and can be retried '
            'now from the platform.', muted=True, size=13))
        blocks.append(el.button('Open the reporting page', f'{_base_url()}/reporting'))
    else:
        blocks.append(el.para(
            'Every scheduled report pulled and uploaded successfully.',
            muted=True, size=13))
        blocks.append(el.raw(
            f'<p style="margin:0 0 4px;font-family:{el.FONT};font-size:12px">'
            f'{el.link(f"{_base_url()}/reporting", "See the detail on the platform")}'
            f'</p>'))

    html = el.render(
        subject, blocks,
        preheader=(f'{len(ok)} of {ran} reports updated'
                   + (f', {len(failed)} failed.' if failed else '.')),
        footer_note='Run by Sentinel. These reports pull from CargoWise and '
                    'upload to SharePoint.')

    text_rows = '\n'.join(
        f'{r.name}: {r.get_outcome_display()}'
        + (f' - {r.rows:,} rows' if r.rows is not None else '')
        + (f' - {r.error}' if r.error else '')
        for r in runs)
    text = (f'CargoWise report run - {finished:%d %b %Y %H:%M}\n'
            f'{len(ok)} of {ran} scheduled reports updated.\n\n{text_rows}\n')

    recipients = [a for a in (
        getattr(settings, 'AWA_NOTIFY_TO', '') or
        'Ethan.Sevenster@moc-pty.com').split(',') if a.strip()]
    banner = el.banner_attachment()

    ok_any, errors = False, []
    for to in recipients:
        sent, msg = _graph_send_simple(to.strip(), subject, body_html=html,
                                       body_text=text,
                                       attachments=[banner] if banner else [])
        if sent:
            ok_any = True
        else:
            errors.append(f'{to}: {msg}')
            logger.error('[awa] status email to %s failed: %s', to, msg)
    return ok_any, '; '.join(errors) if errors else 'sent'
