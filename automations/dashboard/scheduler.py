from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from django.conf import settings
import json
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

scheduler = None


def update_sync_health(station, status, message, records=0):
    """Write sync health info for a station to sync_health.json"""
    import tempfile
    try:
        health_file = settings.SYNC_HEALTH_FILE
        health_data = {}
        if os.path.exists(health_file):
            try:
                with open(health_file, 'r') as f:
                    health_data = json.load(f)
            except (json.JSONDecodeError, ValueError):
                logger.warning(f"Corrupted sync_health.json, resetting")
                health_data = {}

        local_time = datetime.now(ZoneInfo('Africa/Johannesburg'))
        health_data[station] = {
            'last_check': local_time.isoformat(),
            'status': status,
            'message': message,
            'records': records,
        }

        # Atomic write to prevent corruption from concurrent workers
        dir_name = os.path.dirname(health_file)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(health_data, f, indent=2)
            os.replace(tmp_path, health_file)
        except Exception:
            os.unlink(tmp_path)
            raise
    except Exception as e:
        logger.error(f"Failed to update sync health for {station}: {e}")


def run_sync_job():
    """Run the OneDrive sync job for turnover data"""
    from . import onedrive_sync
    from .views import update_progress
    try:
        logger.info("Starting scheduled OneDrive sync...")
        update_progress('running', 'Scheduled sync starting...', 0, 100)
        count = onedrive_sync.sync_turnover_data()
        logger.info(f"Scheduled sync complete: {count} records synced")
        update_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('turnover', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled sync error: {e}")
        update_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('turnover', 'error', str(e))


def run_ppg_sync_job():
    """PAUSED — old OneDrive PPG sync. Kept callable for manual fallback button."""
    from . import onedrive_sync
    from .views import update_ppg_progress
    try:
        logger.info("Starting scheduled PPG sync...")
        update_ppg_progress('running', 'Scheduled PPG sync starting...', 0, 100)
        count = onedrive_sync.sync_ppg_data()
        logger.info(f"Scheduled PPG sync complete: {count} records synced")
        update_ppg_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('ppg', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled PPG sync error: {e}")
        update_ppg_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('ppg', 'error', str(e))


# ═══════════════════════════════════════════════════════════════════════
# Email-based sync framework
# All stations now ingest from ethan.sevenster@moc-pty.com mailbox instead
# of OneDrive. Scheduled to check every 3 hours.
# ═══════════════════════════════════════════════════════════════════════

EMAIL_MAILBOX = 'ethan.sevenster@moc-pty.com'

# key -> (sender, subject-contains, parser function name, pnl table name)
# All financial-analysis stations share the same {table}_pnl schema:
#   (division, account_name, value, date, date_fixed, budget_actual, week, report_date)
STATION_EMAIL_CONFIG = {
    'ppg':        ('gerald.lowe@awaship.com',          'PPG Financial Analysis',   'process_ppg_excel_file', 'ppg_pnl'),
    'ccc':        ('gerald.lowe@awaship.com',          'CCC Financial Analysis',   'process_ccc_excel_file', 'ccc_pnl'),
    'ccd':        ('gerald.lowe@awaship.com',          'CCD Financial Analysis',   'process_ccd_excel_file', 'ccd_pnl'),
    'hnl':        ('gerald.lowe@awaship.com',          'HNL Financial Analysis',   'process_hnl_excel_file', 'hnl_pnl'),
    'jfk':        ('gerald.lowe@awaship.com',          'JFK Financial Analysis',   'process_jfk_excel_file', 'jfk_pnl'),
    'lcl':        ('gerald.lowe@awaship.com',          'LCL Financial Analysis',   'process_lcl_excel_file', 'lcl_pnl'),
    'hou':        ('gerald.lowe@awaship.com',          'HOU Financial Analysis',   'process_hou_excel_file', 'hou_pnl'),
    'ics':        ('gerald.lowe@awaship.com',          'ICS Financial Analysis',   'process_ics_excel_file', 'ics_pnl'),
    'ord':        ('gerald.lowe@awaship.com',          'ORD Financial Analysis',   'process_ord_excel_file', 'ord_pnl'),
    'imp':        ('gerald.lowe@awaship.com',          'IMP Financial Analysis',   'process_imp_excel_file', 'imp_pnl'),
    'lax':        ('gerald.lowe@awaship.com',          'LAX Financial Analysis',   'process_lax_excel_file', 'lax_pnl'),
    'fax':        ('anthony.penzes@intelligentscm.com', 'FAX Financial Analysis',  'process_fax_excel_file', 'fax_pnl'),
    'atl':        ('anthony.penzes@intelligentscm.com', 'ATL Financial Analysis',  'process_atl_excel_file', 'atl_pnl'),
    'dfw':        ('anthony.penzes@intelligentscm.com', 'DFW Financial Analysis',  'process_dfw_excel_file', 'dfw_pnl'),
    'con':        ('anthony.penzes@intelligentscm.com', 'CON Financial Analysis',  'process_con_excel_file', 'con_pnl'),
    'dor':        ('anthony.penzes@intelligentscm.com', 'DOR Combined Financial Analysis', 'process_dor_excel_file', 'dor_pnl'),
}


def _fetch_latest_station_email(key, sender, subject_kw):
    """Return (msg_id, subject, received, xlsx_name, xlsx_bytes) or (None,...)"""
    import base64, requests
    from .views import _get_graph_token

    token = _get_graph_token()
    if not token:
        raise RuntimeError('Graph token unavailable')
    headers = {'Authorization': f'Bearer {token}'}

    # Inbox scan (recent 100 messages is plenty for 3-hourly run; older ones we already processed)
    r = requests.get(
        f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages',
        headers=headers,
        params={'$top': 100, '$orderby': 'receivedDateTime desc',
                '$select': 'id,subject,receivedDateTime,from,hasAttachments'},
        timeout=30,
    )
    r.raise_for_status()
    msgs = [
        m for m in r.json().get('value', [])
        if m.get('hasAttachments')
        and m.get('from', {}).get('emailAddress', {}).get('address', '').lower() == sender.lower()
        and subject_kw.lower() in (m.get('subject', '').lower())
    ]
    if not msgs:
        return (None, None, None, None, None)
    msg = msgs[0]
    ar = requests.get(
        f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages/{msg["id"]}/attachments',
        headers=headers, timeout=60,
    )
    ar.raise_for_status()
    xlsx = next((a for a in ar.json().get('value', [])
                 if a.get('name', '').lower().endswith(('.xlsx', '.xls'))), None)
    if not xlsx:
        return (msg['id'], msg['subject'], msg['receivedDateTime'], None, None)
    return (msg['id'], msg['subject'], msg['receivedDateTime'],
            xlsx['name'], base64.b64decode(xlsx['contentBytes']))


def _run_station_email_sync(key):
    """Fetch the latest email attachment for a station, parse it with the station's
    Excel parser, and insert into {key}_pnl. Idempotent via messageId tracking."""
    import os, json, io
    from django.db import connection
    from psycopg2.extras import execute_values
    from . import onedrive_sync

    cfg = STATION_EMAIL_CONFIG.get(key)
    if not cfg:
        logger.error(f'No email config for station {key!r}')
        return
    sender, subject_kw, parser_fn_name, table = cfg
    parser_fn = getattr(onedrive_sync, parser_fn_name, None)
    if not parser_fn:
        logger.error(f'Parser {parser_fn_name} not found')
        return

    STATE_FILE = os.path.join(os.path.dirname(__file__), '..', f'{key}_email_last.json')

    try:
        logger.info(f'[{key}] email sync: checking mailbox...')
        msg_id, subject, received, fname, fbytes = _fetch_latest_station_email(key, sender, subject_kw)
        if not msg_id:
            update_sync_health(key, 'success', f'No {key.upper()} email found yet', 0)
            return
        if not fbytes:
            update_sync_health(key, 'error', f'{key.upper()} email had no Excel attachment', 0)
            return

        # Idempotency
        try:
            last = json.load(open(STATE_FILE))
            if last.get('message_id') == msg_id:
                update_sync_health(key, 'success',
                                   f'Already processed: {received[:10]}', last.get('rows', 0))
                return
        except Exception:
            pass

        # Parse — all station parsers accept a file-like object
        rows = parser_fn(io.BytesIO(fbytes), fname)
        if not rows:
            update_sync_health(key, 'success', f'Email parsed but 0 rows: {received[:10]}', 0)
            with open(STATE_FILE, 'w') as f:
                json.dump({'message_id': msg_id, 'subject': subject,
                           'received': received, 'rows': 0}, f)
            return

        # Insert. Row shape: (division, account_name, value, date, date_fixed,
        # budget_actual, week, report_date). DELETE-then-INSERT per (date, week).
        with connection.cursor() as cur:
            for date_val, week in set((r[3], r[6]) for r in rows):
                cur.execute(
                    f"DELETE FROM {table} WHERE date = %s AND week = %s AND budget_actual = 'Actual'",
                    (date_val, week),
                )
            execute_values(
                cur,
                f"INSERT INTO {table} (division, account_name, value, date, date_fixed, budget_actual, week, report_date) VALUES %s",
                rows,
            )

        with open(STATE_FILE, 'w') as f:
            json.dump({'message_id': msg_id, 'subject': subject,
                       'received': received, 'rows': len(rows)}, f)

        update_sync_health(key, 'success',
                           f'Email {received[:10]}: {len(rows)} rows', len(rows))
        logger.info(f'[{key}] email sync complete: {len(rows)} rows from {fname}')

    except Exception as e:
        logger.exception(f'[{key}] email sync failed')
        update_sync_health(key, 'error', str(e))


# Convenience functions for APScheduler (it needs a plain callable per job id)
def run_ppg_email_sync_job():  _run_station_email_sync('ppg')
def run_ccc_email_sync_job():  _run_station_email_sync('ccc')
def run_ccd_email_sync_job():  _run_station_email_sync('ccd')
def run_hnl_email_sync_job():  _run_station_email_sync('hnl')
def run_jfk_email_sync_job():  _run_station_email_sync('jfk')
def run_lcl_email_sync_job():  _run_station_email_sync('lcl')
def run_hou_email_sync_job():  _run_station_email_sync('hou')
def run_ics_email_sync_job():  _run_station_email_sync('ics')
def run_ord_email_sync_job():  _run_station_email_sync('ord')
def run_imp_email_sync_job():  _run_station_email_sync('imp')
def run_lax_email_sync_job():  _run_station_email_sync('lax')
def run_fax_email_sync_job():  _run_station_email_sync('fax')
def run_atl_email_sync_job():  _run_station_email_sync('atl')
def run_dfw_email_sync_job():  _run_station_email_sync('dfw')
def run_con_email_sync_job():  _run_station_email_sync('con')
def run_dor_email_sync_job():  _run_station_email_sync('dor')


def _run_turnover_email_sync():
    """Fetch latest turnover emails (one per branch) and insert into turnover_data."""
    import os, json, io, base64, requests, re
    from django.db import connection
    from psycopg2.extras import execute_values
    from .views import _get_graph_token
    from . import onedrive_sync

    try:
        token = _get_graph_token()
        if not token:
            raise RuntimeError('Graph token unavailable')
        headers = {'Authorization': f'Bearer {token}'}

        # Paginate all turnover emails
        url = (f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages'
               f'?$top=100&$orderby=receivedDateTime desc'
               f'&$select=id,subject,receivedDateTime,from,hasAttachments')
        msgs = []
        while url:
            r = requests.get(url, headers=headers, timeout=30); r.raise_for_status()
            j = r.json()
            for m in j.get('value', []):
                if (m.get('hasAttachments')
                    and 'turnover by debtor' in m.get('subject', '').lower()
                    and m.get('from', {}).get('emailAddress', {}).get('address', '').lower() == 'data.analysis@intelligentscm.com'):
                    msgs.append(m)
            url = j.get('@odata.nextLink')

        if not msgs:
            update_sync_health('turnover', 'success', 'No turnover emails found', 0)
            return

        # Only process the latest email
        msg = msgs[0]
        STATE_FILE = os.path.join(os.path.dirname(__file__), '..', 'turnover_email_last.json')
        try:
            last = json.load(open(STATE_FILE))
            if last.get('message_id') == msg['id']:
                update_sync_health('turnover', 'success', f'Already processed', last.get('rows', 0))
                return
        except Exception:
            pass

        ar = requests.get(
            f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages/{msg["id"]}/attachments',
            headers=headers, timeout=60)
        ar.raise_for_status()
        xlsx = next((a for a in ar.json().get('value', [])
                     if a.get('name', '').lower().endswith(('.xlsx', '.xls'))), None)
        if not xlsx:
            update_sync_health('turnover', 'error', 'No Excel attachment', 0)
            return

        fname = xlsx['name']
        fbytes = base64.b64decode(xlsx['contentBytes'])
        file_content = io.BytesIO(fbytes)

        # Use existing turnover parser (process_excel_file)
        rows = onedrive_sync.process_excel_file(file_content, fname)
        if not rows:
            update_sync_health('turnover', 'success', 'Parsed 0 rows', 0)
            return

        with connection.cursor() as cur:
            # Turnover uses DELETE all + INSERT (snapshot replacement)
            cur.execute("DELETE FROM turnover_data")
            execute_values(cur,
                "INSERT INTO turnover_data (debtor, debtor_name, value, date, date_fixed, branch, report_date) VALUES %s",
                rows)

        with open(STATE_FILE, 'w') as f:
            json.dump({'message_id': msg['id'], 'subject': msg['subject'],
                       'received': msg['receivedDateTime'], 'rows': len(rows)}, f)
        update_sync_health('turnover', 'success', f'Email {msg["receivedDateTime"][:10]}: {len(rows)} rows', len(rows))
        logger.info(f'[turnover] email sync: {len(rows)} rows from {fname}')

    except Exception as e:
        logger.exception('[turnover] email sync failed')
        update_sync_health('turnover', 'error', str(e))


def _run_wip_email_sync():
    """Fetch latest WIP email and insert into wip_accrual."""
    import os, json, io, base64, requests
    from django.db import connection
    from psycopg2.extras import execute_values
    from .views import _get_graph_token
    import openpyxl

    try:
        token = _get_graph_token()
        if not token:
            raise RuntimeError('Graph token unavailable')
        headers = {'Authorization': f'Bearer {token}'}

        url = (f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages'
               f'?$top=100&$orderby=receivedDateTime desc'
               f'&$select=id,subject,receivedDateTime,from,hasAttachments')
        msgs = []
        while url:
            r = requests.get(url, headers=headers, timeout=30); r.raise_for_status()
            j = r.json()
            for m in j.get('value', []):
                if (m.get('hasAttachments')
                    and 'wip rev and accrued costs' in m.get('subject', '').lower()):
                    msgs.append(m)
            url = j.get('@odata.nextLink')

        if not msgs:
            update_sync_health('wip_accrual', 'success', 'No WIP emails found', 0)
            return

        msg = msgs[0]
        STATE_FILE = os.path.join(os.path.dirname(__file__), '..', 'wip_email_last.json')
        try:
            last = json.load(open(STATE_FILE))
            if last.get('message_id') == msg['id']:
                update_sync_health('wip_accrual', 'success', 'Already processed', last.get('rows', 0))
                return
        except Exception:
            pass

        ar = requests.get(
            f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages/{msg["id"]}/attachments',
            headers=headers, timeout=60)
        ar.raise_for_status()
        xlsx = next((a for a in ar.json().get('value', [])
                     if a.get('name', '').lower().endswith(('.xlsx', '.xls'))), None)
        if not xlsx:
            update_sync_health('wip_accrual', 'error', 'No Excel attachment', 0)
            return

        fb = base64.b64decode(xlsx['contentBytes'])
        wb = openpyxl.load_workbook(io.BytesIO(fb), read_only=True, data_only=True)
        ws = wb['Detailed Listing of Outstanding']
        rows = []
        for row in ws.iter_rows(min_row=22, values_only=False):
            cells = [c.value for c in row]
            vals = cells[2:25] if len(cells) > 24 else cells[2:] + [None] * (23 - max(0, len(cells) - 2))
            if not vals[0]:
                continue
            rows.append(tuple(str(v).strip() if v is not None else '' for v in vals))
        wb.close()

        with connection.cursor() as cur:
            cur.execute('DELETE FROM wip_accrual')
            execute_values(cur,
                'INSERT INTO wip_accrual (type,branch,dept,charge_code,job,local_ref,wip,accrual,net_total,added,age,debtor_creditor,stat,job_branch,controlling_agent,controlling_customer,management_group,exp_group,orig,eta,etd,posted_by,posted_by_fullname) VALUES %s',
                rows)

        with open(STATE_FILE, 'w') as f:
            json.dump({'message_id': msg['id'], 'received': msg['receivedDateTime'], 'rows': len(rows)}, f)
        update_sync_health('wip_accrual', 'success', f'Email {msg["receivedDateTime"][:10]}: {len(rows)} rows', len(rows))

    except Exception as e:
        logger.exception('[wip_accrual] email sync failed')
        update_sync_health('wip_accrual', 'error', str(e))


def _run_import_ops_email_sync():
    """Fetch latest import ops email and insert into import_ops."""
    import os, json, io, base64, requests
    from django.db import connection
    from psycopg2.extras import execute_values
    from .views import _get_graph_token
    import openpyxl

    try:
        token = _get_graph_token()
        if not token:
            raise RuntimeError('Graph token unavailable')
        headers = {'Authorization': f'Bearer {token}'}

        url = (f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages'
               f'?$top=100&$orderby=receivedDateTime desc'
               f'&$select=id,subject,receivedDateTime,from,hasAttachments')
        msgs = []
        while url:
            r = requests.get(url, headers=headers, timeout=30); r.raise_for_status()
            j = r.json()
            for m in j.get('value', []):
                if (m.get('hasAttachments')
                    and 'import operational report moc' in m.get('subject', '').lower()):
                    msgs.append(m)
            url = j.get('@odata.nextLink')

        if not msgs:
            update_sync_health('import_ops', 'success', 'No import ops emails found', 0)
            return

        msg = msgs[0]
        STATE_FILE = os.path.join(os.path.dirname(__file__), '..', 'import_ops_email_last.json')
        try:
            last = json.load(open(STATE_FILE))
            if last.get('message_id') == msg['id']:
                update_sync_health('import_ops', 'success', 'Already processed', last.get('rows', 0))
                return
        except Exception:
            pass

        ar = requests.get(
            f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages/{msg["id"]}/attachments',
            headers=headers, timeout=60)
        ar.raise_for_status()
        xlsx = next((a for a in ar.json().get('value', [])
                     if a.get('name', '').lower().endswith(('.xlsx', '.xls'))), None)
        if not xlsx:
            update_sync_health('import_ops', 'error', 'No Excel attachment', 0)
            return

        fb = base64.b64decode(xlsx['contentBytes'])
        wb = openpyxl.load_workbook(io.BytesIO(fb), read_only=True, data_only=True)
        ws = wb['Shipment Profile']
        rows = []
        for row in ws.iter_rows(min_row=15, values_only=False):
            cells = [c.value for c in row]
            vals = cells[2:25] if len(cells) > 24 else cells[2:] + [None] * (23 - max(0, len(cells) - 2))
            if not vals[0]:
                continue
            rows.append(tuple(str(v).strip() if v is not None else '' for v in vals))
        wb.close()

        with connection.cursor() as cur:
            cur.execute('DELETE FROM import_ops')
            execute_values(cur,
                'INSERT INTO import_ops (shipment_id,shipment_direction,report_date,trans,customs_info,mode,origin,origin_country,destination,destination_country,consignor_code,consignor_name,consignee_code,consignee_name,house_ref,incoterm,additional_terms,ppd_ccx,goods_description,origin_etd,destination_eta,weight,weight_unit) VALUES %s',
                rows)

        with open(STATE_FILE, 'w') as f:
            json.dump({'message_id': msg['id'], 'received': msg['receivedDateTime'], 'rows': len(rows)}, f)
        update_sync_health('import_ops', 'success', f'Email {msg["receivedDateTime"][:10]}: {len(rows)} rows', len(rows))

    except Exception as e:
        logger.exception('[import_ops] email sync failed')
        update_sync_health('import_ops', 'error', str(e))


def _run_creditor_email_sync():
    """Fetch latest creditor emails (one per group) and insert into creditor_transactions."""
    import os, json, io, base64, re, requests
    from decimal import Decimal
    from django.db import connection
    from psycopg2.extras import execute_values
    from .views import _get_graph_token
    import openpyxl, xlrd

    try:
        token = _get_graph_token()
        if not token:
            raise RuntimeError('Graph token unavailable')
        headers = {'Authorization': f'Bearer {token}'}

        url = (f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages'
               f'?$top=100&$orderby=receivedDateTime desc'
               f'&$select=id,subject,receivedDateTime,from,hasAttachments')
        all_msgs = []
        while url:
            r = requests.get(url, headers=headers, timeout=30); r.raise_for_status()
            j = r.json()
            for m in j.get('value', []):
                if (m.get('hasAttachments')
                    and 'creditor transaction report - moc' in m.get('subject', '').lower()):
                    all_msgs.append(m)
            url = j.get('@odata.nextLink')

        if not all_msgs:
            update_sync_health('creditor', 'success', 'No creditor emails found', 0)
            return

        # Group by creditor group (last word of subject)
        from collections import defaultdict
        per_group = defaultdict(list)
        for m in all_msgs:
            mm = re.search(r'MOC\s+(\w+)\s*$', m.get('subject', '').strip())
            if mm:
                per_group[mm.group(1).upper()].append(m)

        grand = 0
        with connection.cursor() as cur:
            cur.execute('DELETE FROM creditor_transactions')

        for group, gmsgs in per_group.items():
            gmsgs.sort(key=lambda m: m['receivedDateTime'], reverse=True)
            try:
                ar = requests.get(
                    f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages/{gmsgs[0]["id"]}/attachments',
                    headers=headers, timeout=60)
                ar.raise_for_status()
                x = next((a for a in ar.json().get('value', [])
                          if a.get('name', '').lower().endswith(('.xlsx', '.xls'))), None)
                if not x:
                    continue
                raw_bytes = base64.b64decode(x['contentBytes'])

                ws = None
                wsx = None
                try:
                    wb = openpyxl.load_workbook(io.BytesIO(raw_bytes), data_only=True)
                    ws = wb.active
                    max_row, max_col = ws.max_row, ws.max_column
                except Exception:
                    wbx = xlrd.open_workbook(file_contents=raw_bytes)
                    wsx = wbx.sheet_by_index(0)
                    max_row, max_col = wsx.nrows, wsx.ncols

                def cell(r, c):
                    if ws is not None:
                        return ws.cell(row=r, column=c).value
                    if r - 1 < wsx.nrows and c - 1 < wsx.ncols:
                        v = wsx.cell_value(r - 1, c - 1)
                        return v if v != '' else None
                    return None

                periods = []
                for ci in range(5, max_col + 1):
                    v = cell(8, ci)
                    if v is not None:
                        vs = str(v).strip().split('.')[0]
                        if re.match(r'^\d{6}$', vs):
                            periods.append((ci, vs))

                if not periods:
                    continue

                cur_branch = ''
                rs = []
                for ri in range(9, max_row + 1):
                    cb = cell(ri, 2)
                    if cb is None:
                        continue
                    cb = str(cb).strip()
                    if cb.startswith('Organization Branch:'):
                        mm2 = re.search(r'\(([^)]*)\)', cb)
                        cur_branch = mm2.group(1) if mm2 else ''
                        continue
                    if 'Total' in cb or 'Grand' in cb or cb == '':
                        continue
                    cn = str(cell(ri, 3) or '').strip()
                    if not cn:
                        continue
                    for ci, period in periods:
                        val = cell(ri, ci)
                        if val is not None and str(val).strip() != '':
                            try:
                                v = Decimal(str(val).replace(',', ''))
                            except Exception:
                                continue
                            rs.append((cb, cn, period, v, group, cur_branch))

                if rs:
                    with connection.cursor() as cur:
                        execute_values(cur,
                            'INSERT INTO creditor_transactions (creditor, creditor_name, period, value, creditor_group, branch) VALUES %s',
                            rs)
                    grand += len(rs)
            except Exception as e:
                logger.warning(f'[creditor] {group} failed: {e}')

        update_sync_health('creditor', 'success', f'{len(per_group)} groups, {grand} rows', grand)

    except Exception as e:
        logger.exception('[creditor] email sync failed')
        update_sync_health('creditor', 'error', str(e))


def _run_condor_dor_email_sync():
    """Fetch latest CON + DOR BRK/FEA/TRX emails and insert into condor_dor_pnl."""
    import os, json, io, base64, requests
    from django.db import connection
    from psycopg2.extras import execute_values
    from .views import _get_graph_token
    from . import onedrive_sync

    CONDOR_DOR_FILES = {
        'CON Financial Analysis':     ('CON', 'CON'),
        'DOR BRK Financial Analysis': ('BRK', 'DOR'),
        'DOR FEA Financial Analysis': ('FEA', 'DOR'),
        'DOR TRX Financial Analysis': ('TRX', 'DOR'),
    }

    try:
        token = _get_graph_token()
        if not token:
            raise RuntimeError('Graph token unavailable')
        headers = {'Authorization': f'Bearer {token}'}

        url = (f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages'
               f'?$top=100&$orderby=receivedDateTime desc'
               f'&$select=id,subject,receivedDateTime,from,hasAttachments')
        all_msgs = []
        while url:
            r = requests.get(url, headers=headers, timeout=30); r.raise_for_status()
            j = r.json()
            all_msgs.extend(j.get('value', []))
            url = j.get('@odata.nextLink')

        grand = 0
        for subj_kw, (department, branch) in CONDOR_DOR_FILES.items():
            matches = [m for m in all_msgs
                       if m.get('hasAttachments')
                       and subj_kw.lower() in m.get('subject', '').lower()]
            if not matches:
                continue
            matches.sort(key=lambda m: m['receivedDateTime'], reverse=True)
            msg = matches[0]

            ar = requests.get(
                f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages/{msg["id"]}/attachments',
                headers=headers, timeout=60)
            ar.raise_for_status()
            xlsx = next((a for a in ar.json().get('value', [])
                         if a.get('name', '').lower().endswith(('.xlsx', '.xls'))), None)
            if not xlsx:
                continue

            fb = base64.b64decode(xlsx['contentBytes'])
            # Parse using PPG parser (same GL PL Period Analysis format)
            pnl_rows = onedrive_sync.process_ppg_excel_file(io.BytesIO(fb), xlsx['name'])
            if not pnl_rows:
                continue
            # Convert to condor_dor_pnl schema: (department, account_name, value, date, date_fixed, branch, budget_actual)
            rows = [(department, r[1], r[2], str(r[3]), r[4], branch, r[5]) for r in pnl_rows]

            with connection.cursor() as cur:
                cur.execute("DELETE FROM condor_dor_pnl WHERE department = %s", (department,))
                execute_values(cur,
                    "INSERT INTO condor_dor_pnl (department, account_name, value, date, date_fixed, branch, budget_actual) VALUES %s",
                    rows)
            grand += len(rows)

        update_sync_health('condor_dor', 'success', f'{grand} rows across 4 files', grand)

    except Exception as e:
        logger.exception('[condor_dor] email sync failed')
        update_sync_health('condor_dor', 'error', str(e))


def run_turnover_email_sync_job():  _run_turnover_email_sync()
def run_wip_email_sync_job():       _run_wip_email_sync()
def run_import_ops_email_sync_job(): _run_import_ops_email_sync()
def run_creditor_email_sync_job():  _run_creditor_email_sync()
def run_condor_dor_email_sync_job(): _run_condor_dor_email_sync()


def run_dor_sync_job():
    """Run the DOR sync job"""
    from . import onedrive_sync
    from .views import update_dor_progress
    try:
        logger.info("Starting scheduled DOR sync...")
        update_dor_progress('running', 'Scheduled DOR sync starting...', 0, 100)
        count = onedrive_sync.sync_dor_data()
        logger.info(f"Scheduled DOR sync complete: {count} records synced")
        update_dor_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('dor', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled DOR sync error: {e}")
        update_dor_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('dor', 'error', str(e))


def run_con_sync_job():
    """Run the CON sync job"""
    from . import onedrive_sync
    from .views import update_con_progress
    try:
        logger.info("Starting scheduled CON sync...")
        update_con_progress('running', 'Scheduled CON sync starting...', 0, 100)
        count = onedrive_sync.sync_con_data()
        logger.info(f"Scheduled CON sync complete: {count} records synced")
        update_con_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('con', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled CON sync error: {e}")
        update_con_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('con', 'error', str(e))


def run_ccd_sync_job():
    """Run the CCD sync job"""
    from . import onedrive_sync
    from .views import update_ccd_progress
    try:
        logger.info("Starting scheduled CCD sync...")
        update_ccd_progress('running', 'Scheduled CCD sync starting...', 0, 100)
        count = onedrive_sync.sync_ccd_data()
        logger.info(f"Scheduled CCD sync complete: {count} records synced")
        update_ccd_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('ccd', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled CCD sync error: {e}")
        update_ccd_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('ccd', 'error', str(e))


def run_atl_sync_job():
    """Run the ATL sync job"""
    from . import onedrive_sync
    from .views import update_atl_progress
    try:
        logger.info("Starting scheduled ATL sync...")
        update_atl_progress('running', 'Scheduled ATL sync starting...', 0, 100)
        count = onedrive_sync.sync_atl_data()
        logger.info(f"Scheduled ATL sync complete: {count} records synced")
        update_atl_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('atl', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled ATL sync error: {e}")
        update_atl_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('atl', 'error', str(e))


def run_ccc_sync_job():
    """Run the CCC sync job"""
    from . import onedrive_sync
    from .views import update_ccc_progress
    try:
        logger.info("Starting scheduled CCC sync...")
        update_ccc_progress('running', 'Scheduled CCC sync starting...', 0, 100)
        count = onedrive_sync.sync_ccc_data()
        logger.info(f"Scheduled CCC sync complete: {count} records synced")
        update_ccc_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('ccc', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled CCC sync error: {e}")
        update_ccc_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('ccc', 'error', str(e))


def run_hnl_sync_job():
    """Run the HNL sync job"""
    from . import onedrive_sync
    from .views import update_hnl_progress
    try:
        logger.info("Starting scheduled HNL sync...")
        update_hnl_progress('running', 'Scheduled HNL sync starting...', 0, 100)
        count = onedrive_sync.sync_hnl_data()
        logger.info(f"Scheduled HNL sync complete: {count} records synced")
        update_hnl_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('hnl', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled HNL sync error: {e}")
        update_hnl_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('hnl', 'error', str(e))


def run_jfk_sync_job():
    """Run the JFK sync job"""
    from . import onedrive_sync
    from .views import update_jfk_progress
    try:
        logger.info("Starting scheduled JFK sync...")
        update_jfk_progress('running', 'Scheduled JFK sync starting...', 0, 100)
        count = onedrive_sync.sync_jfk_data()
        logger.info(f"Scheduled JFK sync complete: {count} records synced")
        update_jfk_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('jfk', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled JFK sync error: {e}")
        update_jfk_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('jfk', 'error', str(e))


def run_fax_sync_job():
    """Run the FAX sync job"""
    from . import onedrive_sync
    from .views import update_fax_progress
    try:
        logger.info("Starting scheduled FAX sync...")
        update_fax_progress('running', 'Scheduled FAX sync starting...', 0, 100)
        count = onedrive_sync.sync_fax_data()
        logger.info(f"Scheduled FAX sync complete: {count} records synced")
        update_fax_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('fax', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled FAX sync error: {e}")
        update_fax_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('fax', 'error', str(e))


def run_hou_sync_job():
    """Run the HOU sync job"""
    from . import onedrive_sync
    from .views import update_hou_progress
    try:
        logger.info("Starting scheduled HOU sync...")
        update_hou_progress('running', 'Scheduled HOU sync starting...', 0, 100)
        count = onedrive_sync.sync_hou_data()
        logger.info(f"Scheduled HOU sync complete: {count} records synced")
        update_hou_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('hou', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled HOU sync error: {e}")
        update_hou_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('hou', 'error', str(e))


def run_ics_sync_job():
    """Run the ICS sync job"""
    from . import onedrive_sync
    from .views import update_ics_progress
    try:
        logger.info("Starting scheduled ICS sync...")
        update_ics_progress('running', 'Scheduled ICS sync starting...', 0, 100)
        count = onedrive_sync.sync_ics_data()
        logger.info(f"Scheduled ICS sync complete: {count} records synced")
        update_ics_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('ics', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled ICS sync error: {e}")
        update_ics_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('ics', 'error', str(e))


def run_imp_sync_job():
    """Run the IMP sync job"""
    from . import onedrive_sync
    from .views import update_imp_progress
    try:
        logger.info("Starting scheduled IMP sync...")
        update_imp_progress('running', 'Scheduled IMP sync starting...', 0, 100)
        count = onedrive_sync.sync_imp_data()
        logger.info(f"Scheduled IMP sync complete: {count} records synced")
        update_imp_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('imp', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled IMP sync error: {e}")
        update_imp_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('imp', 'error', str(e))


def run_lax_sync_job():
    """Run the LAX sync job"""
    from . import onedrive_sync
    from .views import update_lax_progress
    try:
        logger.info("Starting scheduled LAX sync...")
        update_lax_progress('running', 'Scheduled LAX sync starting...', 0, 100)
        count = onedrive_sync.sync_lax_data()
        logger.info(f"Scheduled LAX sync complete: {count} records synced")
        update_lax_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('lax', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled LAX sync error: {e}")
        update_lax_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('lax', 'error', str(e))


def run_lcl_sync_job():
    """Run the LCL sync job"""
    from . import onedrive_sync
    from .views import update_lcl_progress
    try:
        logger.info("Starting scheduled LCL sync...")
        update_lcl_progress('running', 'Scheduled LCL sync starting...', 0, 100)
        count = onedrive_sync.sync_lcl_data()
        logger.info(f"Scheduled LCL sync complete: {count} records synced")
        update_lcl_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('lcl', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled LCL sync error: {e}")
        update_lcl_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('lcl', 'error', str(e))


def run_ord_sync_job():
    """Run the ORD sync job"""
    from . import onedrive_sync
    from .views import update_ord_progress
    try:
        logger.info("Starting scheduled ORD sync...")
        update_ord_progress('running', 'Scheduled ORD sync starting...', 0, 100)
        count = onedrive_sync.sync_ord_data()
        logger.info(f"Scheduled ORD sync complete: {count} records synced")
        update_ord_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('ord', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled ORD sync error: {e}")
        update_ord_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('ord', 'error', str(e))


def run_dfw_sync_job():
    """Run the DFW sync job"""
    from . import onedrive_sync
    from .views import update_dfw_progress
    try:
        logger.info("Starting scheduled DFW sync...")
        update_dfw_progress('running', 'Scheduled DFW sync starting...', 0, 100)
        count = onedrive_sync.sync_dfw_data()
        logger.info(f"Scheduled DFW sync complete: {count} records synced")
        update_dfw_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('dfw', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled DFW sync error: {e}")
        update_dfw_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('dfw', 'error', str(e))


def run_import_ops_sync_job():
    """Run the Import Ops sync job"""
    from . import onedrive_sync
    from .views import update_import_ops_progress
    try:
        logger.info("Starting scheduled Import Ops sync...")
        update_import_ops_progress('running', 'Scheduled Import Ops sync starting...', 0, 100)
        count = onedrive_sync.sync_import_ops_data()
        logger.info(f"Scheduled Import Ops sync complete: {count} records synced")
        update_import_ops_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('import_ops', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled Import Ops sync error: {e}")
        update_import_ops_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('import_ops', 'error', str(e))


def run_wip_accrual_sync_job():
    """Run the WIP Accrual sync job"""
    from . import onedrive_sync
    from .views import update_wip_accrual_progress
    try:
        logger.info("Starting scheduled WIP Accrual sync...")
        update_wip_accrual_progress('running', 'Scheduled WIP Accrual sync starting...', 0, 100)
        count = onedrive_sync.sync_wip_accrual_data()
        logger.info(f"Scheduled WIP Accrual sync complete: {count} records synced")
        update_wip_accrual_progress('complete', f'Synced {count} records', 100, 100)
        update_sync_health('wip_accrual', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled WIP Accrual sync error: {e}")
        update_wip_accrual_progress('error', f'Scheduled sync error: {str(e)}', 0, 100)
        update_sync_health('wip_accrual', 'error', str(e))


def run_creditor_sync_job():
    """Run the Creditor sync job"""
    from . import onedrive_sync
    try:
        logger.info("Starting scheduled Creditor sync...")
        count = onedrive_sync.sync_creditor_data()
        logger.info(f"Scheduled Creditor sync complete: {count} records synced")
        update_sync_health('creditor', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled Creditor sync error: {e}")
        update_sync_health('creditor', 'error', str(e))


def run_condor_dor_sync_job():
    """Run the Condor+DOR PNL sync job"""
    from . import onedrive_sync
    try:
        logger.info("Starting scheduled Condor+DOR sync...")
        count = onedrive_sync.sync_condor_dor_data()
        logger.info(f"Scheduled Condor+DOR sync complete: {count} records synced")
        update_sync_health('condor_dor', 'success', f'No file' if count == 0 else f'Synced {count} records', count)
    except Exception as e:
        logger.error(f"Scheduled Condor+DOR sync error: {e}")
        update_sync_health('condor_dor', 'error', str(e))


def run_scheduled_touchpoints():
    """Check if any touchpoints are due today (per-contact date) and send them.

    For each TP (2-10), finds contacts whose individual touchpoint_N date
    matches today (DD-MM-YYYY) and whose tp_sent_on is still empty.
    This means even if a date is changed the day before, it will fire
    on the correct day.
    """
    from .models import TouchpointTemplate, USEUContact
    import subprocess
    import sys as _sys

    today = datetime.now(ZoneInfo('America/Los_Angeles')).date()
    today_str = today.strftime('%d-%m-%Y')
    logger.info(f"Checking scheduled touchpoints for {today_str}...")

    # Don't send on Monday (0), Friday (4), Saturday (5), Sunday (6)
    if today.weekday() in (0, 4, 5, 6):
        logger.info(f"Skipping touchpoint sends — today is {today.strftime('%A')} (no sends on Mon/Fri/Sat/Sun)")
        return

    # Don't send on US public holidays
    from .views import _us_holidays
    if today in _us_holidays(today.year):
        logger.info(f"Skipping touchpoint sends — today is a US public holiday")
        return

    for tp_num in range(1, 11):
        # Check template exists (needed for email content)
        try:
            TouchpointTemplate.objects.get(touchpoint_number=tp_num)
        except TouchpointTemplate.DoesNotExist:
            continue

        tp_field = f'touchpoint_{tp_num}'
        tp_sent_field = f'tp{tp_num}_sent_on'

        # Find contacts whose individual TP date is today and not yet sent
        eligible = USEUContact.objects.filter(
            status='Active',
            **{tp_field: today_str, tp_sent_field: ''}
        ).exclude(email='').exclude(email__isnull=True).count()

        if eligible == 0:
            continue

        logger.info(f"TP{tp_num} due today for {eligible} contacts, launching send...")

        job_id = f'tp{tp_num}_auto_{int(datetime.now().timestamp())}'

        # Create job file for progress tracking
        _job_file = os.path.join(os.path.dirname(__file__), '..', f'send_job_{job_id}.json')
        try:
            import tempfile as _tempfile
            _fd, _tmp = _tempfile.mkstemp(dir=os.path.dirname(_job_file), suffix='.tmp')
            with os.fdopen(_fd, 'w') as _f:
                json.dump({'total': eligible, 'sent': 0, 'failed': 0, 'current': '', 'done': False, 'results': []}, _f)
            os.replace(_tmp, _job_file)
        except Exception:
            pass

        # Launch the worker subprocess
        _worker = os.path.join(os.path.dirname(__file__), '..', 'send_campaign_worker.py')
        try:
            subprocess.Popen(
                [_sys.executable, _worker, '--tp-num', str(tp_num), '--job-id', job_id],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            logger.info(f"TP{tp_num} send launched with job_id={job_id}")
            update_sync_health(f'tp{tp_num}_auto', 'success', f'Auto-sent to {eligible} contacts')
        except Exception as e:
            logger.error(f"Failed to launch TP{tp_num} send: {e}")
            update_sync_health(f'tp{tp_num}_auto', 'error', str(e))


def check_bounce_emails():
    """Check the mailbox for bounce/NDR messages and mark contacts as Undeliverable."""
    from .models import USEUContact
    from .views import _get_graph_token, GRAPH_MAILBOX
    import requests as http_requests
    import re as _re

    try:
        token = _get_graph_token()
        if not token:
            logger.error("Bounce check: could not get Graph token")
            return

        # Search for undeliverable/bounce messages in the last 24 hours
        headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}
        # Filter for messages with common bounce subjects
        base_url = (
            f"https://graph.microsoft.com/v1.0/users/{GRAPH_MAILBOX}/messages"
            f"?$filter=isRead eq false and ("
            f"contains(subject,'Undeliverable') or "
            f"contains(subject,'Delivery has failed') or "
            f"contains(subject,'Mail delivery failed') or "
            f"contains(subject,'Returned mail') or "
            f"contains(subject,'Non-delivery') or "
            f"contains(subject,'Failure') or "
            f"contains(subject,'could not be delivered'))"
            f"&$top=200&$select=id,subject,body,receivedDateTime"
        )

        # Paginate through all bounce messages
        all_messages = []
        url = base_url
        while url:
            r = http_requests.get(url, headers=headers, timeout=30)
            if r.status_code != 200:
                logger.warning(f"Bounce check: HTTP {r.status_code}")
                break
            data = r.json()
            all_messages.extend(data.get('value', []))
            url = data.get('@odata.nextLink')  # next page if exists
            if len(all_messages) >= 1000:  # safety cap
                break

        messages = all_messages
        if not messages:
            return

        logger.info(f"Bounce check: found {len(messages)} bounce messages")
        marked = 0

        for msg in messages:
            body_text = msg.get('body', {}).get('content', '')
            # Extract email addresses from the bounce message
            emails_found = _re.findall(r'[\w.+-]+@[\w-]+\.[\w.-]+', body_text)

            for bounced_email in set(emails_found):
                bounced_email = bounced_email.lower().strip()
                # Skip our own mailbox and common system addresses
                if bounced_email in (GRAPH_MAILBOX.lower(), 'postmaster@', 'mailer-daemon@'):
                    continue
                if 'microsoft.com' in bounced_email or 'postmaster' in bounced_email:
                    continue

                # Find and mark matching contacts
                updated = USEUContact.objects.filter(
                    email__iexact=bounced_email,
                    status='Active'
                ).update(status='Undeliverable')

                if updated:
                    logger.info(f"Bounce check: marked {bounced_email} as Undeliverable ({updated} contacts)")
                    marked += updated

            # Mark bounce message as read
            try:
                http_requests.patch(
                    f"https://graph.microsoft.com/v1.0/users/{GRAPH_MAILBOX}/messages/{msg['id']}",
                    headers=headers,
                    json={'isRead': True},
                    timeout=10
                )
            except Exception:
                pass

        if marked:
            update_sync_health('bounce_check', 'success', f'Marked {marked} contacts as Undeliverable')
            logger.info(f"Bounce check complete: {marked} contacts marked Undeliverable")
        else:
            update_sync_health('bounce_check', 'success', f'Checked {len(messages)} bounces, no new contacts affected')

    except Exception as e:
        logger.error(f"Bounce check error: {e}")
        update_sync_health('bounce_check', 'error', str(e))


def refresh_onedrive_token():
    """Refresh the OneDrive access token to keep it alive.

    The actual retry logic lives in get_access_token() which retries 3 times
    with backoff. This function tracks the result in sync health so the
    monitoring dashboard shows token status.
    """
    from . import onedrive_sync
    try:
        token = onedrive_sync.get_access_token()
        if token:
            logger.info("OneDrive token refreshed successfully")
            update_sync_health('onedrive_token', 'success', 'Token is active')
        else:
            logger.error("OneDrive token refresh returned None - all retries exhausted")
            update_sync_health('onedrive_token', 'error', 'Token refresh failed - re-authentication may be required')
    except Exception as e:
        logger.error(f"OneDrive token refresh error: {e}")
        update_sync_health('onedrive_token', 'error', f'Token refresh exception: {e}')


def start_scheduler():
    """Start the background scheduler"""
    global scheduler

    if scheduler is not None:
        return

    scheduler = BackgroundScheduler()

    # Run turnover sync every hour
    scheduler.add_job(
        run_sync_job,
        trigger=IntervalTrigger(hours=1),
        id='onedrive_sync',
        name='Sync OneDrive turnover data every hour',
        replace_existing=True
    )

    # ── PPG OneDrive sync PAUSED ─ now ingesting from weekly Sunday email via Graph.
    # Keep the handler wired so Sync Monitor's manual button still works as a fallback.
    # scheduler.add_job(
    #     run_ppg_sync_job,
    #     trigger=IntervalTrigger(hours=1),
    #     id='ppg_sync',
    #     name='Sync PPG data every hour',
    #     replace_existing=True
    # )

    # ═══════════════════════════════════════════════════════════════════
    # Email-based station syncs — every 3 hours
    # Old OneDrive hourly jobs are disabled below; handlers remain callable
    # from the manual Sync button as a fallback if the email stream breaks.
    # ═══════════════════════════════════════════════════════════════════
    _EMAIL_JOBS = [
        ('ppg', run_ppg_email_sync_job, 'Ingest weekly PPG email attachment'),
        ('ccc', run_ccc_email_sync_job, 'Ingest weekly CCC email attachment'),
        ('ccd', run_ccd_email_sync_job, 'Ingest weekly CCD email attachment'),
        ('hnl', run_hnl_email_sync_job, 'Ingest weekly HNL email attachment'),
        ('jfk', run_jfk_email_sync_job, 'Ingest weekly JFK email attachment'),
        ('lcl', run_lcl_email_sync_job, 'Ingest weekly LCL email attachment'),
        ('hou', run_hou_email_sync_job, 'Ingest weekly HOU email attachment'),
        ('ics', run_ics_email_sync_job, 'Ingest weekly ICS email attachment'),
        ('ord', run_ord_email_sync_job, 'Ingest weekly ORD email attachment'),
        ('imp', run_imp_email_sync_job, 'Ingest weekly IMP email attachment'),
        ('lax', run_lax_email_sync_job, 'Ingest weekly LAX email attachment'),
        ('fax', run_fax_email_sync_job, 'Ingest weekly FAX email attachment'),
        ('atl', run_atl_email_sync_job, 'Ingest weekly ATL email attachment'),
        ('dfw', run_dfw_email_sync_job, 'Ingest weekly DFW email attachment'),
        ('con', run_con_email_sync_job, 'Ingest weekly CON email attachment'),
        ('dor', run_dor_email_sync_job, 'Ingest weekly DOR email attachment'),
        ('turnover', run_turnover_email_sync_job, 'Ingest turnover email attachment'),
        ('wip_accrual', run_wip_email_sync_job, 'Ingest WIP & Accrual email attachment'),
        ('import_ops', run_import_ops_email_sync_job, 'Ingest Import Ops email attachment'),
        ('creditor', run_creditor_email_sync_job, 'Ingest Creditor email attachments'),
        ('condor_dor', run_condor_dor_email_sync_job, 'Ingest Condor+DOR email attachments'),
    ]
    for _key, _fn, _desc in _EMAIL_JOBS:
        scheduler.add_job(
            _fn,
            trigger=IntervalTrigger(hours=3),
            id=f'{_key}_email_sync',
            name=_desc,
            replace_existing=True,
        )

    # ── Old OneDrive hourly jobs (paused — now email-driven) ──
    # scheduler.add_job(run_dor_sync_job, IntervalTrigger(hours=1), id='dor_sync', ...)
    # scheduler.add_job(run_con_sync_job, IntervalTrigger(hours=1), id='con_sync', ...)
    # scheduler.add_job(run_ccd_sync_job, IntervalTrigger(hours=1), id='ccd_sync', ...)
    # scheduler.add_job(run_atl_sync_job, IntervalTrigger(hours=1), id='atl_sync', ...)
    # scheduler.add_job(run_ccc_sync_job, IntervalTrigger(hours=1), id='ccc_sync', ...)
    # scheduler.add_job(run_hnl_sync_job, IntervalTrigger(hours=1), id='hnl_sync', ...)
    # scheduler.add_job(run_jfk_sync_job, IntervalTrigger(hours=1), id='jfk_sync', ...)
    # scheduler.add_job(run_fax_sync_job, IntervalTrigger(hours=1), id='fax_sync', ...)
    # scheduler.add_job(run_hou_sync_job, IntervalTrigger(hours=1), id='hou_sync', ...)
    # scheduler.add_job(run_ics_sync_job, IntervalTrigger(hours=1), id='ics_sync', ...)
    # scheduler.add_job(run_imp_sync_job, IntervalTrigger(hours=1), id='imp_sync', ...)
    # scheduler.add_job(run_lax_sync_job, IntervalTrigger(hours=1), id='lax_sync', ...)
    # scheduler.add_job(run_lcl_sync_job, IntervalTrigger(hours=1), id='lcl_sync', ...)
    # scheduler.add_job(run_ord_sync_job, IntervalTrigger(hours=1), id='ord_sync', ...)
    # scheduler.add_job(run_dfw_sync_job, IntervalTrigger(hours=1), id='dfw_sync', ...)

    # Run Import Ops sync every hour
    scheduler.add_job(
        run_import_ops_sync_job,
        trigger=IntervalTrigger(hours=1),
        id='import_ops_sync',
        name='Sync Import Ops data every hour',
        replace_existing=True
    )

    # Run WIP Accrual sync every hour
    scheduler.add_job(
        run_wip_accrual_sync_job,
        trigger=IntervalTrigger(hours=1),
        id='wip_accrual_sync',
        name='Sync WIP Accrual data every hour',
        replace_existing=True
    )

    # Run Creditor sync every hour
    scheduler.add_job(
        run_creditor_sync_job,
        trigger=IntervalTrigger(hours=1),
        id='creditor_sync',
        name='Sync Creditor data every hour',
        replace_existing=True
    )

    # Run Condor+DOR PNL sync every hour
    scheduler.add_job(
        run_condor_dor_sync_job,
        trigger=IntervalTrigger(hours=1),
        id='condor_dor_sync',
        name='Sync Condor+DOR PNL data every hour',
        replace_existing=True
    )

    # Check and send scheduled touchpoints every 5 minutes
    scheduler.add_job(
        run_scheduled_touchpoints,
        trigger=IntervalTrigger(minutes=5),
        id='scheduled_touchpoints',
        name='Check and send scheduled touchpoints',
        replace_existing=True
    )

    # Check bounce emails every 15 minutes
    scheduler.add_job(
        check_bounce_emails,
        trigger=IntervalTrigger(minutes=15),
        id='bounce_check',
        name='Check bounce emails and mark Undeliverable',
        replace_existing=True
    )

    # Refresh OneDrive token every minute to ensure it never expires
    scheduler.add_job(
        refresh_onedrive_token,
        trigger=IntervalTrigger(minutes=1),
        id='token_refresh',
        name='Refresh OneDrive token every minute',
        replace_existing=True
    )

    scheduler.start()
    logger.info("Scheduler started - All stations syncing every hour, token refresh every minute")

    # Immediately refresh token on startup
    try:
        refresh_onedrive_token()
        logger.info("OneDrive token refreshed on startup")
    except Exception as e:
        logger.error(f"OneDrive token refresh on startup failed: {e}")


def stop_scheduler():
    """Stop the background scheduler"""
    global scheduler
    if scheduler:
        scheduler.shutdown()
        scheduler = None
