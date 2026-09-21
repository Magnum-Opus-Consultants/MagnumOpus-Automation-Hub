"""Load the latest AWA Payables: Waiting email into the bravo_tran table.

Wipe-and-replace: every run DELETEs all rows, then loads the Waiting sheet
from the most recent matching email. Same pattern as wip_accrual / import_ops.

Usage:
    py manage.py load_bravo_tran_history            # replace table with latest email
    py manage.py load_bravo_tran_history --message-id <id>  # load a specific email
"""
import base64
import io
import re
from datetime import datetime

import openpyxl
import requests
from django.core.management.base import BaseCommand
from django.db import connection, transaction
from psycopg2.extras import execute_values

from dashboard.scheduler import EMAIL_MAILBOX


SUBJECT_RE = re.compile(r'Report:\s*(\d{4}-\d{2}-\d{2})', re.I)
SUBJECT_MATCH = 'awa payables: waiting'

CREATE_TABLE_SQL = '''
CREATE TABLE IF NOT EXISTS bravo_tran (
    id BIGSERIAL PRIMARY KEY,
    report_date DATE NOT NULL,
    request_sent_to TEXT DEFAULT '',
    email_subject TEXT DEFAULT '',
    vendor TEXT DEFAULT '',
    vendor_code TEXT DEFAULT '',
    invoice_number TEXT DEFAULT '',
    invoice_total NUMERIC,
    accrued_total NUMERIC,
    job_numbers TEXT DEFAULT '',
    charge_codes TEXT DEFAULT '',
    pending_charge_codes TEXT DEFAULT '',
    job_branches TEXT DEFAULT '',
    job_departments TEXT DEFAULT '',
    accrual_operator TEXT DEFAULT '',
    unassigned TEXT DEFAULT '',
    no_division TEXT DEFAULT '',
    invoice_date DATE,
    invoice_due_date DATE,
    invoice_received_on TIMESTAMPTZ,
    request_sent_on TIMESTAMPTZ,
    labels TEXT DEFAULT '',
    note TEXT DEFAULT '',
    link_to_item TEXT DEFAULT '',
    bt_invoice_id BIGINT
);
CREATE INDEX IF NOT EXISTS bravo_tran_report_date_idx ON bravo_tran (report_date);
CREATE INDEX IF NOT EXISTS bravo_tran_vendor_idx     ON bravo_tran (vendor);
CREATE INDEX IF NOT EXISTS bravo_tran_branch_idx     ON bravo_tran (job_branches);
'''


def _parse_date(v):
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v.date()
    if hasattr(v, 'year') and hasattr(v, 'month') and hasattr(v, 'day'):
        try:
            return v if not hasattr(v, 'hour') else v.date()
        except Exception:
            pass
    s = str(v).strip()
    for fmt in ('%Y-%m-%d', '%d/%m/%Y', '%m/%d/%Y', '%d-%m-%Y'):
        try:
            return datetime.strptime(s[:10], fmt).date()
        except Exception:
            continue
    return None


