"""Rebuild the client pack as Excel or PDF, styled like the original workbook.

Every colour, width and font size here was read back off
"E-Crop Stress Testing - Management Live Sheet - Consolidated v2.xlsx" so an
exported pack is indistinguishable from one edited by hand. Two things are
deliberately different:

* The dashboard figures are computed here rather than typed. The original
  carried COUNTA/COUNTIF formulas over the sheet ranges; we write the values,
  which is what those formulas would have evaluated to.
* Status colours are written as direct fills. The original applied them through
  15 conditional-formatting rules per sheet keyed on the English label, which
  breaks the moment a label is edited. The colours are identical.
"""
import io
import re

from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

# ── Palette, taken from the source workbook ──────────────────────────────────
NAVY = 'FF1F2A44'          # titles, table headers, tab colour
NAVY_DEEP = 'FF16213A'     # readiness % tile
SLATE = 'FF3D5A80'         # legend section headers, pending-retest tile
GREEN = 'FF1E7B34'         # PASS tile
AMBER = 'FF9C6500'         # requires-action tile
RED = 'FFC00000'           # outstanding tile
SUBTITLE = 'FF44546A'      # testing-window line
MUTED = 'FF666666'         # blurb
LEGEND_BAND = 'FFF4F6FA'   # legend column-header band
TAB_SHEET = 'FF00B050'     # the green tab the testing sheets carry

WHITE = 'FFFFFFFF'
BLACK = 'FF000000'

# Status fills, lifted from the conditional-formatting rules.
BUCKET_FILL = {
    'in_scope_change': ('FFFFFF00', BLACK),
    'change_request': ('FFED7D31', BLACK),
    'new_development': ('FFD9D9D9', BLACK),
    'developer_enhancement': ('FFA9D08E', BLACK),
}
DEV_FILL = {
    'in_progress': ('FFFFFF00', BLACK),
    'done_internally_tested': ('FF00B050', BLACK),
    'requires_clarification': ('FFED7D31', BLACK),
    'rectified_requires_testing': ('FF00B0F0', BLACK),
}
TESTED_FILL = {
    'tested': ('FF00B050', BLACK),
    'not_tested': ('FFFF0000', WHITE),
}
READINESS_FILL = {
    'pass': ('FF00B050', BLACK),
    'requires_action': ('FFED7D31', BLACK),
    'outstanding': ('FFFF0000', WHITE),
}

# Characters Excel refuses in a worksheet name.
SHEET_NAME_BAD = r'[\\/*?:\[\]]'

FONT = 'Calibri'
THIN = Side(style='thin', color='FFBFBFBF')
BORDER = Border(left=THIN, right=THIN, top=THIN, bottom=THIN)

SHEET_COLS = ['Issue', 'Description', 'Feedback Bucket',
              'Development Feedback', 'Client Test / Review Status',
              'Readiness Status', 'Client Feedback / Comments']
SHEET_WIDTHS = [32.0, 58.0, 16.9, 26.0, 22.0, 20.0, 60.0]

# The methodology text from the "Legend & Criteria" sheet. It is the same for
# every engagement - that is what makes the workbook a template - so it lives
# here rather than being stored per project.
LEGEND = [
    ('Feedback Buckets', 'bucket', [
        ('In Scope Change',
         'Meaning that the change picked up from testing and/or use case will be '
         'edited and finalised without billing and or scoping requirements. The '
         'hours and allocations will be resolved internally and will be included '
         'in the new APK.'),
        ('Change Request',
         'Are request that deviates from the current modus operandi and/or '
         'operational requirements. These changes are writen up towards defining '
         'the functionlity and be able to then allocate the hours and to bill for '
         'development'),
        ('New Development',
         'Are developments that are out of scope and needs to billed and scoped '
         'for accordingly.'),
        ('Developer Enhancements',
         'These are systems enhancements that we are responsible for in ensuring '
         'that the system works effectiveley based on the unique scenarios and '
         'use cases tested.'),
    ]),
    ('Development Feedback', 'dev', [
        ('In Progress',
         'The development team is busy developing these functions and/or '
         'enhancements'),
        ('Done & Internally Tested', 'Development is finalised and completed'),
        ('Requires Clarification',
         'Require further clarification from the inspector team and/or client '
         'personell to ensure that we adhere to requirements'),
        ('Rectified & Requires Testing',
         'Development Team has rectified the suggestions, comments and/or '
         'enhancements and are ready to be tested again'),
    ]),
    ('Readiness Checks', 'readiness', [
        ('PASS',
         'Functionality was tested and operates as intended. Where a change was '
         'required, it has been implemented, successfully retested and jointly '
         'verified by the client and the Development & Support Team.'),
        ('REQUIRES ACTION',
         'An item has been identified and work is in progress or implemented, but '
         'successful retesting and joint verification are still required. '
         'Development completion alone does not constitute a pass.'),
        ('OUTSTANDING',
         'Functionality was tested and an issue remains unresolved in the App or '
         'Web application. Further technical amendment is required to achieve the '
         'agreed behaviour. This does not mean untested.'),
    ]),
    ('Client Test / Review Status', 'tested', [
        ('Tested', 'Item has been tested by the inspection team.'),
        ('Not Tested', 'Item has not yet been tested.'),
    ]),
]

