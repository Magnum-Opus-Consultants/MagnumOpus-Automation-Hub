from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.triggers.cron import CronTrigger
from django.conf import settings
from django.db import transaction
import json
import os
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)

scheduler = None

# Up-Down Trader: only load shipment files from this year onward (2024, 2025,
# 2026 and every future year). Anything earlier is ignored.
MIN_UPDOWN_YEAR = 2024


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

    # Inbox scan — paginate through all messages to find the latest matching email
    url = (f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages'
           f'?$top=500&$orderby=receivedDateTime desc'
           f'&$select=id,subject,receivedDateTime,from,hasAttachments')
    msgs = []
    while url:
        r = requests.get(url, headers=headers, timeout=60)
        r.raise_for_status()
        j = r.json()
        for m in j.get('value', []):
            if (m.get('hasAttachments')
                and m.get('from', {}).get('emailAddress', {}).get('address', '').lower() == sender.lower()
                and subject_kw.lower() in m.get('subject', '').lower()):
                msgs.append(m)
        # Only paginate if we haven't found any matches yet
        if msgs:
            break
        url = j.get('@odata.nextLink')
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
        # Wrapped in atomic() so a failing INSERT rolls the DELETE back.
        from collections import defaultdict
        with transaction.atomic():
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
                # Create Total rows: one per (division, account_name, date) with latest value
                total_dedup = {}
                for r in rows:
                    dedup_key = (r[0], r[1], r[3], r[5])  # division, account_name, date, budget_actual
                    total_dedup[dedup_key] = (r[0], r[1], r[2], r[3], r[4], r[5], 'Total', r[7])
                total_rows = list(total_dedup.values())
                for date_val in set(r[3] for r in rows):
                    cur.execute(
                        f"DELETE FROM {table} WHERE date = %s AND week = 'Total' AND budget_actual = 'Actual'",
                        (date_val,),
                    )
                execute_values(
                    cur,
                    f"INSERT INTO {table} (division, account_name, value, date, date_fixed, budget_actual, week, report_date) VALUES %s",
                    total_rows,
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


def run_weekly_reports_job():
    """Each morning, create today's recurring report tasks in the Planner."""
    try:
        from django.core.management import call_command
        call_command('create_weekly_reports')
    except Exception as e:
        logger.exception('[weekly_reports] failed to create daily tasks')


# Convenience functions for APScheduler (it needs a plain callable per job id)
def run_bravo_tran_sync_job():
    """Hourly Bravo Trans sync — wipe-and-replace with the latest AWA Payables email.
    Reuses the load_bravo_tran_history management command for a single source of truth."""
    try:
        from django.core.management import call_command
        call_command('load_bravo_tran_history')
        update_sync_health('bravo_tran', 'success', 'Loaded latest AWA Payables email', 0)
    except Exception as e:
        logger.exception('[bravo_tran] hourly sync failed')
        update_sync_health('bravo_tran', 'error', str(e))


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
               f'?$top=500&$orderby=receivedDateTime desc'
               f'&$select=id,subject,receivedDateTime,from,hasAttachments')
        msgs = []
        while url:
            r = requests.get(url, headers=headers, timeout=30); r.raise_for_status()
            j = r.json()
            for m in j.get('value', []):
                if (m.get('hasAttachments')
                    and 'turnover by debtor' in m.get('subject', '').lower()
                    and m.get('from', {}).get('emailAddress', {}).get('address', '').lower() == 'data.excellence@intelligentscm.com'):
                    msgs.append(m)
            url = j.get('@odata.nextLink')

        if not msgs:
            update_sync_health('turnover', 'success', 'No turnover emails found', 0)
            return

        STATE_FILE = os.path.join(os.path.dirname(__file__), '..', 'turnover_email_last.json')

        # Group by branch (from subject) — keep only the latest email per branch
        latest_per_branch = {}
        for m in msgs:
            subj = m.get('subject', '')
            branch = subj.split(' - ')[-1].strip() if ' - ' in subj else None
            if branch and branch not in latest_per_branch:
                latest_per_branch[branch] = m

        # Check idempotency — skip if we already processed this exact set
        try:
            last = json.load(open(STATE_FILE))
            last_ids = set(last.get('message_ids', []))
            current_ids = set(m['id'] for m in latest_per_branch.values())
            if last_ids == current_ids:
                update_sync_health('turnover', 'success', f'Already processed {len(last_ids)} branches', last.get('rows', 0))
                return
        except Exception:
            pass

        total_rows = 0
        branches_done = []

        for branch_name, msg in latest_per_branch.items():
            try:
                ar = requests.get(
                    f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages/{msg["id"]}/attachments',
                    headers=headers, timeout=60)
                ar.raise_for_status()
                xlsx = next((a for a in ar.json().get('value', [])
                             if a.get('name', '').lower().endswith(('.xlsx', '.xls'))), None)
                if not xlsx:
                    logger.warning(f'[turnover] No Excel attachment for {branch_name}')
                    continue

                fname = xlsx['name']
                fbytes = base64.b64decode(xlsx['contentBytes'])
                rows = onedrive_sync.process_excel_file(io.BytesIO(fbytes), fname)
                if not rows:
                    continue

                # Parser returns (debtor, debtor_name, date_str, branch, value, report_date)
                # DB expects (debtor, debtor_name, value, date, date_fixed, branch, report_date)
                mapped = [(r[0], r[1], r[4], r[2], r[2], r[3], r[5]) for r in rows]
                actual_branch = rows[0][3] if rows else branch_name

                # atomic(): if INSERT fails, the DELETE rolls back so we never
                # lose historical rows when replacement data can't be written.
                with transaction.atomic():
                    with connection.cursor() as cur:
                        # Only delete dates covered by the new data, preserve historical data
                        new_dates = set(r[3] for r in mapped)  # date column
                        for d in new_dates:
                            cur.execute("DELETE FROM turnover_data WHERE branch = %s AND date = %s", (actual_branch, d))
                        execute_values(cur,
                            "INSERT INTO turnover_data (debtor, debtor_name, value, date, date_fixed, branch, report_date) VALUES %s",
                            mapped)

                total_rows += len(mapped)
                branches_done.append(actual_branch)
                logger.info(f'[turnover] {actual_branch}: {len(mapped)} rows from {fname}')

            except Exception as branch_err:
                logger.error(f'[turnover] Error processing {branch_name}: {branch_err}')

        with open(STATE_FILE, 'w') as f:
            json.dump({
                'message_ids': [m['id'] for m in latest_per_branch.values()],
                'branches': branches_done,
                'rows': total_rows,
            }, f)
        update_sync_health('turnover', 'success',
                           f'{len(branches_done)} branches, {total_rows} rows', total_rows)
        logger.info(f'[turnover] email sync complete: {len(branches_done)} branches, {total_rows} rows')

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
               f'?$top=500&$orderby=receivedDateTime desc'
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

        # Safety guards: never wipe the snapshot unless we have a credible
        # replacement. Zero rows almost always means a parser/sheet mismatch —
        # keep the existing data. A >50% shrink is also suspicious; bail out
        # and flag it on the monitor rather than silently losing history.
        if not rows:
            update_sync_health('wip_accrual', 'error',
                               f'Email {msg["receivedDateTime"][:10]} parsed 0 rows — kept existing data',
                               0)
            return
        with connection.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM wip_accrual')
            existing = cur.fetchone()[0] or 0
        if existing > 100 and len(rows) < existing * 0.5:
            update_sync_health('wip_accrual', 'error',
                               f'Refused sync: {len(rows)} new rows vs {existing} existing (>50% shrink)',
                               existing)
            logger.error(f'[wip_accrual] refused: incoming {len(rows)} would shrink from {existing}')
            return

        with transaction.atomic():
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