def _parse_dt(v):
    if v is None or v == '':
        return None
    if isinstance(v, datetime):
        return v
    s = str(v).strip()
    for fmt in ('%Y-%m-%d %H:%M:%S %z', '%Y-%m-%d %H:%M:%S', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%dT%H:%M:%SZ'):
        try:
            return datetime.strptime(s, fmt)
        except Exception:
            continue
    return None


def _num(v):
    if v is None or v == '':
        return None
    try:
        return float(str(v).replace(',', ''))
    except Exception:
        return None


def _str(v):
    return '' if v is None else str(v).strip()


def _parse_waiting_sheet(fbytes):
    """Parse the 'Waiting' sheet → list of tuples matching INSERT column order (minus report_date)."""
    wb = openpyxl.load_workbook(io.BytesIO(fbytes), read_only=True, data_only=True)
    if 'Waiting' not in wb.sheetnames:
        wb.close()
        return []
    ws = wb['Waiting']
    rows = list(ws.iter_rows(values_only=True))
    wb.close()
    if not rows:
        return []

    header = [_str(c) for c in rows[0]]
    idx = {name: i for i, name in enumerate(header)}

    def col(r, name):
        i = idx.get(name)
        if i is None or i >= len(r):
            return None
        return r[i]

    out = []
    for r in rows[1:]:
        if r is None or not any(cell is not None and str(cell).strip() for cell in r):
            continue
        if not (col(r, 'Vendor') or col(r, 'Invoice Number')):
            continue
        out.append((
            _str(col(r, 'Request Sent To')),
            _str(col(r, 'Email Subject')),
            _str(col(r, 'Vendor')),
            _str(col(r, 'Vendor Code')),
            _str(col(r, 'Invoice Number')),
            _num(col(r, 'Invoice Total')),
            _num(col(r, 'Accrued Total')),
            _str(col(r, 'Job Number(s)')),
            _str(col(r, 'Charge Code(s)')),
            _str(col(r, 'Pending Charge Code(s)')),
            _str(col(r, 'Job Branches')),
            _str(col(r, 'Job Departments')),
            _str(col(r, 'Accrual Operator')),
            _str(col(r, 'Unassigned')),
            _str(col(r, 'No division')),
            _parse_date(col(r, 'Invoice Date')),
            _parse_date(col(r, 'Invoice Due Date')),
            _parse_dt(col(r, 'Invoice Received On')),
            _parse_dt(col(r, 'Request Sent On')),
            _str(col(r, 'Labels')),
            _str(col(r, 'Note')),
            _str(col(r, 'Link to Item')),
            int(col(r, 'bt_invoice_id')) if col(r, 'bt_invoice_id') not in (None, '') else None,
        ))
    return out


INSERT_COLS = (
    'report_date, request_sent_to, email_subject, vendor, vendor_code, '
    'invoice_number, invoice_total, accrued_total, job_numbers, charge_codes, '
    'pending_charge_codes, job_branches, job_departments, accrual_operator, '
    'unassigned, no_division, invoice_date, invoice_due_date, '
    'invoice_received_on, request_sent_on, labels, note, link_to_item, bt_invoice_id'
)


class Command(BaseCommand):
    help = 'Replace the bravo_tran table with the latest AWA Payables: Waiting email.'

    def add_arguments(self, parser):
        parser.add_argument('--message-id', type=str, default='',
                            help='Load a specific Graph message id instead of the latest match')

    def handle(self, *args, **opts):
        # Ensure the table exists
        with connection.cursor() as cur:
            cur.execute(CREATE_TABLE_SQL)

        from dashboard.views import _get_graph_token
        tok = _get_graph_token()
        if not tok:
            self.stderr.write('Could not acquire Graph token')
            return
        headers = {'Authorization': f'Bearer {tok}'}

        # Find the latest matching email (unless a specific one was pinned)
        pinned = opts.get('message_id') or ''
        target = None
        if pinned:
            r = requests.get(
                f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages/{pinned}',
                headers=headers, timeout=30)
            r.raise_for_status()
            m = r.json()
            m_date = SUBJECT_RE.search(m.get('subject', ''))
            if not m_date:
                self.stderr.write('Pinned message subject has no report date')
                return
            target = {
                'id': m['id'],
                'subject': m['subject'],
                'report_date': datetime.strptime(m_date.group(1), '%Y-%m-%d').date(),
            }
        else:
            self.stdout.write('Looking up latest AWA Payables: Waiting email...')
            url = (f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages'
                   f'?$top=50&$orderby=receivedDateTime desc'
                   f'&$select=id,subject,receivedDateTime,hasAttachments')
            # Search through pages until we find one that matches
            while url and target is None:
                r = requests.get(url, headers=headers, timeout=30)
                r.raise_for_status()
                j = r.json()
                for m in j.get('value', []):
                    subj = (m.get('subject') or '').lower()
                    if m.get('hasAttachments') and SUBJECT_MATCH in subj:
                        m_date = SUBJECT_RE.search(m.get('subject', ''))
                        if m_date:
                            target = {
                                'id': m['id'],
                                'subject': m['subject'],
                                'report_date': datetime.strptime(m_date.group(1), '%Y-%m-%d').date(),
                            }
                            break
                url = j.get('@odata.nextLink')
            if target is None:
                self.stderr.write('No AWA Payables: Waiting email found')
                return

        self.stdout.write(f'Using: {target["subject"]}  (report_date {target["report_date"]})')

        # Fetch attachment
        ar = requests.get(
            f'https://graph.microsoft.com/v1.0/users/{EMAIL_MAILBOX}/messages/{target["id"]}/attachments',
            headers=headers, timeout=60)
        ar.raise_for_status()
        xl = next((a for a in ar.json().get('value', [])
                   if a.get('name', '').lower().endswith(('.xlsx', '.xls'))), None)
        if not xl:
            self.stderr.write('No xlsx attachment on the latest email')
            return

        fb = base64.b64decode(xl['contentBytes'])
        parsed = _parse_waiting_sheet(fb)
        if not parsed:
            self.stderr.write('Parsed 0 rows from Waiting sheet — refusing to wipe table')
            return

        # Shrink guard: if new count is <50% of current count with >100 existing,
        # refuse — looks like a bad parse.
        with connection.cursor() as cur:
            cur.execute('SELECT COUNT(*) FROM bravo_tran')
            existing = cur.fetchone()[0] or 0
        if existing > 100 and len(parsed) < existing * 0.5:
            self.stderr.write(
                f'Refusing: would shrink table from {existing} to {len(parsed)} (>50% loss). '
                'Inspect the email and re-run with --force if intentional.')
            return

        rows_with_date = [(target['report_date'],) + row for row in parsed]
        # Atomic DELETE + INSERT — wipe-and-replace for the whole table
        with transaction.atomic():
            with connection.cursor() as cur:
                cur.execute('DELETE FROM bravo_tran')
                execute_values(
                    cur,
                    f'INSERT INTO bravo_tran ({INSERT_COLS}) VALUES %s',
                    rows_with_date,
                )

        self.stdout.write(self.style.SUCCESS(
            f'Replaced bravo_tran with {len(parsed):,} rows from {target["report_date"]}.'
        ))