# Which fill table each legend block draws its swatch colours from.
_LEGEND_FILLS = {
    'bucket': (BUCKET_FILL, ['in_scope_change', 'change_request',
                             'new_development', 'developer_enhancement']),
    'dev': (DEV_FILL, ['in_progress', 'done_internally_tested',
                       'requires_clarification', 'rectified_requires_testing']),
    'readiness': (READINESS_FILL, ['pass', 'requires_action', 'outstanding']),
    'tested': (TESTED_FILL, ['tested', 'not_tested']),
}


def _fill(rgb):
    return PatternFill('solid', fgColor=rgb)


def _widths(ws, widths, start=1):
    for i, w in enumerate(widths, start=start):
        ws.column_dimensions[get_column_letter(i)].width = w


def current_of(item):
    """The pass that decides this item's verdict: its latest."""
    rounds = list(item.iterations.all())
    return rounds[-1] if rounds else None


def feedback_of(item):
    """Every pass's comments, stacked the way the source column did.

    The original sheets accumulated review notes in one cell across rounds
    ("Live review: PASS / Victoria: ... / Aina: PASS"), so retests append rather
    than replace. Passes are labelled once there is more than one, which is what
    makes a retest legible to the client.
    """
    rounds = [r for r in item.iterations.all()]
    notes = [(r, (r.client_feedback or '').strip()) for r in rounds]
    notes = [(r, t) for r, t in notes if t]
    if not notes:
        return ''
    if len(rounds) == 1:
        return notes[0][1]
    return '\n\n'.join(f'Test {r.number}: {t}' for r, t in notes)


def window_of(project):
    """The project's window, formatted the one way - see system_testing."""
    from .system_testing import window_label
    return window_label(project)


def version_chain(area):
    """"2.1.5 -> 2.1.6 -> 2.1.8" - every build released against this app.

    Rendered the way the source banner did, because the chain is the point:
    it says which builds the round was actually run against.
    """
    labels = [v.label for v in area.versions.all() if v.label]
    return ' -> '.join(labels)


def safe_filename(name, ext):
    safe = re.sub(r'[^A-Za-z0-9._-]+', '_', name).strip('_') or 'system-testing'
    return f'{safe}.{ext}'


# ══════════════════════════════════════════════════════════════════════════════
# Excel
# ══════════════════════════════════════════════════════════════════════════════

