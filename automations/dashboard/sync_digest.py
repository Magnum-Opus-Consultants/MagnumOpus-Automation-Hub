"""Run all report syncs and email ONE status digest of every report.

Reads sync_health.json (which every sync stamps with its last-check time, status,
row count and message) and emails a single table so you can see, at a glance,
that every report actually ran and synced — and spot anything stale or errored.

Sends via Graph (Office 365) only — AWS SES is never used. Goes to RECIPIENTS.

Run from the automations/ directory:
    python dashboard/sync_digest.py            # run all syncs, then email digest
    python dashboard/sync_digest.py --digest   # email current status only (no re-sync)
"""
import os
import sys
import json
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'automations.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
import django  # noqa: E402
django.setup()

from django.conf import settings  # noqa: E402

RECIPIENTS = ['Ethan.Sevenster@moc-pty.com']
TZ = ZoneInfo('Africa/Johannesburg')

# Health keys to leave out of the digest (dead / unused paths, and the
# standalone reconciliation we no longer send separately).
EXCLUDE_KEYS = {'onedrive_token', 'updown_reconcile'}

# Station email syncs + the special reports that report into sync_health.
STATION_KEYS = ['ppg', 'ccc', 'ccd', 'hnl', 'jfk', 'lcl', 'hou', 'ics',
                'ord', 'imp', 'lax', 'fax', 'atl', 'dfw', 'con', 'dor']
SPECIAL_FNS = ['_run_turnover_email_sync', '_run_wip_email_sync',
               '_run_import_ops_email_sync', '_run_creditor_email_sync',
               '_run_condor_dor_email_sync']

# Friendlier labels for known health keys (anything else falls back to UPPER()).
LABELS = {
    'updown_trader': 'Up-Down Trader sync',
    'updown_reconcile': 'Up-Down Trader reconciliation',
    'bravo_tran': 'Bravo Trans',
    'turnover': 'Turnover', 'wip': 'WIP', 'import_ops': 'Import Ops',
    'creditor': 'Creditor', 'condor_dor': 'Condor / DOR',
}


def run_all_syncs():
    """Run every email-driven report sync. Errors are caught per report so one
    failure never stops the rest."""
    from dashboard import scheduler as sch
    for k in STATION_KEYS:
        try:
            sch._run_station_email_sync(k)
            print('synced', k)
        except Exception as e:
            print('ERR', k, e)
    for name in SPECIAL_FNS:
        try:
            getattr(sch, name)()
            print('synced', name)
        except Exception as e:
            print('ERR', name, e)
    try:
        sch.run_bravo_tran_sync_job()
        print('synced bravo_tran')
    except Exception as e:
        print('ERR bravo_tran', e)


def _read_health():
    try:
        with open(settings.SYNC_HEALTH_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _age_seconds(last_check):
    if not last_check:
        return None
    try:
        dt = datetime.fromisoformat(last_check)
    except Exception:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=TZ)
    return (datetime.now(TZ) - dt).total_seconds()


def _fmt_age(secs):
    if secs is None:
        return 'never'
    d, rem = divmod(int(secs), 86400)
    h, rem = divmod(rem, 3600)
    m, _ = divmod(rem, 60)
    if d:
        return f'{d}d {h}h ago'
    if h:
        return f'{h}h {m}m ago'
    return f'{m}m ago'


def _fmt_when(last_check):
    if not last_check:
        return '—'
    try:
        return datetime.fromisoformat(last_check).strftime('%Y-%m-%d %H:%M')
    except Exception:
        return last_check[:16]


