"""The Up Management Report as a PDF, copying the V3 Word document exactly.

The measurements are not guesses - they were read out of the .docx itself:

    page          US Letter, 216 x 279 mm  (not A4, which the first pass used)
    table width   10774 twips = 190 mm, so 13 mm side margins
    title block   2122 / 8652 twips  = 37.4 / 152.6 mm
    client card   2411 / 3254 / 2693 / 2410 twips = 42.5 / 57.4 / 47.5 / 42.5 mm
    body font     Calibri, 12 pt default
    theme         accent1 #4472C4, dk2 #44546A, lt2 #E7E6E6
    borders       TableGrid - a thin single rule on every edge
    highlight     yellow, on the template's instruction lines

Calibri belongs to Microsoft and cannot be shipped to a Linux server, so this
is set in Carlito - the metrically identical OFL clone bundled beside this
file. Identical widths mean identical line breaks and the same page count.

Every figure comes from up_report.build(), which computes all of them. Nothing
in this document is typed by anyone.
"""
import logging
import os
from datetime import timedelta

from fpdf import FPDF
from fpdf.enums import Align
from fpdf.fonts import FontFace

from . import up_report
from .management_report import week_start_for
from .up_report import PRESSURE_SCALE

logger = logging.getLogger(__name__)

ASSETS = os.path.join(os.path.dirname(__file__), 'assets', 'report')
LOGO = os.path.join(ASSETS, 'sentinel-logo.png')

# Straight from the document's theme.
ACCENT = (68, 114, 196)      # accent1 #4472C4
DARK = (68, 84, 106)         # dk2     #44546A
FILL = (231, 230, 230)       # lt2     #E7E6E6
INK = (0, 0, 0)
MUTED = (89, 89, 89)
BORDER = (128, 128, 128)     # TableGrid's default rule
HIGHLIGHT = (255, 255, 0)

# The twip values straight from the document. Passed as ratios rather than
# converted to millimetres: Letter is 215.9 mm wide, so 13 mm margins leave
# 189.9 mm of usable width against the document's nominal 190, and asking for
# 190 exactly is rejected. Ratios are scaled to fit and stay faithful.
TITLE_COLS = (2122, 8652)
CARD_COLS = (2411, 3254, 2693, 2410)
SIDE_MARGIN = 13.0

SEVERITY_FILL = {
    'critical': (248, 203, 203),
    'high': (252, 224, 224),
    'medium': (255, 242, 204),
    'low': (255, 255, 255),
}


class UpReportPDF(FPDF):
    """US Letter, Carlito, laid out as the Word original."""

    def __init__(self, week_ending='', version='V3'):
        super().__init__(orientation='P', unit='mm', format='Letter')
        self.week_ending = week_ending
        self.version = version
        self.set_auto_page_break(auto=True, margin=18)
        self.set_margins(SIDE_MARGIN, 16, SIDE_MARGIN)
        self._install_fonts()
        self.set_draw_color(*BORDER)
        self.set_line_width(0.2)

    def _install_fonts(self):
        """Carlito in place of Calibri - identical metrics, free to ship."""
        self.body = 'Carlito'
        for style, filename in (('', 'Carlito-Regular.ttf'),
                                ('B', 'Carlito-Bold.ttf'),
                                ('I', 'Carlito-Italic.ttf'),
                                ('BI', 'Carlito-BoldItalic.ttf')):
            path = os.path.join(ASSETS, filename)
            if os.path.isfile(path):
                self.add_font('Carlito', style, path)
            else:
                # Falls back rather than failing: a report set in Helvetica is
                # still a report, and the alternative is no report at all.
                logger.warning('[up-report] %s missing; using Helvetica',
                               filename)
                self.body = 'Helvetica'
                return

    def header(self):
        if self.page_no() == 1:
            return
        self.set_font(self.body, 'I', 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, 'Sentinel Weekly Up Management Report  -  week ending '
                        f'{self.week_ending}', align='L')
        self.ln(7)
        self.set_text_color(*INK)

    def footer(self):
        self.set_y(-15)
        self.set_font(self.body, '', 8)
        self.set_text_color(*MUTED)
        self.cell(0, 5, f'{self.version}    Page {self.page_no()} of {{nb}}',
                  align='C')
        self.set_text_color(*INK)


def _n(v):
    return '' if v in (None, '') else str(v)


def _head_face():
    return FontFace(emphasis='BOLD', fill_color=FILL)


def _section(pdf, number, title):
    if pdf.get_y() > pdf.h - 55:
        pdf.add_page()
    pdf.ln(4)
    pdf.set_font(pdf.body, 'B', 14)
    pdf.set_text_color(*DARK)
    pdf.cell(0, 8, f'{number}. {title}')
    pdf.ln(9)
    pdf.set_text_color(*INK)


