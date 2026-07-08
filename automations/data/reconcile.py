"""Reconcile the Up-Down Trader Excel source files against the database.

For every yearly shipment file in SharePoint this sums Total Recognized Income,
Job Profit and the distinct shipment count for the rows *recognised in that
year* (same IMM/null -> job_opened rule the report views use), then compares
those figures to what is actually in ``customer_spend_operational`` — the table
the report (``customer_spend_summary``) is built from. It then emails a
side-by-side report, including when the data was last synced, so you can see at
a glance whether the file and the DB still agree.

Run manually from the automations/ directory:
    python data/up_down_trader/reconcile.py

Or call ``run_reconciliation()`` from the scheduler / a Django shell.
"""
import os
import sys
import re
import json
import tempfile

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'automations.settings')
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
import django  # noqa: E402
django.setup()

import requests  # noqa: E402
import openpyxl  # noqa: E402
from urllib.parse import quote  # noqa: E402
from django.db import connection  # noqa: E402

# --- column indices within a parsed row (row[2:], 0-based) ---------------
# These mirror load_data.OPERATIONAL_COLS / _parse_operational_rows.
IDX_SHIPMENT = 0
IDX_JOB_OPENED = 54
IDX_INCOME = 57          # total_recognized_income
IDX_PROFIT = 61          # job_profit
IDX_RECOGNITION = 110    # job_revenue_recognition_date

# --- SharePoint location of the shipment files ---------------------------
SP_SITE = 'magnumopusconsultantspty352.sharepoint.com:/sites/DataPrime'
SP_FOLDER = 'Clients/ISCM/Up Down Trader Report/Shipment Data'

# --- who gets the reconciliation email (edit to taste) -------------------
RECIPIENTS = ['Ethan.Sevenster@moc-pty.com']

# Money is considered "matching" if it agrees to within this many dollars.
MONEY_TOL = 0.01

LAST_SYNC_FILE = os.path.join(
    os.path.dirname(__file__), '..', '..', 'updown_trader_last_sync.json')

# Recognition-date expression, identical to the report views.
DATE_EXPR = """CASE WHEN job_revenue_recognition_date = 'IMM'
                    OR job_revenue_recognition_date IS NULL
               THEN job_opened ELSE job_revenue_recognition_date END"""

OPERATIONAL_SHEETS = ('operational data', 'shipment profile')


# ----------------------------------------------------------------------- #
# small helpers
# ----------------------------------------------------------------------- #
def _num(v):
    try:
        return float(v) if v not in (None, '') else 0.0
    except (TypeError, ValueError):
        return 0.0


def _year_of(recognition, opened):
    """Recognition year for a row: use the recognition date unless it's IMM/blank,
    in which case fall back to job_opened (same rule as the SQL views)."""
    raw = recognition
    if not raw or str(raw).strip().upper() == 'IMM':
        raw = opened
    if not raw:
        return None
    s = str(raw).strip()
    m = re.match(r'(\d{4})-', s)            # ISO 'YYYY-MM-DD ...'
    if m:
        return int(m.group(1))
    m = re.search(r'(19|20)\d{2}', s)       # any 4-digit year, e.g. '15/01/2024'
    if m:
        return int(m.group(0))
    return None


def _file_year(name):
    m = re.search(r'(20\d{2})', name or '')
    return int(m.group(1)) if m else None


def _money(v):
    return '${:,.2f}'.format(v) if v is not None else '—'


# ----------------------------------------------------------------------- #
# SharePoint (Microsoft Graph)
# ----------------------------------------------------------------------- #
def _graph():
    from dashboard.views import _get_graph_token
    token = _get_graph_token()
    if not token:
        raise RuntimeError('No Graph token available')
    h = {'Authorization': f'Bearer {token}'}
    sid = requests.get(f'https://graph.microsoft.com/v1.0/sites/{SP_SITE}',
                       headers=h, timeout=30).json()['id']
    did = requests.get(f'https://graph.microsoft.com/v1.0/sites/{sid}/drive',
                       headers=h, timeout=30).json()['id']
    return h, did