IMPORT_OPS_COLUMNS = [
    # (db_name, pg_type) — order matches Excel columns C…EQ of the Shipment Profile sheet
    ('shipment_id', 'TEXT'), ('shipment_direction', 'TEXT'), ('shipment_report_date', 'TIMESTAMPTZ'),
    ('trans', 'TEXT'), ('customs_info', 'TEXT'), ('mode', 'TEXT'),
    ('origin', 'TEXT'), ('origin_country', 'TEXT'), ('destination', 'TEXT'), ('destination_country', 'TEXT'),
    ('consignor_code', 'TEXT'), ('consignor_name', 'TEXT'),
    ('consignee_code', 'TEXT'), ('consignee_name', 'TEXT'),
    ('house_ref', 'TEXT'), ('incoterm', 'TEXT'), ('additional_terms', 'TEXT'), ('ppd_ccx', 'TEXT'),
    ('goods_description', 'TEXT'),
    ('origin_etd', 'TIMESTAMPTZ'), ('destination_eta', 'TIMESTAMPTZ'),
    ('weight', 'NUMERIC'), ('weight_uq', 'TEXT'),
    ('volume', 'NUMERIC'), ('volume_uq', 'TEXT'),
    ('loading_meters', 'NUMERIC'),
    ('chargeable', 'NUMERIC'), ('chargeable_uq', 'TEXT'),
    ('inner_qty', 'NUMERIC'), ('inner_uq', 'TEXT'),
    ('outer_qty', 'NUMERIC'), ('outer_uq', 'TEXT'),
    ('added', 'TIMESTAMPTZ'),
    ('controlling_customer_code', 'TEXT'), ('controlling_customer_name', 'TEXT'),
    ('controlling_agent_code', 'TEXT'), ('controlling_agent_name', 'TEXT'),
    ('controlling_agent_address', 'TEXT'), ('controlling_agent_country', 'TEXT'),
    ('transport_job', 'TEXT'), ('brokerage_job', 'TEXT'),
    ('is_master_lead', 'TEXT'), ('master_lead_ref', 'TEXT'),
    ('import_broker_code', 'TEXT'), ('import_broker_name', 'TEXT'),
    ('export_broker_code', 'TEXT'), ('export_broker_name', 'TEXT'),
    ('job_branch', 'TEXT'), ('job_dept', 'TEXT'),
    ('local_client_code', 'TEXT'), ('local_client_name', 'TEXT'),
    ('job_sales_rep', 'TEXT'), ('job_operator', 'TEXT'), ('job_status', 'TEXT'),
    ('job_opened', 'DATE'),
    ('recognized_revenue', 'NUMERIC'), ('recognized_wip', 'NUMERIC'),
    ('total_recognized_income', 'NUMERIC'),
    ('recognized_cost', 'NUMERIC'), ('recognized_accrual', 'NUMERIC'),
    ('total_recognized_expense', 'NUMERIC'), ('job_profit', 'NUMERIC'),
    ('consol_id', 'TEXT'),
    ('first_load', 'TEXT'), ('last_discharge', 'TEXT'),
    ('etd_first_load', 'TIMESTAMPTZ'), ('eta_last_discharge', 'TIMESTAMPTZ'),
    ('master', 'TEXT'), ('vessel', 'TEXT'), ('flight_voyage', 'TEXT'),
    ('load_port', 'TEXT'), ('discharge_port', 'TEXT'),
    ('etd_load', 'TIMESTAMPTZ'), ('eta_discharge', 'TIMESTAMPTZ'),
    ('sending_agent_code', 'TEXT'), ('sending_agent_name', 'TEXT'),
    ('receiving_agent', 'TEXT'), ('receiving_agent_name', 'TEXT'),
    ('co_loaded_with', 'TEXT'), ('co_loader_name', 'TEXT'),
    ('carrier_code', 'TEXT'), ('carrier_name', 'TEXT'),
    ('teu', 'NUMERIC'), ('container_count', 'NUMERIC'),
    ('cntr_other', 'NUMERIC'),
    ('cntr_20f', 'NUMERIC'), ('cntr_20r', 'NUMERIC'), ('cntr_20h', 'NUMERIC'),
    ('cntr_40f', 'NUMERIC'), ('cntr_40r', 'NUMERIC'), ('cntr_40h', 'NUMERIC'),
    ('cntr_45f', 'NUMERIC'), ('cntr_gen', 'NUMERIC'),
    ('unrecognized_revenue', 'NUMERIC'), ('unrecognized_wip', 'NUMERIC'),
    ('unrecognized_cost', 'NUMERIC'), ('unrecognized_accrual', 'NUMERIC'),
    ('total_revenue', 'NUMERIC'), ('total_wip', 'NUMERIC'), ('total_income', 'NUMERIC'),
    ('service_level_code', 'TEXT'), ('shippers_reference', 'TEXT'),
    ('consignor_city', 'TEXT'), ('consignor_state', 'TEXT'), ('consignor_postcode', 'TEXT'),
    ('consignee_city', 'TEXT'), ('consignee_state', 'TEXT'), ('consignee_postcode', 'TEXT'),
    ('consol_atd', 'TIMESTAMPTZ'), ('consol_ata', 'TIMESTAMPTZ'),
    ('job_revenue_recognition_date', 'TIMESTAMPTZ'),
    ('direction', 'TEXT'),
    ('local_client_ar_group_code', 'TEXT'), ('local_client_ar_group_name', 'TEXT'),
    ('overseas_agent_code', 'TEXT'), ('overseas_agent_name', 'TEXT'),
    ('job_overseas_agent_ar_group_code', 'TEXT'), ('job_overseas_agent_ar_group_name', 'TEXT'),
    ('total_cost', 'NUMERIC'), ('total_accrual', 'NUMERIC'), ('total_expense', 'NUMERIC'),
]