def _instruction(pdf, text):
    """The template's yellow-highlighted guidance lines."""
    pdf.set_font(pdf.body, '', 9)
    pdf.set_fill_color(*HIGHLIGHT)
    pdf.set_text_color(*INK)
    pdf.multi_cell(0, 4.6, text, fill=True, new_x='LMARGIN', new_y='NEXT')
    # Back to white at once: the fill colour persists on the document, and
    # leaving it yellow highlighted every table cell that followed.
    pdf.set_fill_color(255, 255, 255)
    pdf.ln(1.5)


def _note(pdf, text):
    pdf.set_font(pdf.body, 'I', 8)
    pdf.set_text_color(*MUTED)
    pdf.multi_cell(0, 4, text, new_x='LMARGIN', new_y='NEXT')
    pdf.set_text_color(*INK)
    pdf.ln(1.5)


def _title_block(pdf, header):
    if os.path.isfile(LOGO):
        # 775 x 240 as generated by assets/report/make_sentinel_logo.py;
        # 52 mm wide keeps the proportions.
        pdf.image(LOGO, x=SIDE_MARGIN, y=12, w=52)
        pdf.set_y(12 + 52 * 240 / 775 + 4)
    pdf.set_font(pdf.body, 'B', 18)
    pdf.set_text_color(*INK)
    pdf.cell(0, 10, 'Sentinel Weekly Up Management Report')
    pdf.ln(13)

    bold_fill = _head_face()
    pdf.set_font(pdf.body, '', 11)
    with pdf.table(col_widths=TITLE_COLS,
                   first_row_as_headings=False, line_height=6.5,
                   borders_layout='ALL', padding=1.4) as table:
        for label, value in (
                ('Developed By:', header['developed_by']),
                ('Week Ending Date:', header['week_ending']),
                ('Issue Number:', header['issue_number']),
                ('Report Version:', header['report_version']),
                ('Developed For', header['developed_for'])):
            row = table.row()
            row.cell(label, style=bold_fill)
            row.cell(str(value))
    pdf.ln(4)


def _highlights(pdf, cards):
    _section(pdf, 1, 'Highlights / Wins (Past Week)')
    _instruction(pdf, '(One table per client, generated from the tracker)')
    if not cards:
        _note(pdf, 'No delivery projects.')
        return

    bold_fill = _head_face()
    bold = FontFace(emphasis='BOLD')

    for card in cards:
        # A card is thirteen rows; keep it whole rather than splitting a client
        # across a page break.
        if pdf.get_y() > pdf.h - 88:
            pdf.add_page()

        pdf.set_font(pdf.body, '', 10)
        with pdf.table(col_widths=CARD_COLS,
                       first_row_as_headings=False, line_height=5.8,
                       borders_layout='ALL', padding=1.2) as table:
            r = table.row()
            r.cell('Client:', style=bold_fill)
            r.cell(card['client'], colspan=3, style=bold)

            r = table.row()
            r.cell('Sprint:', style=bold_fill)
            r.cell(_n(card['sprint']), colspan=3)

            r = table.row()
            r.cell('Project Due Date:', style=bold_fill)
            r.cell(_n(card['project_due_date']), colspan=3)

            r = table.row()
            r.cell('Development:', style=bold_fill)
            r.cell('Completed', style=bold_fill)
            r.cell('Outstanding:', style=bold_fill)
            r.cell('Closed this week', style=bold_fill)

            for key in ('web', 'app', 'api'):
                s = card['streams'].get(key) or {}
                r = table.row()
                r.cell(f'{key.upper()}:', style=bold_fill)
                r.cell(str(s.get('completed', 0)))
                r.cell(str(s.get('outstanding', 0)))
                week = s.get('completed_this_week', 0)
                r.cell(f'+{week}' if week else '')

            un = card['streams'].get('unclassified')
            if un:
                r = table.row()
                r.cell('Unclassified:', style=bold_fill)
                r.cell(str(un.get('completed', 0)))
                r.cell(str(un.get('outstanding', 0)))
                week = un.get('completed_this_week', 0)
                r.cell(f'+{week}' if week else '')

            t = card['tickets']
            r = table.row()
            r.cell('Support Tickets:', style=bold_fill)
            r.cell(f"Total Raised: {t['raised_total']}", style=bold_fill)
            r.cell(f"Open: {t['open']}", style=bold_fill)
            r.cell(f"Closed: {t['closed']}", style=bold_fill)

            if card['wins_this_week']:
                r = table.row()
                r.cell('Wins:', style=bold_fill)
                r.cell('; '.join(w['title'] for w in card['wins_this_week'][:6]),
                       colspan=3)

            r = table.row()
            r.cell('Last Report Update:', style=bold_fill)
            r.cell(_n(card['last_report_update']), colspan=3)

            r = table.row()
            r.cell('Comments:', style=bold_fill)
            r.cell(card['comments'], colspan=3)
        pdf.ln(3.5)