def _list_files(h, did):
    """Top-level .xlsx files in the Shipment Data folder (Archive subfolder ignored)."""
    url = (f'https://graph.microsoft.com/v1.0/drives/{did}/root:/'
           f'{quote(SP_FOLDER)}:/children')
    items = requests.get(url, headers=h, timeout=60).json().get('value', [])
    return [it for it in items
            if it.get('name', '').lower().endswith('.xlsx') and 'file' in it]


def _download(h, did, item):
    url = f"https://graph.microsoft.com/v1.0/drives/{did}/items/{item['id']}/content"
    r = requests.get(url, headers=h, timeout=300)
    r.raise_for_status()
    fd, path = tempfile.mkstemp(suffix='.xlsx')
    with os.fdopen(fd, 'wb') as f:
        f.write(r.content)
    return path


# ----------------------------------------------------------------------- #
# totals
# ----------------------------------------------------------------------- #
def _file_totals(path):
    """{year: {'income', 'profit', 'ships'(set)}} for every row in this file."""
    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = None
    for name in wb.sheetnames:
        if name.strip().lower() in OPERATIONAL_SHEETS:
            ws = wb[name]
            break
    if ws is None:
        ws = wb[wb.sheetnames[0]]

    out = {}
    for row in ws.iter_rows(min_row=16, values_only=True):
        vals = list(row[2:])
        if not vals or not vals[0]:
            continue
        rec = vals[IDX_RECOGNITION] if len(vals) > IDX_RECOGNITION else None
        opened = vals[IDX_JOB_OPENED] if len(vals) > IDX_JOB_OPENED else None
        y = _year_of(rec, opened)
        if y is None:
            continue
        d = out.setdefault(y, {'income': 0.0, 'profit': 0.0, 'ships': set()})
        if len(vals) > IDX_INCOME:
            d['income'] += _num(vals[IDX_INCOME])
        if len(vals) > IDX_PROFIT:
            d['profit'] += _num(vals[IDX_PROFIT])
        sid = vals[IDX_SHIPMENT]
        if sid:
            d['ships'].add(str(sid).strip())
    wb.close()
    return out


def _db_totals():
    """{year: {'income', 'profit', 'ships'(int)}} from customer_spend_operational,
    bucketed by recognition year exactly like the report views."""
    sql = f"""
        SELECT EXTRACT(YEAR FROM CAST(NULLIF({DATE_EXPR}, '') AS DATE))::INT AS y,
               COALESCE(SUM(CAST(NULLIF(total_recognized_income, '') AS NUMERIC)), 0),
               COALESCE(SUM(CAST(NULLIF(job_profit, '') AS NUMERIC)), 0),
               COUNT(DISTINCT shipment_id)
        FROM customer_spend_operational
        WHERE NULLIF({DATE_EXPR}, '') IS NOT NULL
        GROUP BY y
    """
    out = {}
    with connection.cursor() as cur:
        cur.execute(sql)
        for y, inc, prof, cnt in cur.fetchall():
            if y is not None:
                out[int(y)] = {'income': float(inc), 'profit': float(prof),
                               'ships': int(cnt)}
    return out


def _last_sync():
    try:
        with open(LAST_SYNC_FILE) as fh:
            j = json.load(fh)
        return j.get('last_sync'), j.get('records')
    except Exception:
        return None, None