def _rebuild_import_ops_table():
    """Drop+recreate import_ops with the full 121-col Shipment Profile schema."""
    from django.db import connection
    cols_ddl = ',\n    '.join(f'{n} {t}' for n, t in IMPORT_OPS_COLUMNS)
    ddl = f'''
    DROP TABLE IF EXISTS import_ops;
    CREATE TABLE import_ops (
        id BIGSERIAL PRIMARY KEY,
        {cols_ddl}
    );
    CREATE INDEX import_ops_shipment_id_idx ON import_ops (shipment_id);
    CREATE INDEX import_ops_job_branch_idx  ON import_ops (job_branch);
    CREATE INDEX import_ops_job_opened_idx  ON import_ops (job_opened);
    '''
    with connection.cursor() as cur:
        cur.execute(ddl)


def _coerce_io_value(pg_type, v):
    if v is None or (isinstance(v, str) and v.strip() == ''):
        return None
    if pg_type == 'NUMERIC':
        try:
            return float(str(v).replace(',', ''))
        except Exception:
            return None
    if pg_type == 'DATE':
        from datetime import datetime, date
        if isinstance(v, datetime):
            return v.date()
        if isinstance(v, date):
            return v
        s = str(v).strip()
        for fmt in ('%Y-%m-%d', '%Y-%m-%d %H:%M:%S', '%d/%m/%Y', '%m/%d/%Y'):
            try:
                return datetime.strptime(s[:19] if ' ' in s[:19] else s[:10], fmt).date()
            except Exception:
                continue
        return None
    if pg_type == 'TIMESTAMPTZ':
        from datetime import datetime
        if hasattr(v, 'year') and hasattr(v, 'month'):
            return v  # openpyxl already gave us a datetime
        s = str(v).strip()
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M:%S%z', '%Y-%m-%dT%H:%M:%S',
                    '%Y-%m-%d', '%d/%m/%Y %H:%M:%S', '%d/%m/%Y'):
            try:
                return datetime.strptime(s, fmt)
            except Exception:
                continue
        return None
    return str(v).strip()