def _build_html(health):
    rows = []
    for key, info in health.items():
        if key in EXCLUDE_KEYS:
            continue
        secs = _age_seconds(info.get('last_check'))
        rows.append({
            'key': key,
            'label': LABELS.get(key, key.upper()),
            'status': info.get('status', 'unknown'),
            'when': _fmt_when(info.get('last_check')),
            'age': _fmt_age(secs),
            'secs': secs if secs is not None else 1e18,
            'rows': info.get('records', 0),
            'msg': info.get('message', ''),
        })
    # errors first, then oldest first
    rows.sort(key=lambda r: (r['status'] != 'error', -r['secs']))

    errors = sum(1 for r in rows if r['status'] == 'error')
    badge = (f'<span style="color:#c0392b;font-weight:bold;">&#10006; {errors} error(s)</span>'
             if errors else
             '<span style="color:#1e7d32;font-weight:bold;">&#10004; all healthy</span>')

    out = [f"""
    <div style="font-family:Segoe UI,Arial,sans-serif;color:#1f3864;">
      <h2 style="margin:0 0 4px;">Report Sync Digest</h2>
      <p style="margin:0 0 12px;">{badge} &nbsp;·&nbsp; {len(rows)} reports
         &nbsp;·&nbsp; {datetime.now(TZ).strftime('%Y-%m-%d %H:%M')}</p>
      <table style="border-collapse:collapse;font-size:13px;">
        <tr style="background:#1f3864;color:#fff;">
          <th style="padding:6px 10px;text-align:left;">Report</th>
          <th style="padding:6px 10px;">Status</th>
          <th style="padding:6px 10px;text-align:left;">Last sync</th>
          <th style="padding:6px 10px;text-align:left;">Age</th>
          <th style="padding:6px 10px;text-align:right;">Rows</th>
          <th style="padding:6px 10px;text-align:left;">Message</th>
        </tr>"""]
    for r in rows:
        if r['status'] == 'error':
            sc = '<span style="color:#c0392b;font-weight:bold;">ERROR</span>'
            tint = 'background:#fde8e8;'
        elif r['status'] == 'success':
            sc = '<span style="color:#1e7d32;">OK</span>'
            tint = ''
        else:
            sc = r['status']
            tint = ''
        out.append(
            f'<tr style="border-bottom:1px solid #e0e0e0;{tint}">'
            f'<td style="padding:6px 10px;font-weight:bold;">{r["label"]}</td>'
            f'<td style="padding:6px 10px;text-align:center;">{sc}</td>'
            f'<td style="padding:6px 10px;">{r["when"]}</td>'
            f'<td style="padding:6px 10px;">{r["age"]}</td>'
            f'<td style="padding:6px 10px;text-align:right;">{r["rows"]:,}</td>'
            f'<td style="padding:6px 10px;color:#555;">{r["msg"]}</td>'
            '</tr>')
    out.append('</table></div>')
    return ''.join(out), errors


def _build_text(health):
    lines = ['Report Sync Digest', datetime.now(TZ).strftime('%Y-%m-%d %H:%M'), '']
    for key, info in sorted(health.items()):
        if key in EXCLUDE_KEYS:
            continue
        secs = _age_seconds(info.get('last_check'))
        lines.append(f"{LABELS.get(key, key.upper())}: {info.get('status','?').upper()} | "
                     f"{_fmt_when(info.get('last_check'))} ({_fmt_age(secs)}) | "
                     f"{info.get('records',0)} rows | {info.get('message','')}")
    return '\n'.join(lines)


def _digest_rows(health):
    rows = []
    for key, info in health.items():
        if key in EXCLUDE_KEYS:
            continue
        secs = _age_seconds(info.get('last_check'))
        rows.append({
            'label': LABELS.get(key, key.upper()),
            'status': info.get('status', 'unknown'),
            'when': _fmt_when(info.get('last_check')),
            'age': _fmt_age(secs),
            'secs': secs if secs is not None else 1e18,
            'rows': info.get('records', 0),
            'msg': info.get('message', ''),
        })
    rows.sort(key=lambda r: (r['status'] != 'error', -r['secs']))
    return rows