# ----------------------------------------------------------------------- #
# main
# ----------------------------------------------------------------------- #
def reconcile():
    """Build the comparison. Returns (rows, all_ok, last_sync, records)."""
    h, did = _graph()
    files = _list_files(h, did)

    file_by_year = {}
    for it in files:
        fy = _file_year(it['name'])
        path = _download(h, did, it)
        try:
            totals = _file_totals(path)
        finally:
            try:
                os.remove(path)
            except OSError:
                pass
        if not fy:
            continue
        t = totals.get(fy)
        file_by_year[fy] = {
            'name': it['name'],
            'income': t['income'] if t else 0.0,
            'profit': t['profit'] if t else 0.0,
            'ships': len(t['ships']) if t else 0,
        }

    db = _db_totals()
    years = sorted(set(file_by_year) | set(db))

    rows, all_ok = [], True
    for y in years:
        f = file_by_year.get(y)
        d = db.get(y, {'income': 0.0, 'profit': 0.0, 'ships': 0})
        f_inc = f['income'] if f else None
        f_prof = f['profit'] if f else None
        f_ships = f['ships'] if f else None

        d_inc, d_prof, d_ships = d['income'], d['profit'], d['ships']
        inc_ok = f_inc is not None and abs(f_inc - d_inc) <= MONEY_TOL
        prof_ok = f_prof is not None and abs(f_prof - d_prof) <= MONEY_TOL
        ships_ok = f_ships is not None and f_ships == d_ships
        ok = inc_ok and prof_ok and ships_ok
        if not ok:
            all_ok = False

        rows.append({
            'year': y, 'file': f['name'] if f else '(no file)',
            'f_inc': f_inc, 'd_inc': d_inc, 'inc_ok': inc_ok,
            'f_prof': f_prof, 'd_prof': d_prof, 'prof_ok': prof_ok,
            'f_ships': f_ships, 'd_ships': d_ships, 'ships_ok': ships_ok,
            'ok': ok,
        })

    last_sync, records = _last_sync()
    return rows, all_ok, last_sync, records


def _build_html(rows, all_ok, last_sync, records):
    badge = ('<span style="color:#1e7d32;font-weight:bold;">&#10004; ALL MATCH</span>'
             if all_ok else
             '<span style="color:#c0392b;font-weight:bold;">&#10006; MISMATCH FOUND</span>')

    def cell(val, ok, money=True):
        colour = '' if ok else 'background:#fde8e8;color:#c0392b;'
        text = _money(val) if money else ('—' if val is None else f'{val:,}')
        return f'<td style="padding:6px 10px;text-align:right;{colour}">{text}</td>'

    body = [f"""
    <div style="font-family:Segoe UI,Arial,sans-serif;color:#1f3864;">
      <h2 style="margin:0 0 4px;">Up-Down Trader — File vs Database</h2>
      <p style="margin:0 0 12px;">{badge}</p>
      <p style="margin:0 0 16px;font-size:13px;color:#444;">
        Last synced: <b>{last_sync or 'unknown'}</b>
        {f'&nbsp;·&nbsp; {records:,} records' if records else ''}
      </p>
      <table style="border-collapse:collapse;font-size:13px;">
        <tr style="background:#1f3864;color:#fff;">
          <th style="padding:6px 10px;">Year</th>
          <th style="padding:6px 10px;text-align:right;">File Revenue</th>
          <th style="padding:6px 10px;text-align:right;">DB Revenue</th>
          <th style="padding:6px 10px;text-align:right;">File Profit</th>
          <th style="padding:6px 10px;text-align:right;">DB Profit</th>
          <th style="padding:6px 10px;text-align:right;">File Jobs</th>
          <th style="padding:6px 10px;text-align:right;">DB Jobs</th>
          <th style="padding:6px 10px;">Status</th>
        </tr>"""]

    for r in rows:
        status = ('<span style="color:#1e7d32;">&#10004;</span>' if r['ok']
                  else '<span style="color:#c0392b;">&#10006;</span>')
        body.append(
            '<tr style="border-bottom:1px solid #e0e0e0;">'
            f'<td style="padding:6px 10px;font-weight:bold;">{r["year"]}</td>'
            + cell(r['f_inc'], r['inc_ok']) + cell(r['d_inc'], r['inc_ok'])
            + cell(r['f_prof'], r['prof_ok']) + cell(r['d_prof'], r['prof_ok'])
            + cell(r['f_ships'], r['ships_ok'], money=False)
            + cell(r['d_ships'], r['ships_ok'], money=False)
            + f'<td style="padding:6px 10px;text-align:center;">{status}</td>'
            '</tr>')

    body.append("""
      </table>
      <p style="margin:14px 0 0;font-size:12px;color:#777;">
        "File" = rows recognised in that year, summed from the SharePoint shipment
        file. "DB" = the same figures from customer_spend_operational (what the
        report is built from). Red cells are where they differ by more than 1 cent
        / 1 job.
      </p>
    </div>""")
    return ''.join(body)