def _run_import_ops_email_sync():
    """Fetch latest import ops email and upsert into import_ops (by shipment_id)."""
    import os, json, io, base64, requests
    from django.db import connection, transaction
    from psycopg2.extras import execute_values
    from .views import _get_graph_token
    import openpyxl

    try:
        token = _get_graph_token()
        if not token:
            raise RuntimeError('Graph token unavailable')
        headers = {'Authorization': f'Bearer {token}'}

        url = (f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages'
               f'?$top=500&$orderby=receivedDateTime desc'
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

        STATE_FILE = os.path.join(os.path.dirname(__file__), '..', 'import_ops_email_last.json')

        # Skip if we already processed the latest email
        last_id = None
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE) as f:
                    last_id = json.load(f).get('message_id')
            except Exception:
                pass

        if msgs[0]['id'] == last_id:
            with connection.cursor() as cur:
                cur.execute('SELECT COUNT(*) FROM import_ops')
                total = cur.fetchone()[0]
            update_sync_health('import_ops', 'success', f'Already up to date ({total} total)', total)
            return

        # Ensure unique index exists for upsert
        col_names = [n for n, _ in IMPORT_OPS_COLUMNS]
        with connection.cursor() as cur:
            cur.execute("""SELECT indexname FROM pg_indexes
                           WHERE tablename = 'import_ops' AND indexname = 'import_ops_shipment_id_uq'""")
            if not cur.fetchone():
                cur.execute("""DELETE FROM import_ops a USING import_ops b
                               WHERE a.id > b.id AND a.shipment_id = b.shipment_id""")
                cur.execute('CREATE UNIQUE INDEX import_ops_shipment_id_uq ON import_ops (shipment_id)')

        # Ensure table has the correct shape
        with connection.cursor() as cur:
            cur.execute("""SELECT column_name FROM information_schema.columns
                           WHERE table_name = 'import_ops' AND column_name <> 'id'
                           ORDER BY ordinal_position""")
            existing_cols = [r[0] for r in cur.fetchall()]
        if existing_cols != col_names:
            logger.warning(f'[import_ops] rebuilding table (schema drift): {len(existing_cols)} cols → {len(col_names)} cols')
            _rebuild_import_ops_table()

        # Process all unprocessed emails (oldest first so state file ends on the newest)
        to_process = []
        for m in msgs:
            if m['id'] == last_id:
                break
            to_process.append(m)
        to_process.reverse()

        total_upserted = 0
        insert_cols = ','.join(col_names)
        update_set = ','.join(f'{c} = EXCLUDED.{c}' for c in col_names if c != 'shipment_id')

        for msg in to_process:
            ar = requests.get(
                f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages/{msg["id"]}/attachments',
                headers=headers, timeout=60)
            ar.raise_for_status()
            xlsx = next((a for a in ar.json().get('value', [])
                         if a.get('name', '').lower().endswith(('.xlsx', '.xls'))), None)
            if not xlsx:
                continue

            fb = base64.b64decode(xlsx['contentBytes'])
            wb = openpyxl.load_workbook(io.BytesIO(fb), read_only=True, data_only=True)
            ws = wb['Shipment Profile']

            header_row = next(ws.iter_rows(min_row=15, max_row=15, values_only=True))
            if not header_row or len(header_row) < 3 or (header_row[2] or '').strip() != 'Shipment ID':
                wb.close()
                continue

            rows = []
            n_cols = len(IMPORT_OPS_COLUMNS)
            for row in ws.iter_rows(min_row=16, values_only=True):
                vals = list(row[2:2 + n_cols])
                if len(vals) < n_cols:
                    vals += [None] * (n_cols - len(vals))
                if not vals[0]:
                    continue
                coerced = tuple(_coerce_io_value(t, v) for (n, t), v in zip(IMPORT_OPS_COLUMNS, vals))
                rows.append(coerced)
            wb.close()

            if not rows:
                continue

            with transaction.atomic():
                with connection.cursor() as cur:
                    execute_values(cur,
                        f"""INSERT INTO import_ops ({insert_cols}) VALUES %s
                            ON CONFLICT (shipment_id) DO UPDATE SET {update_set}""",
                        rows)
            total_upserted += len(rows)

        # Save state as the newest email
        latest = to_process[-1]
        with open(STATE_FILE, 'w') as f:
            json.dump({'message_id': latest['id'], 'received': latest['receivedDateTime'], 'rows': total_upserted}, f)

        with connection.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM import_ops')
            total = cur.fetchone()[0]

        update_sync_health('import_ops', 'success',
                           f'Processed {len(to_process)} email(s): upserted {total_upserted} rows ({total} total)', total)

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
               f'?$top=500&$orderby=receivedDateTime desc'
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
                    # atomic(): rolls back the scoped DELETE if INSERT fails,
                    # so we can never lose creditor history on a bad batch.
                    with transaction.atomic():
                        with connection.cursor() as cur:
                            # Only delete periods covered by new data for this group
                            new_periods = set(r[2] for r in rs)
                            for p in new_periods:
                                cur.execute('DELETE FROM creditor_transactions WHERE creditor_group = %s AND period = %s', (group, p))
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
               f'?$top=500&$orderby=receivedDateTime desc'
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
            if not rows:
                continue

            # atomic(): DELETE rolls back if INSERT fails, so this department's
            # history is never lost on a bad write.
            with transaction.atomic():
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