def _dashboard_sheet(ws, project, blocks, total):
    """The cover sheet: title band, then one metric strip per area."""
    ws.sheet_properties.tabColor = NAVY
    ws.sheet_view.showGridLines = False
    _widths(ws, [3.0, 26.0, 20.0, 20.0, 20.0, 20.0, 22.0, 3.0])

    ws.merge_cells('B2:G2')
    c = ws['B2']
    c.value = f'{project.name} - Client Review Pack'
    c.fill = _fill(NAVY)
    c.font = Font(name=FONT, bold=True, size=20, color=WHITE)
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[2].height = 25.9

    ws.merge_cells('B3:G3')
    line = '   |   '.join(x for x in (
        f'Testing Window: {window_of(project)}' if window_of(project) else '',
        project.version_label) if x)
    c = ws['B3']
    c.value = line
    c.font = Font(name=FONT, size=11, color=SUBTITLE)
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[3].height = 21.75

    ws.merge_cells('B4:G4')
    c = ws['B4']
    c.value = project.summary
    c.font = Font(name=FONT, size=9.5, color=MUTED)
    c.alignment = Alignment(horizontal='left', vertical='center', wrap_text=True)
    ws.row_dimensions[4].height = 27.75

    ws.freeze_panes = 'A5'

    row = 6
    tones = [NAVY, GREEN, AMBER, RED, SLATE, NAVY_DEEP]
    keys = ['total', 'pass', 'requires_action', 'outstanding',
            'pending_retest', 'readiness_pct']

    for label, roll in blocks:
        heads = [f'Total {label} Items', f'{label} PASS', f'{label} Requires Action',
                 f'{label} Outstanding', f'{label} Pending Retest',
                 f'{label} Readiness %']
        for i, (head, tone) in enumerate(zip(heads, tones)):
            c = ws.cell(row=row, column=2 + i, value=head)
            c.fill = _fill(tone)
            c.font = Font(name=FONT, bold=True, size=9.5, color=WHITE)
            c.alignment = Alignment(horizontal='center', vertical='center',
                                    wrap_text=True)
        ws.row_dimensions[row].height = 24.0
        row += 1

        for i, (key, tone) in enumerate(zip(keys, tones)):
            value = roll[key]
            c = ws.cell(row=row, column=2 + i,
                        value=(value / 100.0) if key == 'readiness_pct' else value)
            if key == 'readiness_pct':
                c.number_format = '0%'
            c.font = Font(name=FONT, bold=True, size=20, color=tone)
            c.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[row].height = 33.75
        row += 2

    # Readiness breakdown per area, mirroring the original's status tables.
    for label, roll in blocks:
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
        c = ws.cell(row=row, column=2, value=f'Readiness Status - {label}')
        c.fill = _fill(SLATE)
        c.font = Font(name=FONT, bold=True, size=12, color=WHITE)
        c.alignment = Alignment(horizontal='left', vertical='center')
        ws.row_dimensions[row].height = 19.5
        row += 1
        for head, col in (('Status', 2), ('Count', 3)):
            c = ws.cell(row=row, column=col, value=head)
            c.fill = _fill(LEGEND_BAND)
            c.font = Font(name=FONT, bold=True, size=10, color=NAVY)
            c.border = BORDER
        row += 1
        for name, key, table_key in (
                ('PASS', 'pass', 'pass'),
                ('REQUIRES ACTION', 'requires_action', 'requires_action'),
                ('OUTSTANDING', 'outstanding', 'outstanding'),
                ('Rectified & Requires Testing', 'pending_retest', None)):
            c = ws.cell(row=row, column=2, value=name)
            c.font = Font(name=FONT, bold=True, size=10, color=BLACK)
            c.border = BORDER
            if table_key:
                rgb, fg = READINESS_FILL[table_key]
                c.fill = _fill(rgb)
                c.font = Font(name=FONT, bold=True, size=10, color=fg)
            else:
                c.fill = _fill(DEV_FILL['rectified_requires_testing'][0])
            v = ws.cell(row=row, column=3, value=roll[key])
            v.font = Font(name=FONT, size=10)
            v.alignment = Alignment(horizontal='center')
            v.border = BORDER
            row += 1
        row += 1

    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=7)
    c = ws.cell(row=row, column=2,
                value=f'All areas: {total["total"]} items  ·  {total["pass"]} PASS  '
                      f'·  {total["readiness_pct"]}% readiness')
    c.fill = _fill(NAVY)
    c.font = Font(name=FONT, bold=True, size=11, color=WHITE)
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[row].height = 21.75