def _risks(pdf, risks):
    _section(pdf, 2, 'Risk')
    head = _head_face()
    pdf.set_font(pdf.body, '', 9)
    with pdf.table(col_widths=(60, 26, 26, 22, 56),
                   first_row_as_headings=False, line_height=5.4,
                   borders_layout='ALL', padding=1.2) as table:
        r = table.row()
        for label in ('Issue Description:', 'Owner:', 'Resolution Time:',
                      'Severity:', 'Mitigation Plan:'):
            r.cell(label, style=head)
        for item in risks:
            row = table.row()
            row.cell(item['description'])
            row.cell(_n(item['owner']))
            row.cell(_n(item['resolution_time']))
            row.cell(item['severity_display'],
                     style=FontFace(fill_color=SEVERITY_FILL.get(
                         item['severity'], (255, 255, 255))))
            row.cell(item['mitigation'] or 'none recorded')
        if not risks:
            # The template prints the grid whether or not anything is in it, so
            # an empty register reads as empty rather than as a missing section.
            blank = table.row()
            for _ in range(5):
                blank.cell('')
    if any(r.get('source') == 'observed' for r in risks):
        _note(pdf, 'Some items were identified by the platform from the '
                   'tracker rather than entered on a register.')


def _focus(pdf, focus, pressure):
    _section(pdf, 3, 'Focus Matrix:')
    head = _head_face()

    pdf.set_font(pdf.body, 'B', 11)
    pdf.cell(0, 6, 'Staff Focus:')
    pdf.ln(7)

    people = focus['people']
    if not people:
        _note(pdf, 'Nobody is assigned to open work, so there is no staff '
                   'focus split to report.')
    else:
        # The label column takes 44 mm; the people and the totals column share
        # the rest, which is how the original is proportioned.
        # Ratios again: the label column is roughly a quarter, the rest split
        # evenly between the people and the totals column.
        widths = (44.0,) + (
            ((189.0 - 44) / (len(people) + 1)),) * (len(people) + 1)
        pdf.set_font(pdf.body, '', 8.5)
        with pdf.table(col_widths=widths,
                       first_row_as_headings=False, line_height=5.0,
                       borders_layout='ALL', padding=1.0,
                       text_align=Align.C) as table:
            r = table.row()
            r.cell('Product / Client:', style=head, align=Align.L)
            for p in people:
                r.cell(p['initials'], style=head)
            r.cell('Total:', style=head)

            for row_data in focus['staff_rows']:
                row = table.row()
                row.cell(row_data['bucket'], style=FontFace(emphasis='BOLD'),
                         align=Align.L)
                for cell in row_data['cells']:
                    row.cell('' if cell['share_pct'] is None
                             else f"{cell['share_pct']:g}%")
                row.cell(str(row_data['items']))

            total = table.row()
            total.cell('Total:', style=head, align=Align.L)
            for p in people:
                total.cell(f"{p['hours']:g}h",
                           style=FontFace(emphasis='BOLD', fill_color=(
                               SEVERITY_FILL['high'] if p['over_capacity']
                               else FILL)))
            total.cell('', style=head)
        _note(pdf, "Each cell is that person's share of their own open items "
                   'for the client; the totals row is hours committed. '
                   + ', '.join(f"{p['initials']} = {p['person']}"
                               for p in people) + '.')

    pdf.ln(2)
    pdf.set_font(pdf.body, 'B', 11)
    pdf.cell(0, 6, 'Company Focus:')
    pdf.ln(7)
    pdf.set_font(pdf.body, '', 9)
    with pdf.table(col_widths=(46, 26, 30, 30, 30, 28),
                   first_row_as_headings=False, line_height=5.4,
                   borders_layout='ALL', padding=1.2) as table:
        r = table.row()
        for label in ('Product / Client:', 'Open work %', 'Work Items Done',
                      'To be Completed', 'Next Due Date', 'Support %'):
            r.cell(label, style=head)
        for row_data in focus['company_rows']:
            row = table.row()
            row.cell(row_data['bucket'], style=FontFace(emphasis='BOLD'))
            row.cell(f"{row_data['share_pct']:g}%")
            row.cell(str(row_data['work_items_done']))
            row.cell(str(row_data['to_be_completed']))
            row.cell(_n(row_data['due_date']))
            row.cell(f"{row_data['support_pct']:g}%")

    pdf.ln(3)
    if pdf.get_y() > pdf.h - 48:
        pdf.add_page()
    pdf.set_font(pdf.body, 'B', 11)
    pdf.cell(0, 6, 'Sentinel Oversight:')
    pdf.ln(7)
    chosen = pressure.get('value') or ''
    pdf.set_font(pdf.body, '', 8.5)
    with pdf.table(col_widths=(42, 26, 26, 24, 40, 32),
                   first_row_as_headings=False, line_height=5.4,
                   borders_layout='ALL', padding=1.2,
                   text_align=Align.C) as table:
        r = table.row()
        r.cell('Sentinel Oversight:', style=head, align=Align.L)
        for _value, label in PRESSURE_SCALE:
            r.cell(label, style=head)
        row = table.row()
        row.cell('Delivery pressure', style=FontFace(emphasis='BOLD'),
                 align=Align.L)
        for value, _label in PRESSURE_SCALE:
            row.cell('X' if value == chosen else '',
                     style=FontFace(emphasis='BOLD', fill_color=(
                         (198, 224, 180) if value == chosen
                         else (255, 255, 255))))
    _note(pdf, 'Computed from workload: ' + pressure.get('reason', '')
               + ' This measures pressure on delivery, not how the team feels.')