def run_updown_trader_sync_job():
    """Monthly scheduled sync of Up-Down Trader data from SharePoint."""
    import tempfile
    import requests as req
    from django.db import connection

    try:
        from data.up_down_trader.load_data import (
            ensure_tables, upsert_customer_spend, upsert_customer_spend_operational,
            _extract_year, dedupe_operational, trim_to_source_year, rebuild_summary_view
        )
        from .views import _get_graph_token

        SITE = 'magnumopusconsultantspty352.sharepoint.com:/sites/DataPrime'
        FOLDER = 'Clients/ISCM/Up Down Trader Report/Shipment Data'

        token = _get_graph_token()
        if not token:
            logger.error("Up-Down Trader scheduled sync: Graph API token unavailable")
            update_sync_health('updown_trader', 'error', 'Graph API token unavailable')
            return

        headers = {'Authorization': f'Bearer {token}'}

        sr = req.get(f'https://graph.microsoft.com/v1.0/sites/{SITE}',
                     headers=headers, timeout=30)
        sr.raise_for_status()
        site_id = sr.json()['id']

        dr = req.get(f'https://graph.microsoft.com/v1.0/sites/{site_id}/drive',
                     headers=headers, timeout=30)
        dr.raise_for_status()
        drive_id = dr.json()['id']

        fr = req.get(
            f'https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{FOLDER}:/children',
            headers=headers, timeout=30)
        fr.raise_for_status()
        items = [i for i in fr.json().get('value', [])
                 if i.get('name', '').lower().endswith(('.xlsx', '.xls'))]

        if not items:
            logger.info("Up-Down Trader scheduled sync: No Excel files found")
            update_sync_health('updown_trader', 'success', 'No files found')
            return

        ensure_tables()
        cs_count = 0
        op_count = 0
        operational_truncated = False
        temp_files = []

        try:
            for item in items:
                fname = item['name']
                fyear = _extract_year(fname)
                if fyear and fyear < MIN_UPDOWN_YEAR:
                    logger.info(f"Up-Down Trader sync: skipping {fname} (year {fyear} < {MIN_UPDOWN_YEAR})")
                    continue
                logger.info(f"Up-Down Trader sync: processing {fname}")

                dl = req.get(
                    f'https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item["id"]}/content',
                    headers=headers, timeout=120)
                dl.raise_for_status()

                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
                tmp.write(dl.content)
                tmp.close()
                temp_files.append(tmp.name)

                import openpyxl
                wb = openpyxl.load_workbook(tmp.name, read_only=True, data_only=True)
                sheets = wb.sheetnames
                wb.close()

                has_financial = 'Financial Data ' in sheets or 'Financial Data' in sheets
                has_operational = 'Operational Data' in sheets or 'Shipment Profile' in sheets

                # Financial Data is no longer used. The report sources job income
                # and revenue from the shipment profile (operational) data only.
                if has_financial:
                    logger.info(f"Up-Down Trader sync: skipping financial data file {fname} (financial data no longer used)")

                if has_operational:
                    if not operational_truncated:
                        with connection.cursor() as cur:
                            cur.execute("TRUNCATE customer_spend_operational RESTART IDENTITY")
                        operational_truncated = True
                    count = upsert_customer_spend_operational(tmp.name, truncate=False)
                    op_count += count
                    # Tag the rows just inserted with the year of this file, so a
                    # year's column comes only from that year's file.
                    y = _extract_year(fname)
                    if y:
                        with connection.cursor() as cur:
                            cur.execute("UPDATE customer_spend_operational SET source_year=%s WHERE source_year IS NULL", [y])

            # Shipment files overlap, so the same shipment can be appended from
            # multiple files — remove the resulting duplicate rows before the
            # report view is built (otherwise every summed value is inflated).
            dedupe_operational()
            # Keep only rows whose recognition year matches their source file year,
            # so e.g. the 2025 file's 2024-recognised rows don't bleed into 2024.
            trim_to_source_year()
            rebuild_summary_view()

            # Save last sync timestamp
            sync_file = os.path.join(os.path.dirname(__file__), '..', 'updown_trader_last_sync.json')
            with open(sync_file, 'w') as f:
                json.dump({
                    'last_sync': datetime.now(ZoneInfo('Africa/Johannesburg')).isoformat(),
                    'records': cs_count + op_count
                }, f)

            msg = f'Synced {len(items)} files: {cs_count} spend + {op_count} operational records'
            logger.info(f"Up-Down Trader scheduled sync: {msg}")
            update_sync_health('updown_trader', 'success', msg, cs_count + op_count)

        finally:
            for path in temp_files:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    except Exception as e:
        logger.error(f"Up-Down Trader scheduled sync error: {e}")
        update_sync_health('updown_trader', 'error', str(e))