def _area_sheet(ws, area, version, rows):
    """One release's sheet: the issues live against that build."""
    ws.sheet_properties.tabColor = TAB_SHEET
    ws.sheet_view.showGridLines = False
    _widths(ws, SHEET_WIDTHS)

    title = f'{area.name} {version.label} - Testing Feedback'
    chain = version_chain(area)
    if chain:
        title += f'   |   builds: {chain}'
    ws.merge_cells('A1:H1')
    c = ws['A1']
    c.value = title
    c.fill = _fill(NAVY)
    c.font = Font(name=FONT, bold=True, size=14, color=WHITE)
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[1].height = 18.75

    for i, head in enumerate(SHEET_COLS, start=1):
        c = ws.cell(row=2, column=i, value=head)
        c.fill = _fill(NAVY)
        c.font = Font(name=FONT, bold=True, size=10.5, color=WHITE)
        c.alignment = Alignment(horizontal='center', vertical='center',
                                wrap_text=True)
        c.border = BORDER
    ws.row_dimensions[2].height = 28.5
    ws.freeze_panes = 'A3'

    row = 3
    for cur in rows:
        it = cur.item
        values = [it.issue, it.description, it.get_bucket_display(),
                  cur.get_dev_status_display(),
                  cur.get_tested_display(),
                  cur.get_readiness_display(),
                  cur.client_feedback]
        fills = [None, None,
                 BUCKET_FILL.get(it.bucket),
                 DEV_FILL.get(cur.dev_status),
                 TESTED_FILL.get(cur.tested),
                 READINESS_FILL.get(cur.readiness), None]
        for i, (value, fill) in enumerate(zip(values, fills), start=1):
            c = ws.cell(row=row, column=i, value=value)
            c.border = BORDER
            # The status columns read as labels, so they centre; the prose
            # columns read as text and stay left.
            centred = i in (3, 4, 5, 6)
            c.alignment = Alignment(
                horizontal='center' if centred else 'left',
                vertical='center', wrap_text=True)
            if fill:
                rgb, fg = fill
                c.fill = _fill(rgb)
                c.font = Font(name=FONT, bold=True, size=11, color=fg)
            else:
                c.font = Font(name=FONT, size=11, bold=(i == 1))
        # Roughly what the source used: tall enough for the wrapped description.
        longest = max(len(it.description or ''), len(cur.client_feedback or ''))
        ws.row_dimensions[row].height = min(150, max(30, 15 * (1 + longest // 55)))
        row += 1


def _legend_sheet(ws):
    ws.sheet_properties.tabColor = SLATE
    ws.sheet_view.showGridLines = False
    _widths(ws, [3.0, 30.0, 95.0, 3.0])

    ws.merge_cells('B2:C2')
    c = ws['B2']
    c.value = 'Testing Criteria & Status Definitions'
    c.fill = _fill(NAVY)
    c.font = Font(name=FONT, bold=True, size=18, color=WHITE)
    c.alignment = Alignment(horizontal='left', vertical='center')
    ws.row_dimensions[2].height = 30

    row = 4
    for heading, kind, entries in LEGEND:
        ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=3)
        c = ws.cell(row=row, column=2, value=heading)
        c.fill = _fill(SLATE)
        c.font = Font(name=FONT, bold=True, size=12, color=WHITE)
        c.alignment = Alignment(horizontal='left', vertical='center')
        ws.row_dimensions[row].height = 20
        row += 1

        for head, col in (('Status / Category', 2), ('Criteria / Definition', 3)):
            c = ws.cell(row=row, column=col, value=head)
            c.fill = _fill(LEGEND_BAND)
            c.font = Font(name=FONT, bold=True, size=10, color=NAVY)
            c.border = BORDER
        row += 1

        table, keys = _LEGEND_FILLS[kind]
        for (label, definition), key in zip(entries, keys):
            rgb, fg = table[key]
            c = ws.cell(row=row, column=2, value=label)
            c.fill = _fill(rgb)
            c.font = Font(name=FONT, bold=True, size=10, color=fg)
            c.alignment = Alignment(vertical='center', wrap_text=True)
            c.border = BORDER
            d = ws.cell(row=row, column=3, value=definition)
            d.font = Font(name=FONT, size=10)
            d.alignment = Alignment(vertical='center', wrap_text=True)
            d.border = BORDER
            ws.row_dimensions[row].height = max(30, 14 * (1 + len(definition) // 95))
            row += 1
        row += 1


def _notes_sheet(ws, notes):
    ws.sheet_view.showGridLines = False
    _widths(ws, [5.1, 9.1, 97.4])
    c = ws.cell(row=2, column=2, value='Nr')
    c.font = Font(name=FONT, bold=True, size=11)
    c = ws.cell(row=2, column=3, value='Enhancements')
    c.font = Font(name=FONT, bold=True, size=11)
    for i, n in enumerate(notes, start=1):
        ws.cell(row=2 + i, column=2, value=i).font = Font(name=FONT, size=11)
        c = ws.cell(row=2 + i, column=3, value=n.text)
        c.font = Font(name=FONT, size=11)
        c.alignment = Alignment(vertical='center', wrap_text=True)
        if n.is_done:
            c.font = Font(name=FONT, size=11, strike=True, color=MUTED)


def build_workbook(project, areas, notes, rollup_fn, total_fn):
    """Return the pack as .xlsx bytes, one sheet per release."""
    import openpyxl

    wb = openpyxl.Workbook()
    blocks, rolls, prepared = [], [], []
    for a in areas:
        versions = list(a.versions.all())
        for v in versions:
            rows = sorted(v.iterations.select_related("item"),
                          key=lambda r: (r.item.order, r.item_id))
            prepared.append((a, v, rows))
        # The dashboard reports the build the app is on now, not its history.
        latest = versions[-1] if versions else None
        roll = rollup_fn(latest.iterations.all()) if latest else rollup_fn([])
        rolls.append(roll)
        blocks.append((a.name, roll))

    _dashboard_sheet(wb.active, project, blocks, total_fn(rolls))
    wb.active.title = 'Dashboard'

    used = {'Dashboard'}
    for a, v, rows in prepared:
        # One sheet per release, so each build's evidence stays on its own
        # page. Excel caps sheet names at 31 chars and forbids duplicates.
        raw = f"{a.name} {v.label}"
        base = re.sub(SHEET_NAME_BAD, "-", raw)[:31] or "Area"
        title, n = base, 2
        while title in used:
            title = f'{base[:28]}-{n}'
            n += 1
        used.add(title)
        _area_sheet(wb.create_sheet(title=title), a, v, rows)

    _legend_sheet(wb.create_sheet(title='Legend & Criteria'))
    if notes:
        _notes_sheet(wb.create_sheet(title='Notes'), notes)

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return buf.read()


# ══════════════════════════════════════════════════════════════════════════════
# PDF
# ══════════════════════════════════════════════════════════════════════════════

def _rgb(hex8):
    """'FF1F2A44' -> (31, 42, 68)."""
    h = hex8[-6:]
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


# The core PDF fonts are latin-1 only, and the packs are full of pasted Word
# punctuation - en dashes, curly quotes, arrows between version numbers. Rather
# than bundle a Unicode TTF for characters that carry no meaning here, fold them
# to their ASCII equivalents; anything still unmappable is dropped rather than
# raising and losing the whole export.
_ASCII = {
    '–': '-', '—': '-', '‒': '-', '−': '-',
    '‘': "'", '’': "'", '‚': ',',
    '“': '"', '”': '"', '„': '"',
    '…': '...', '•': '-', '·': '-',
    '→': '->', '←': '<-', '⇒': '=>',
    ' ': ' ', '​': '', '﻿': '',
    '✓': 'v', '✔': 'v', '✗': 'x', '✘': 'x',
    '®': '(R)', '™': '(TM)', '©': '(C)',
}


def _ascii(value):
    text = '' if value is None else str(value)
    for bad, good in _ASCII.items():
        if bad in text:
            text = text.replace(bad, good)
    return text.encode('latin-1', 'replace').decode('latin-1')


def build_pdf(project, areas, notes, rollup_fn, total_fn):
    """Return the same pack as PDF bytes, landscape to fit the eight columns."""
    from fpdf import FPDF

    pdf = FPDF(orientation='L', unit='mm', format='A4')
    pdf.set_auto_page_break(auto=True, margin=12)
    pdf.set_title(_ascii(f'{project.name} - Client Review Pack'))

    prepared, rolls = [], []
    for a in areas:
        versions = list(a.versions.all())
        for v in versions:
            rows = sorted(v.iterations.select_related('item'),
                          key=lambda r: (r.item.order, r.item_id))
            prepared.append((a, v, rows))
        latest = versions[-1] if versions else None
        rolls.append(rollup_fn(latest.iterations.all()) if latest else rollup_fn([]))
    total = total_fn(rolls)

    # ── Cover ────────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(*_rgb(NAVY))
    pdf.rect(0, 0, 297, 26, style='F')
    pdf.set_xy(12, 7)
    pdf.set_font('Helvetica', 'B', 20)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 10, _ascii(f'{project.name} - Client Review Pack'))

    pdf.set_xy(12, 32)
    pdf.set_font('Helvetica', '', 10)
    pdf.set_text_color(*_rgb(SUBTITLE))
    line = '   |   '.join(x for x in (
        f'Testing Window: {window_of(project)}' if window_of(project) else '',
        project.version_label, project.client) if x)
    if line:
        pdf.cell(0, 6, _ascii(line), new_x='LMARGIN', new_y='NEXT')
    if project.summary:
        pdf.set_font('Helvetica', '', 9)
        pdf.set_text_color(*_rgb(MUTED))
        pdf.set_x(12)
        pdf.multi_cell(273, 5, _ascii(project.summary))

    # Metric strips, one per area.
    tones = [NAVY, GREEN, AMBER, RED, SLATE, NAVY_DEEP]
    keys = ['total', 'pass', 'requires_action', 'outstanding',
            'pending_retest', 'readiness_pct']
    y = pdf.get_y() + 6
    for a, roll in zip(areas, rolls):
        pdf.set_xy(12, y)
        pdf.set_font('Helvetica', 'B', 11)
        pdf.set_text_color(*_rgb(NAVY))
        chain = version_chain(a)
        head = a.name + (f'   ({chain})' if chain else '')
        pdf.cell(0, 6, _ascii(head), new_x='LMARGIN', new_y='NEXT')
        y = pdf.get_y()

        labels = ['Total Items', 'PASS', 'Requires Action', 'Outstanding',
                  'Pending Retest', 'Readiness %']
        w = 45.0
        for i, (label, key, tone) in enumerate(zip(labels, keys, tones)):
            x = 12 + i * w
            pdf.set_fill_color(*_rgb(tone))
            pdf.rect(x, y, w - 2, 8, style='F')
            pdf.set_xy(x, y)
            pdf.set_font('Helvetica', 'B', 7.5)
            pdf.set_text_color(255, 255, 255)
            pdf.cell(w - 2, 8, _ascii(label), align='C')

            value = f'{roll[key]}%' if key == 'readiness_pct' else str(roll[key])
            pdf.set_xy(x, y + 8)
            pdf.set_font('Helvetica', 'B', 16)
            pdf.set_text_color(*_rgb(tone))
            pdf.cell(w - 2, 12, _ascii(value), align='C')
        y += 26

    pdf.set_xy(12, y)
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(*_rgb(NAVY))
    pdf.cell(0, 6, _ascii(f'All areas: {total["total"]} items  -  '
                          f'{total["pass"]} PASS  -  '
                          f'{total["readiness_pct"]}% readiness'))

    # ── One page-run per area ────────────────────────────────────────────────
    widths = [52, 78, 26, 34, 24, 28, 31]
    for a, v, rows in prepared:
        pdf.add_page()
        pdf.set_fill_color(*_rgb(NAVY))
        pdf.rect(0, 0, 297, 14, style='F')
        pdf.set_xy(12, 3)
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(255, 255, 255)
        chain = version_chain(a)
        title = f'{a.name} {v.label}' + (f'   |   builds: {chain}' if chain else '')
        pdf.cell(0, 8, _ascii(title))
        pdf.set_xy(12, 20)

        _pdf_header(pdf, widths)
        for r in rows:
            _pdf_row(pdf, widths, r)

    # ── Legend ───────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_fill_color(*_rgb(NAVY))
    pdf.rect(0, 0, 297, 14, style='F')
    pdf.set_xy(12, 3)
    pdf.set_font('Helvetica', 'B', 12)
    pdf.set_text_color(255, 255, 255)
    pdf.cell(0, 8, 'Testing Criteria & Status Definitions')
    pdf.set_xy(12, 20)

    for heading, kind, entries in LEGEND:
        if pdf.get_y() > 165:
            pdf.add_page()
            pdf.set_xy(12, 20)
        pdf.set_x(12)
        pdf.set_fill_color(*_rgb(SLATE))
        pdf.set_text_color(255, 255, 255)
        pdf.set_font('Helvetica', 'B', 10)
        pdf.cell(273, 7, _ascii(f'  {heading}'), fill=True, new_x='LMARGIN', new_y='NEXT')

        table, keys_ = _LEGEND_FILLS[kind]
        for (label, definition), key in zip(entries, keys_):
            rgb, fg = table[key]
            top = pdf.get_y()
            pdf.set_x(12)
            pdf.set_font('Helvetica', '', 8.5)
            pdf.set_text_color(0, 0, 0)
            # Measure the definition first so the swatch matches its height.
            lines = pdf.multi_cell(213, 4.6, _ascii(definition), dry_run=True,
                                   output='LINES', split_only=False)
            height = max(8.0, 4.6 * (len(lines) if lines else 1) + 2)

            pdf.set_fill_color(*_rgb(rgb))
            pdf.set_text_color(*(255, 255, 255) if fg == WHITE else (0, 0, 0))
            pdf.set_font('Helvetica', 'B', 8.5)
            pdf.set_xy(12, top)
            pdf.multi_cell(60, height, _ascii(label), border=1, fill=True, align='L',
                           new_x='RIGHT', new_y='TOP', max_line_height=4.6)

            pdf.set_xy(72, top)
            pdf.set_font('Helvetica', '', 8.5)
            pdf.set_text_color(0, 0, 0)
            pdf.multi_cell(213, height, _ascii(definition), border=1, align='L',
                           new_x='LMARGIN', new_y='NEXT', max_line_height=4.6)
        pdf.ln(3)

    # ── Notes ────────────────────────────────────────────────────────────────
    if notes:
        pdf.add_page()
        pdf.set_fill_color(*_rgb(NAVY))
        pdf.rect(0, 0, 297, 14, style='F')
        pdf.set_xy(12, 3)
        pdf.set_font('Helvetica', 'B', 12)
        pdf.set_text_color(255, 255, 255)
        pdf.cell(0, 8, 'Enhancements')
        pdf.set_xy(12, 20)
        pdf.set_text_color(0, 0, 0)
        for i, n in enumerate(notes, start=1):
            pdf.set_x(12)
            pdf.set_font('Helvetica', 'B', 9)
            pdf.cell(10, 6, str(i))
            pdf.set_font('Helvetica', '', 9)
            pdf.multi_cell(263, 6, _ascii(n.text), new_x='LMARGIN', new_y='NEXT')

    out = pdf.output()
    return bytes(out)


def _pdf_header(pdf, widths):
    pdf.set_fill_color(*_rgb(NAVY))
    pdf.set_text_color(255, 255, 255)
    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_x(12)
    for w, head in zip(widths, SHEET_COLS):
        pdf.cell(w, 9, _ascii(head), border=0, fill=True, align='C')
    pdf.ln(9)


def _pdf_row(pdf, widths, cur):
    """One pass, with the status cells filled the same colours as the sheet."""
    it = cur.item
    values = [it.issue, it.description, it.get_bucket_display(),
              cur.get_dev_status_display(),
              cur.get_tested_display(),
              cur.get_readiness_display(),
              cur.client_feedback]
    fills = [None, None,
             BUCKET_FILL.get(it.bucket),
             DEV_FILL.get(cur.dev_status),
             TESTED_FILL.get(cur.tested),
             READINESS_FILL.get(cur.readiness), None]

    pdf.set_font('Helvetica', '', 7.5)
    # Height is driven by the tallest wrapped cell in the row.
    height = 5.0
    for w, value in zip(widths, values):
        lines = pdf.multi_cell(w, 3.6, _ascii(value), dry_run=True,
                               output='LINES', split_only=False)
        height = max(height, 3.6 * (len(lines) if lines else 1) + 1.6)
    height = min(height, 60)

    if pdf.get_y() + height > 190:
        pdf.add_page()
        pdf.set_xy(12, 20)
        _pdf_header(pdf, widths)

    top = pdf.get_y()
    x = 12
    for w, value, fill in zip(widths, values, fills):
        pdf.set_xy(x, top)
        if fill:
            rgb, fg = fill
            pdf.set_fill_color(*_rgb(rgb))
            pdf.set_text_color(*((255, 255, 255) if fg == WHITE else (0, 0, 0)))
            pdf.set_font('Helvetica', 'B', 7.5)
            pdf.multi_cell(w, height, _ascii(value), border=1, fill=True,
                           align='C', new_x='RIGHT', new_y='TOP',
                           max_line_height=3.6)
        else:
            pdf.set_text_color(0, 0, 0)
            pdf.set_font('Helvetica', '', 7.5)
            pdf.multi_cell(w, height, _ascii(value), border=1, align='L',
                           new_x='RIGHT', new_y='TOP', max_line_height=3.6)
        x += w
    pdf.set_xy(12, top + height)
