"""Generate a formatted Up-Down Trader report Excel from customer_spend_summary.

Produces a styled .xlsx replica of the report table (no pivot charts):
 - dark-blue header row, white bold text, wrapped
 - narrow, light-green, smaller-font columns for the count/volume metrics
   (Job No, Chg KG, Chg M3, TEU) so they read as secondary to the $ columns
 - frozen header row + first two columns (ORG CODE / CONTROLLING AGENT)

Run from the automations/ directory:
    python data/up_down_trader/build_report.py
The file is written next to this script as 'Up Down Traders Report - Generated.xlsx'.
"""
import os
import sys

os.environ['DJANGO_SETTINGS_MODULE'] = 'automations.settings'
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
import django
django.setup()

from django.db import connection
import openpyxl
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.table import Table, TableStyleInfo

OUT = os.path.join(os.path.dirname(__file__), 'Up Down Traders Report - Generated.xlsx')

# Table starts at E3 (like the original) — leaves columns A-D and rows 1-2 as margin
START_ROW = 3
START_COL = 5   # column E
TABLE_STYLE = 'TableStyleMedium1'   # same block/banded style as the original

# SharePoint target (separate filename so it never clobbers the existing report)
SP_SITE = 'magnumopusconsultantspty352.sharepoint.com:/sites/DataPrime'
SP_FOLDER = 'Clients/ISCM/Up Down Trader Report'
SP_NAME = 'Up Down Traders Report - Generated.xlsx'

HEADER_FILL = PatternFill('solid', fgColor='054B70')   # MOC dark blue
HEADER_FONT = Font(bold=True, color='FFFFFF', size=11)
VOL_FILL = PatternFill('solid', fgColor='E2EFDA')      # light green
VOL_FONT = Font(size=9, color='3C3C3C')

# Count/volume metric columns get the smaller, coloured treatment
VOL_KEYS = ('JOB NO', 'CHG KG', 'CHG M3', 'TEU', 'CUSTOMERS')


def _is_vol(header):
    h = (header or '').upper()
    return any(k in h for k in VOL_KEYS)


def generate(out_path=OUT):
    with connection.cursor() as cur:
        cur.execute('SELECT * FROM customer_spend_summary')
        headers = [d[0] for d in cur.description]
        rows = cur.fetchall()

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = 'Master'

    ncols, nrows = len(headers), len(rows)

    # Write the table offset to E3 (blank A-D columns and rows 1-2 as margin)
    for i, h in enumerate(headers):
        ws.cell(row=START_ROW, column=START_COL + i, value=h)
    for r, row in enumerate(rows):
        for i, val in enumerate(row):
            ws.cell(row=START_ROW + 1 + r, column=START_COL + i, value=val)

    first_col = get_column_letter(START_COL)
    last_col = get_column_letter(START_COL + ncols - 1)
    last_row = START_ROW + nrows
    ref = f"{first_col}{START_ROW}:{last_col}{last_row}"

    # Excel Table: the bordered "block" look, banded rows and filter dropdowns,
    # same style as the original report.
    tab = Table(displayName="UpDownTraders", ref=ref)
    tab.tableStyleInfo = TableStyleInfo(
        name=TABLE_STYLE, showRowStripes=True, showColumnStripes=False,
        showFirstColumn=False, showLastColumn=False)
    ws.add_table(tab)

    # Auto-fit every column to its content so nothing is squished ("completely
    # open"); light-green overlay on the count/volume columns.
    MAX_WIDTH = 50
    for i, h in enumerate(headers):
        c = START_COL + i
        col = get_column_letter(c)
        hu = str(h).upper()
        if '%' in str(h):
            nfmt = '0.0"%"'                 # margin: value already on 0-100 scale
        elif 'REV' in hu or 'PROFIT' in hu:
            nfmt = '$#,##0'                 # currency columns (now numeric)
        else:
            nfmt = None
        width = len(str(h))
        for row in rows:
            v = row[i]
            if v is not None and len(str(v)) > width:
                width = len(str(v))
        ws.column_dimensions[col].width = min(width + 3, MAX_WIDTH)
        for r in range(START_ROW + 1, last_row + 1):
            cell = ws.cell(row=r, column=c)
            if _is_vol(h):
                cell.fill = VOL_FILL
            if nfmt:
                cell.number_format = nfmt

    # Freeze header row + first two table columns (ORG CODE / CONTROLLING AGENT)
    ws.freeze_panes = f"{get_column_letter(START_COL + 2)}{START_ROW + 1}"

    wb.save(out_path)
    print(f"Generated {out_path}  ({nrows} rows, {ncols} columns)")
    return out_path


def upload(path, name=SP_NAME):
    """Upload the generated file to the SharePoint Up Down Trader Report folder."""
    import requests
    from urllib.parse import quote
    from dashboard.views import _get_graph_token

    token = _get_graph_token()
    if not token:
        print("No Graph token available — skipping SharePoint upload")
        return
    h = {'Authorization': f'Bearer {token}'}
    sid = requests.get(f'https://graph.microsoft.com/v1.0/sites/{SP_SITE}', headers=h, timeout=30).json()['id']
    did = requests.get(f'https://graph.microsoft.com/v1.0/sites/{sid}/drive', headers=h, timeout=30).json()['id']
    with open(path, 'rb') as f:
        data = f.read()
    target = quote(f'{SP_FOLDER}/{name}')
    url = f'https://graph.microsoft.com/v1.0/drives/{did}/root:/{target}:/content'
    r = requests.put(url, headers={**h, 'Content-Type': 'application/octet-stream'},
                     data=data, timeout=120)
    if r.status_code in (200, 201):
        print("Uploaded to SharePoint:", r.json().get('webUrl'))
    else:
        print("Upload failed:", r.status_code, r.text[:300])


if __name__ == '__main__':
    p = generate()
    upload(p)