def run_sync_digest_job():
    """Run every report sync, then email the status digest (Mon/Wed/Fri)."""
    try:
        from dashboard.sync_digest import run_all_and_email
        run_all_and_email()
    except Exception as e:
        logger.exception('[sync_digest] failed')
        update_sync_health('sync_digest', 'error', str(e))


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

    # Daily recurring reports → create Planner tasks each morning at 05:00 UTC (07:00 SAST)
    scheduler.add_job(
        run_weekly_reports_job,
        trigger=CronTrigger(hour=5, minute=0),
        id='weekly_reports',
        name='Create today\'s recurring report tasks',
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
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

    # Up-Down Trader sync — 19th of every month at 02:00 UTC (04:00 SAST)
    scheduler.add_job(
        run_updown_trader_sync_job,
        trigger=CronTrigger(day=19, hour=2, minute=0),
        id='updown_trader_sync',
        name='Monthly Up-Down Trader SharePoint sync (19th)',
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )

    # Report sync digest — Mon/Wed/Fri at 04:00 UTC (06:00 SAST): run every
    # report sync, then email Ethan the one-table status summary.
    scheduler.add_job(
        run_sync_digest_job,
        trigger=CronTrigger(day_of_week='mon,wed,fri', hour=4, minute=0),
        id='sync_digest',
        name='Report sync digest email (Mon/Wed/Fri)',
        replace_existing=True,
        misfire_grace_time=3600,
        coalesce=True,
    )

    scheduler.start()
    logger.info("Scheduler started - All syncs email-driven every 3 hours")


def stop_scheduler():
    """Stop the background scheduler"""
    global scheduler
    if scheduler:
        scheduler.shutdown()
        scheduler = None