def _financial(pdf, rows):
    _section(pdf, 4, 'Financial Components')
    head = _head_face()
    pdf.set_font(pdf.body, '', 9)
    with pdf.table(col_widths=(38, 44, 28, 20, 34, 26),
                   first_row_as_headings=False, line_height=5.4,
                   borders_layout='ALL', padding=1.2) as table:
        r = table.row()
        for label in ('Product / Client:', 'Next Deliverable',
                      'Next Invoice Date', 'SLA Active', 'Hosting Capacity',
                      'Reconciled:'):
            r.cell(label, style=head)
        for row_data in rows:
            row = table.row()
            row.cell(row_data['bucket'], style=FontFace(emphasis='BOLD'))
            row.cell(_n(row_data['next_deliverable']))
            row.cell(_n(row_data['next_invoice_date']))
            row.cell('Yes' if row_data['sla_active'] else 'No')
            row.cell(_n(row_data['hosting_capacity']))
            row.cell('Yes' if row_data['is_reconciled'] else 'No')
    _note(pdf, "Reconciled is management only. Read from each client's service "
               'agreement; the next deliverable is the nearest open due date.')


def _next_week(pdf, next_week):
    _section(pdf, 5, 'Plan for Next Week')
    head = _head_face()
    pdf.set_font(pdf.body, '', 9)
    with pdf.table(col_widths=(40, 82, 28, 40),
                   first_row_as_headings=False, line_height=5.4,
                   borders_layout='ALL', padding=1.2) as table:
        r = table.row()
        for label in ('Product / Client:', 'Comments / Key Notes', 'Due Date',
                      'Responsibility'):
            r.cell(label, style=head)
        for row_data in next_week['rows']:
            row = table.row()
            row.cell(row_data['bucket'], style=FontFace(emphasis='BOLD'))
            text = row_data['note'] or ''
            if row_data['items']:
                text = (text + '\n' + '\n'.join(
                    '- ' + i['title']
                    + (f" ({i['owner']})" if i['owner'] else '')
                    + (' [overdue]' if i.get('is_overdue') else '')
                    for i in row_data['items'][:6])).strip()
            row.cell(text)
            row.cell(_n(row_data['due_date']))
            row.cell(_n(row_data['responsibility']))


def render(week_start=None, data=None):
    """The report as PDF bytes."""
    week_start = week_start or week_start_for()
    data = data or up_report.build(week_start)
    header = data['header']

    pdf = UpReportPDF(week_ending=header['week_ending'],
                      version=header['report_version'])
    pdf.set_title('Sentinel Weekly Up Management Report - week ending '
                  f"{header['week_ending']}")
    pdf.set_author('Magnum Opus Consultants')
    pdf.set_creator('Sentinel')
    pdf.alias_nb_pages()
    pdf.add_page()

    _title_block(pdf, header)
    _highlights(pdf, data['highlights'])
    _risks(pdf, data['risks'])
    _focus(pdf, data['focus'], data['pressure'])
    _financial(pdf, data['financial'])
    _next_week(pdf, data['next_week'])

    pdf.ln(3)
    _note(pdf, 'Every figure in this report is computed from the project '
               'tracker; nothing in it is entered by hand. '
               + ' '.join(data['how_it_is_derived']))

    return bytes(pdf.output())


def filename(week_start=None):
    week_start = week_start or week_start_for()
    ending = week_start + timedelta(days=6)
    return f'Up Management Report - week ending {ending:%Y-%m-%d}.pdf'