def _summary_html(rows, errors):
    if errors:
        badge = f'<span style="color:#c0392b;font-weight:bold;">&#10006; {errors} error(s)</span>'
    else:
        badge = '<span style="color:#1e7d32;font-weight:bold;">&#10004; All reports healthy</span>'
    when = datetime.now(TZ).strftime('%Y-%m-%d %H:%M')
    return f'''
    <div style="font-family:Segoe UI,Arial,sans-serif;color:#1f3864;font-size:14px;">
      <h2 style="margin:0 0 6px;">Report Sync Digest</h2>
      <p style="margin:0 0 14px;">{badge} &nbsp;&middot;&nbsp; {len(rows)} reports
         &nbsp;&middot;&nbsp; {when}</p>
      <p style="margin:0;">The full status of every report is in the attached PDF
         (<b>report_sync_digest.pdf</b>).</p>
    </div>'''


def _summary_text(rows, errors):
    status = f'{errors} error(s)' if errors else 'All reports healthy'
    when = datetime.now(TZ).strftime('%Y-%m-%d %H:%M')
    return (f'Report Sync Digest\n{status} - {len(rows)} reports - {when}\n'
            'Full status in the attached PDF (report_sync_digest.pdf).')


def build_digest_pdf(rows, errors):
    """One PDF table of EVERY report's status. Returns (bytes, filename) or (None, None)."""
    try:
        from fpdf import FPDF
    except ImportError:
        return None, None
    when = datetime.now(TZ).strftime('%Y-%m-%d %H:%M')
    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, 'Report Sync Digest', ln=1)
    pdf.set_font('Helvetica', '', 11)
    status = ('ALL HEALTHY' if errors == 0 else f'{errors} ERROR(S)')
    pdf.cell(0, 8, f'{status}  -  {len(rows)} reports  -  {when}', ln=1)
    pdf.ln(2)

    w = [58, 20, 34, 24, 22, 118]
    pdf.set_font('Helvetica', 'B', 9)
    for wi, h in zip(w, ['Report', 'Status', 'Last sync', 'Age', 'Rows', 'Message']):
        pdf.cell(wi, 8, h, border=1)
    pdf.ln()
    pdf.set_font('Helvetica', '', 9)
    for r in rows:
        st = 'ERROR' if r['status'] == 'error' else 'OK'
        pdf.cell(w[0], 7, str(r['label'])[:36], border=1)
        pdf.cell(w[1], 7, st, border=1, align='C')
        pdf.cell(w[2], 7, r['when'], border=1)
        pdf.cell(w[3], 7, r['age'], border=1)
        pdf.cell(w[4], 7, f"{r['rows']:,}", border=1, align='R')
        pdf.cell(w[5], 7, str(r['msg'])[:72], border=1)
        pdf.ln()
    raw = pdf.output(dest='S')
    data = raw.encode('latin1') if isinstance(raw, str) else bytes(raw)
    return data, 'report_sync_digest.pdf'


def send_sync_digest(recipients=None):
    """Email a short summary with the full report-status table attached as a PDF."""
    health = _read_health()
    rows = _digest_rows(health)
    errors = sum(1 for r in rows if r['status'] == 'error')
    subject = (f'Report Sync Digest: {errors} error(s)' if errors
               else 'Report Sync Digest: all healthy')
    html = _summary_html(rows, errors)
    text = _summary_text(rows, errors)
    print(text)

    attachments = None
    try:
        import base64
        pdf_bytes, pdf_name = build_digest_pdf(rows, errors)
        if pdf_bytes:
            attachments = [{'name': pdf_name, 'contentType': 'application/pdf',
                            'contentBytes': base64.b64encode(pdf_bytes).decode()}]
        else:
            print('digest PDF skipped (fpdf not installed)')
    except Exception as e:
        print('digest PDF skipped:', e)

    from dashboard.views import _graph_send_simple   # Graph only — no AWS SES
    sent = False
    for to in (recipients or RECIPIENTS):
        ok, msg = _graph_send_simple(to, subject, body_html=html, body_text=text,
                                     attachments=attachments)
        print(f'  email -> {to}: {"sent" if ok else "FAILED " + str(msg)}')
        sent = sent or ok
    return sent


def run_all_and_email(recipients=None):
    """Run every report sync, then email the digest."""
    run_all_syncs()
    return send_sync_digest(recipients)


if __name__ == '__main__':
    if '--digest' in sys.argv:
        send_sync_digest()
    else:
        run_all_and_email()