def _build_text(rows, all_ok, last_sync, records):
    lines = ['Up-Down Trader — File vs Database',
             ('ALL MATCH' if all_ok else 'MISMATCH FOUND'),
             f'Last synced: {last_sync or "unknown"}'
             + (f'  ({records} records)' if records else ''), '']
    for r in rows:
        lines.append(
            f"{r['year']}: "
            f"Rev file {_money(r['f_inc'])} / db {_money(r['d_inc'])} | "
            f"Profit file {_money(r['f_prof'])} / db {_money(r['d_prof'])} | "
            f"Jobs file {r['f_ships']} / db {r['d_ships']} | "
            f"{'OK' if r['ok'] else 'MISMATCH'}")
    return '\n'.join(lines)


def build_reconcile_pdf():
    """Build a simple one-page PDF: per year File value vs Database value, plus
    the last-synced date. Returns (pdf_bytes, filename), or (None, None) if the
    fpdf library isn't installed."""
    try:
        from fpdf import FPDF
    except ImportError:
        return None, None

    rows, all_ok, last_sync, records = reconcile()
    when = (last_sync or 'unknown').replace('T', ' ')[:16]

    pdf = FPDF()
    pdf.add_page()
    pdf.set_font('Helvetica', 'B', 16)
    pdf.cell(0, 10, 'Up-Down Trader - File vs Database', ln=1)
    pdf.set_font('Helvetica', '', 11)
    pdf.cell(0, 8, f'Last synced: {when}', ln=1)
    pdf.cell(0, 8, 'Status: ' + ('ALL MATCH' if all_ok else 'MISMATCH FOUND'), ln=1)
    pdf.ln(4)

    pdf.set_font('Helvetica', 'B', 11)
    pdf.cell(30, 9, 'Year', border=1)
    pdf.cell(60, 9, 'File Value', border=1, align='R')
    pdf.cell(60, 9, 'Database Value', border=1, align='R')
    pdf.ln()
    pdf.set_font('Helvetica', '', 11)
    for r in rows:
        pdf.cell(30, 9, str(r['year']), border=1)
        pdf.cell(60, 9, _money(r['f_inc']), border=1, align='R')
        pdf.cell(60, 9, _money(r['d_inc']), border=1, align='R')
        pdf.ln()

    raw = pdf.output(dest='S')
    pdf_bytes = raw.encode('latin1') if isinstance(raw, str) else bytes(raw)
    return pdf_bytes, 'updown_file_vs_db.pdf'


def run_reconciliation(send=True, recipients=None):
    """Run the reconciliation and (optionally) email the result.

    Returns a summary dict: {'all_ok': bool, 'rows': [...], 'sent': bool}.
    """
    rows, all_ok, last_sync, records = reconcile()
    html = _build_html(rows, all_ok, last_sync, records)
    text = _build_text(rows, all_ok, last_sync, records)
    subject = ('Up-Down Trader reconciliation: ALL MATCH' if all_ok
               else 'Up-Down Trader reconciliation: MISMATCH FOUND')

    print(text)

    # update the sync-health dashboard (best effort)
    try:
        from dashboard.scheduler import update_sync_health
        update_sync_health('updown_reconcile',
                           'success' if all_ok else 'warning',
                           subject, len(rows))
    except Exception as e:
        print('sync_health update skipped:', e)

    sent = False
    if send:
        # Send via Graph (Office 365) only. AWS SES is intentionally NOT used.
        from dashboard.views import _graph_send_simple
        for to in (recipients or RECIPIENTS):
            ok, msg = _graph_send_simple(to, subject, body_html=html, body_text=text)
            print(f'  email -> {to}: {"sent" if ok else "FAILED " + str(msg)}')
            sent = sent or ok

    return {'all_ok': all_ok, 'rows': rows, 'sent': sent}


if __name__ == '__main__':
    run_reconciliation(send=True)
