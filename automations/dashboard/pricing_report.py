"""The Pricing Report: load the workbook into the database, then report on it.

## What this replaces

The report used to be a Power Query in Excel, pointed at a CargoWise export on
somebody's desktop. That query did four jobs:

  1. read the export and type its columns;
  2. map staff codes to names, twice (Assigned To and Created By);
  3. derive conversion time, converted/not-converted, origin and destination
     country, month, AU-NZ-vs-rest, import/export/domestic, and a duplicate
     flag by grouping on client + status + weight + volume + staff + month;
  4. append the turnover analysis rows underneath, so one table carried both
     the quotes on top and the income at the bottom.

All four now happen here, against the database, so the report does not depend
on one laptop, one file path, or one person remembering to hit refresh.

## The two blocks

The workbook is two tables stacked in one sheet and that shape is kept, because
it is what the analysis means:

  * **quote** rows - the pricing export. Every column except income.
  * **turnover** rows - the turnover analysis appended underneath. Only client,
    month, branch and income; no quote ever existed for these.

A figure that mixes them is nearly always a mistake, so every query in here
states which block it is reading.

## Loading a workbook that has already been transformed

The file people download today is the *processed* workbook - the analyst's own
derived columns are already in it. So the loader prefers what the sheet says
and only computes a column when the sheet does not carry it. Both paths are
implemented, because the raw CargoWise export has none of them, and this is
what lets the same loader take either file.
"""
import datetime as dt
import logging
import os
import re
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation

from django.db import transaction
from django.db.models import Avg, Count, Q, Sum

from .models import PricingImport, PricingRow

logger = logging.getLogger(__name__)

# Written in Python rather than 200 nested if-thens, which is what the M query
# had to do. Same mappings, both directions of the workbook's two lookups.
ASSIGNED_NAMES = {
    'JS3': 'Jeremy Stewart', 'T02': 'Julian Camargo', 'KG1': 'Kathleen Gilpin',
    'KI': 'Kevin Idrobo', 'T03': 'Maria Valencia', 'M16': 'Merylou Pascua',
    'MP2': 'Michelle Perez', 'RB2': 'Rachel Bourke', 'AB': 'Andrew Belov',
    'GL1': 'Gerald Lowe', 'T08': 'Harold Pertuz', 'DH': 'Daniel Huigh',
    'CH1': 'Christan Horn', 'MR1': 'Manny Reyes', 'GB1': 'Grham Burford',
    'XF': 'Xavier Faletoi', 'RT1': 'Rober Thatcher', 'SM1': 'Stacey Prestwood',
    'AP': 'Ashley Prudence', 'CA': 'Celeste Apollo', 'MP3': 'Manica Pua',
}

CREATED_BY_NAMES = {
    'AO': 'Alfredo Orellana', 'FFR': 'Faramarz Faramarzian',
    'MH2': 'Marseu Haukoulua', 'TH2': "T'ona Hodge", 'JPL': 'Jessica Plancarte',
    'AAB': 'BravoTran', 'PR': 'Pedro Romero', 'AD2': 'Ali Danesh',
    'ME': 'Mike Eriksen', 'CT': 'Condor Team', 'CG6': 'Cen Global',
    'AK1': 'Alex Knowles', 'MP4': 'Mike Pattinson', 'JG1': 'John Greenstreet',
    'TP4': 'Tiania Penigar', 'KE': 'Krysten.Estrada', 'PV': 'Pita Vahe',
    'ZV': 'Ziggy Vollrath', 'BC': 'Brittany Walker', 'JT2': 'Jaimee Thein',
    'AA2': 'Alaysia Allen-Grijalva', 'AA3': 'Akenese Aselemo',
    'RM4': 'Richard Marquez', 'MP2': 'Michelle Perez', 'CL': 'Cassandra Laban',
    'CSA': '2B Solution Group', 'SB': 'Sherly Babaran', 'M02': 'Reymark Coloma',
    'SM2': 'Steve McWain', 'CA1': 'Cynthia Avalos', 'UW2': 'LAX Warehouse User 2',
    'M03': 'Joanna Bascon', 'M18': 'Deiseree Africa', 'MP3': 'Monica Pena',
    'CH1': 'Christian Horn', 'RM2': 'Rocio Monge', 'JV1': 'Jeffrey Vittorio',
    'DN': 'Daniel Navarro', 'BR2': 'Blanca Ramos', 'SK1': 'Susan Kimsey',
    'JS4': 'Joshua Sanchez', 'TF': 'Tony Feist', 'RT1': 'Robert Thatcher',
    'DH1': 'Darlene Ho', 'SG2': 'Sili Galeai', 'NF': 'Nadadia.Fuimaono',
    'CA': 'Celeste Apollo', 'M22': 'Shara Jae Sta Maria', 'SM3': 'Shoaib Mustafa',
    'GB1': 'Graham Burford', 'VR': 'Viviana Rivera', 'DH': 'Daniel Haigh',
    'YE': 'Christine Diciembre', 'JF': 'Janel Pickard-Faletoi',
    'M05': 'Glenn Mark Morfe', 'AK3': 'Alan Kuczynski', 'CM3': 'Cherey Miller',
    'MG2': 'Martin Garcia', 'HF': 'Havilah Fenis', 'M08': 'Mikchaela Tenorio',
    'HL': 'Hazel Chu-Ling', 'MS3': 'Maria Victoria Saleapaga',
    'EM1': 'Elizabeth Medina', 'EC': 'Easter Carter', 'XF': 'Xavier Faletoi',
    'M14': 'Len Mari Adriano', 'JG3': 'Jose Garcia', 'M16': 'Merylou Pascua',
    'VN': 'Viet Nguyen', 'MR1': 'Manny Reyes', 'RB2': 'Rachel Bourke',
    'JM5': 'Joel Miguel', 'M07': 'Carl Reyes', 'BM': 'Bill Maugle',
    'UW': 'LAX Warehouse User 1', 'BY': 'Bruce Yun',
    'TW1': 'Transit Warehouse User 1', 'KS3': 'Keybond Saleapaga',
    'OA': 'Oscar Arevalo', 'TH1': "T'ona Hodge", 'MM1': 'Michael McGlone',
    'MM3': 'Myra March', 'AP': 'Ashley Prudence', 'AS4': 'Angel Suarez',
    'M20': 'Norissa Suguitan', 'GR': 'Gabrielle Vollrath', 'M19': 'Renee Via Malit',
    'CDR': 'Christina Drain', 'JI': 'Jeff Intriago', 'JV3': 'Jhoana Verbo',
    'ML4': 'Mike Labine', 'TH': 'Trisha Helms', 'MK': 'Melina Kadic',
    'NPA': 'Nadira Prashad-arjun', 'OPB': 'Anne Ferrancol', 'JH1': 'Jason Hu',
    'T03': 'Maria Valencia', 'TD': 'Tony DeLaurie', 'SM1': 'Stacey Prestwood',
    'M21': 'Angielyn Manalo', 'RM': 'Regina March', 'KI': 'Kevin Idrobo',
    'SD1': 'Sueann Dyer', 'DV': 'Diane Van Oostenbrugge', 'LP': 'Lauren Padilla',
    'AMR': 'Anniese Martin', 'DS': 'Deepah Smith', 'EP': 'Eveline Perez',
    'LH': 'Lizeth Hurtado', 'KG1': 'Kathleen Marie Gilpin', 'KD4': 'Kurt Davis',
    'T02': 'Julian Camargo', 'EFR': 'Eben Fourie', 'JH': 'Jacey Hines',
    'AV': 'Anna Corina Vazquez', 'FA': 'Firas Alramone', 'M13': 'ISB.MDPC13',
    'AAA': 'Len Broqueza', 'SR': 'Sherry Ramjohn', 'KS': 'Kefarkes Slifo',
    'M17': 'Jhonard Depositar', 'TK': 'Trish Kelly', 'CP': 'Chris Pilkati',
    'WS1': 'Wanda Stone', 'GD': 'Gabe DeLaurie', 'BM3': 'Brian Martinez',
    'C01': 'Zama Kunene', 'M23': 'Adrian Amandy', 'JE': 'Jeff Estes',
    'CS1': 'Crystal Snider', 'JP1': 'Jose Pacheco', 'NG': 'Narabey Garcia',
    'T01': 'Naidu Espitia', 'AQ': 'Andres Quevedo', 'BR3': 'Bogdan Rog',
    'AB2': 'Angie Bitterman', 'DS2': 'Dernesha Speight', 'RO': 'Ray Anne Ong',
    'GL1': 'Import Support', 'JM1': 'Jesse Maugle', 'MK1': 'Mason Kreiter',
    'MR': 'Mila Rahman', 'SH1': 'Salman Hashmi', 'UW3': 'LAX Warehouse User 3',
    'M09': 'Ericca Mahilaga', 'AC': 'Andrea Calderon', 'BS': 'Brock Stinson',
    'CV': 'Chloe Vidana', 'M01': 'Gizelle Manalo', 'PE': 'Kimberly Nogales',
    'LS': 'Callum Bartlett', 'EG': 'Elaclare Guerrero', 'M10': 'Patricia Biagtan',
    'M11': 'Sharra Mae Garcia', 'FR': 'Filipo Robertson', 'JS3': 'Jeremy Stewart',
    'M06': 'Michelle Escalante', 'AH': 'Antonette Hamrick', 'M04': 'Harry Cañamo',
    'M12': 'Niña De Torres', 'M15': 'Alona Cana',
}

# The workbook's own header spellings, including the typo in "Oppertunity",
# because renaming them in the file would break the analyst's other pivots.
SHEET = 'Sheet1'
MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
          'August', 'September', 'October', 'November', 'December']
_MONTH_NO = {m: i + 1 for i, m in enumerate(MONTHS)}

BATCH = 2000


# ══════════════════════════════════════════════════════════════════════════════
# Reading a cell
# ══════════════════════════════════════════════════════════════════════════════

def _s(v, limit=None):
    """A cell as clean text. Excel's stray whitespace and #N/A both become ''."""
    if v is None:
        return ''
    s = str(v).strip()
    if s in ('#N/A', '#REF!', '#VALUE!', 'nan', 'None'):
        return ''
    return s[:limit] if limit else s


def _f(v):
    """A cell as a float, or None. Excel hands back '1,234.5' often enough."""
    if v is None or v == '':
        return None
    if isinstance(v, (int, float)) and not isinstance(v, bool):
        return float(v)
    try:
        return float(str(v).replace(',', '').replace('$', '').strip())
    except (TypeError, ValueError):
        return None


def _i(v):
    f = _f(v)
    return int(f) if f is not None else None


def _money(v):
    f = _f(v)
    if f is None:
        return None
    try:
        return Decimal(str(round(f, 2)))
    except (InvalidOperation, ValueError):
        return None


def _dtm(v):
    """A cell as a UTC datetime, or None.

    Excel stores no zone. The source column is called "Created Time (UTC)" and
    the booking dates come from the same system, so UTC is what they are -
    stamping it here keeps them out of Django's naive-datetime warning and,
    more to the point, stops them shifting by the server's offset later.
    """
    parsed = None
    if isinstance(v, dt.datetime):
        parsed = v
    elif isinstance(v, dt.date):
        parsed = dt.datetime(v.year, v.month, v.day)
    else:
        s = _s(v)
        if not s:
            return None
        for fmt in ('%Y-%m-%d %H:%M:%S', '%Y-%m-%d %H:%M', '%Y-%m-%d',
                    '%d/%m/%Y %H:%M', '%d/%m/%Y', '%m/%d/%Y %H:%M', '%m/%d/%Y'):
            try:
                parsed = dt.datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def _month_start(label, created):
    """"January 2024" -> date(2024, 1, 1); falls back to the created date."""
    m = re.match(r'^([A-Za-z]+)\s+(\d{4})$', _s(label))
    if m and m.group(1).capitalize() in _MONTH_NO:
        return dt.date(int(m.group(2)), _MONTH_NO[m.group(1).capitalize()], 1)
    if created:
        return dt.date(created.year, created.month, 1)
    return None


def _country(port):
    """CargoWise port codes are country + city: USHOU -> US, INMAA -> IN.

    The M query took everything but the last three characters, which is the
    same rule; this one refuses to guess at a code too short to hold both.
    """
    p = _s(port)
    return p[:-3] if len(p) > 3 else ''


# ══════════════════════════════════════════════════════════════════════════════
# Loading
# ══════════════════════════════════════════════════════════════════════════════

def load(path, user=None, make_active=True, sheet=SHEET):
    """Read a pricing workbook into the database. Returns the PricingImport.

    Streams the sheet: the file is over 20 MB and 200 MB unzipped, so nothing
    here holds more than one batch of rows at a time.
    """
    import openpyxl

    if not os.path.isfile(path):
        raise FileNotFoundError(path)

    stat = os.stat(path)
    imp = PricingImport.objects.create(
        filename=os.path.basename(path),
        file_size=stat.st_size,
        file_modified=dt.datetime.fromtimestamp(stat.st_mtime,
                                                tz=dt.timezone.utc),
        loaded_by=user if (user and user.is_authenticated) else None,
        is_active=False,          # flipped at the end, so a crash leaves the
    )                             # previous load serving the page

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet] if sheet in wb.sheetnames else wb.worksheets[0]
        rows = ws.iter_rows(values_only=True)
        header = [_s(h) for h in next(rows)]
        col = {h: i for i, h in enumerate(header) if h}

        def cell(row, name):
            i = col.get(name)
            return row[i] if i is not None and i < len(row) else None

        buf, counts, skipped, n = [], Counter(), 0, 0
        # The duplicate rule groups on six columns; counted as we stream and
        # applied afterwards, which is what the M query's Table.Group did.
        dup_key_count = Counter()
        needs_dup = 'Duplicate Filter' not in col and 'Duplicate Fixed' not in col

        for raw in rows:
            n += 1
            if not any(v is not None and str(v).strip() != '' for v in raw):
                skipped += 1
                continue

            income = _money(cell(raw, 'Total Income'))
            block = PricingRow.TURNOVER if income is not None else PricingRow.QUOTE

            created = _dtm(cell(raw, 'Created Time (UTC)'))
            booked = _dtm(cell(raw, 'Booked'))
            month_label = _s(cell(raw, 'Month'), 30)
            origin = _s(cell(raw, 'Origin'), 20)
            dest = _s(cell(raw, 'Destination'), 20)

            # Prefer the workbook's own derived column; work it out when the
            # sheet is a raw export that has none.
            o_country = _s(cell(raw, 'Origin Country'), 8) or _country(origin)
            d_country = _s(cell(raw, 'Destination Country'), 8) or _country(dest)

            direction = _s(cell(raw, 'Import/Export'), 12)
            if not direction and d_country:
                direction = ('Domestic' if o_country == 'US' == d_country
                             else 'Import' if d_country == 'US' else 'Export')

            au_nz = _s(cell(raw, 'AU/NZ ROW'), 8)
            if not au_nz and d_country:
                au_nz = 'AU/NZ' if d_country in ('AU', 'NZ') else 'ROW'

            assigned = _s(cell(raw, 'Assigned To'), 20)
            assigned_name = _s(cell(raw, 'Assigned To Names'), 120)
            if not assigned_name and assigned:
                assigned_name = ASSIGNED_NAMES.get(assigned, 'New Employer')

            # "Created By" arrives as a code in the raw export and as a name in
            # the processed workbook; the lookup passes a name straight through.
            created_by = _s(cell(raw, 'Created By'), 120)
            created_by = CREATED_BY_NAMES.get(created_by, created_by)

            booking = _s(cell(raw, 'Booking #'), 60)
            converted_cell = _i(cell(raw, 'Converted'))
            converted = (bool(converted_cell) if converted_cell is not None
                         else bool(booking))

            conv_days = None
            if booked and created:
                conv_days = round((booked - created).total_seconds() / 86400, 1)

            dup = (_s(cell(raw, 'Duplicate Fixed'), 12)
                   or _s(cell(raw, 'Duplicate Filter'), 12))
            if needs_dup:
                key = (_s(cell(raw, 'Client')), _s(cell(raw, 'Quote Status')),
                       _f(cell(raw, 'Weight')), _f(cell(raw, 'Volume')),
                       assigned, month_label)
                dup_key_count[key] += 1

            buf.append(PricingRow(
                source=imp, block=block, row_number=n + 1,
                client=_s(cell(raw, 'Client'), 60),
                client_name=_s(cell(raw, 'Client Name'), 255),
                branch=_s(cell(raw, 'Branch'), 40),
                month_label=month_label,
                month_start=_month_start(month_label, created),
                year=_i(cell(raw, 'Year')),
                quarter=_s(cell(raw, 'Quarter'), 4),
                month_sort=_i(cell(raw, 'Month Sort')),
                quote_no=_i(cell(raw, 'Quote #')),
                booking_no=booking,
                quote_status=_s(cell(raw, 'Quote Status')),
                created_time=created, booked=booked,
                conversion_days=conv_days,
                converted=converted,
                missed_opportunity=bool(_i(cell(raw, 'Missed Oppertunity'))),
                transport_mode=_s(cell(raw, 'Transport Mode'), 20),
                mode=_s(cell(raw, 'Mode'), 20),
                weight=_f(cell(raw, 'Weight')),
                weight_unit=_s(cell(raw, 'UW'), 8),
                volume=_f(cell(raw, 'Volume')),
                volume_unit=_s(cell(raw, 'UV'), 8),
                chargeable=_f(cell(raw, 'Chargeable')),
                origin=origin, destination=dest,
                origin_country=o_country, destination_country=d_country,
                incoterm=_s(cell(raw, 'Incoterm'), 20),
                direction=direction, au_nz_row=au_nz,
                assigned_to=assigned, assigned_to_name=assigned_name,
                created_by=created_by,
                total_income=income,
                duplicate_flag=dup,
                duplicate_pickup=_i(cell(raw, 'Duplicate Pickup')),
            ))
            counts[block] += 1

            if len(buf) >= BATCH:
                PricingRow.objects.bulk_create(buf, batch_size=BATCH)
                buf = []
        if buf:
            PricingRow.objects.bulk_create(buf, batch_size=BATCH)
    finally:
        wb.close()

    if needs_dup:
        _apply_duplicate_flags(imp, dup_key_count)

    imp.quote_rows = counts[PricingRow.QUOTE]
    imp.turnover_rows = counts[PricingRow.TURNOVER]
    imp.skipped_rows = skipped
    imp.notes = (f'{len(header)} columns read from "{sheet}". '
                 f'Duplicate flags {"computed here" if needs_dup else "taken from the workbook"}.')
    if make_active:
        with transaction.atomic():
            PricingImport.objects.filter(is_active=True).update(is_active=False)
            imp.is_active = True
            imp.save()
    else:
        imp.save()
    logger.info('[pricing] loaded %s: %s quote + %s turnover rows',
                imp.filename, imp.quote_rows, imp.turnover_rows)
    return imp


def _apply_duplicate_flags(imp, key_count):
    """Mark the groups that appeared more than once, in two statements.

    The M query joined a grouped table back onto the original; the same idea,
    but the grouping is already in memory so only the duplicates need writing.
    """
    dup_keys = [k for k, c in key_count.items() if c > 1]
    imp.rows.update(duplicate_flag='Unique')
    for i in range(0, len(dup_keys), 200):
        q = Q()
        for client, status, weight, volume, assigned, month in dup_keys[i:i + 200]:
            q |= Q(client=client, quote_status=status, weight=weight,
                   volume=volume, assigned_to=assigned, month_label=month)
        if q:
            imp.rows.filter(q).update(duplicate_flag='Duplicate')


def active_import():
    return PricingImport.objects.filter(is_active=True).first()


# ══════════════════════════════════════════════════════════════════════════════
# Reporting
# ══════════════════════════════════════════════════════════════════════════════

def _filtered(imp, filters):
    """The base queryset, with the page's filters applied.

    One filter set scopes the whole report, quotes and income alike, so the two
    halves of the page can never be showing different periods.
    """
    qs = PricingRow.objects.filter(source=imp)
    year = filters.get('year')
    if year:
        qs = qs.filter(year=int(year))
    branch = filters.get('branch')
    if branch:
        qs = qs.filter(branch=branch)
    mode = filters.get('mode')
    if mode:
        qs = qs.filter(transport_mode=mode)
    direction = filters.get('direction')
    if direction:
        qs = qs.filter(direction=direction)
    if filters.get('unique_only'):
        # The analyst's own de-duplication, off by default because it changes
        # the totals and the reader should be told when it is on.
        qs = qs.exclude(duplicate_flag='Duplicate')
    return qs


def report(filters=None):
    """Everything the Pricing Report page draws, in one query pass per section."""
    filters = filters or {}
    imp = active_import()
    if not imp:
        return {'loaded': False, 'source': None}

    rows = _filtered(imp, filters)
    quotes = rows.filter(block=PricingRow.QUOTE)
    turnover = rows.filter(block=PricingRow.TURNOVER)

    total_quotes = quotes.count()
    converted = quotes.filter(converted=True).count()
    income = turnover.aggregate(v=Sum('total_income'))['v'] or Decimal('0')

    # ── Quotes and conversion by month, which is the top half of the report ──
    by_month = defaultdict(lambda: {'quotes': 0, 'converted': 0,
                                    'income': Decimal('0')})
    for r in (quotes.values('month_start', 'month_label')
              .annotate(n=Count('id'), c=Count('id', filter=Q(converted=True)))
              .order_by('month_start')):
        k = r['month_start']
        by_month[k]['label'] = r['month_label']
        by_month[k]['quotes'] = r['n']
        by_month[k]['converted'] = r['c']
    # ── and the income by month, which is the bottom half ──
    for r in (turnover.values('month_start', 'month_label')
              .annotate(v=Sum('total_income')).order_by('month_start')):
        k = r['month_start']
        by_month[k].setdefault('label', r['month_label'])
        by_month[k]['income'] = r['v'] or Decimal('0')

    months = [{
        'month': k.isoformat() if k else '',
        'label': v.get('label', ''),
        'quotes': v['quotes'],
        'converted': v['converted'],
        'conversion_pct': round(100 * v['converted'] / v['quotes'], 1)
                          if v['quotes'] else None,
        'income': float(v['income']),
    } for k, v in sorted(by_month.items(), key=lambda kv: (kv[0] is None, kv[0]))]

    def _group(qs, field, value_field=None, limit=None):
        """Count (or sum) by one column, biggest first, blanks dropped."""
        agg = (Sum(value_field) if value_field else Count('id'))
        out = [{'key': r[field] or '(none)', 'value': float(r['v'] or 0)}
               for r in qs.values(field).annotate(v=agg).order_by('-v')
               if r[field]]
        return out[:limit] if limit else out

    # Income and branches come from the turnover block; everything else is a
    # property of a quote, so the two are never mixed in one series.
    branches = [{
        'branch': r['branch'],
        'income': float(r['v'] or 0),
        'quotes': 0,
    } for r in (turnover.values('branch').annotate(v=Sum('total_income'))
                .order_by('-v')) if r['branch']]
    quote_by_branch = {r['branch']: r['n'] for r in
                       quotes.values('branch').annotate(n=Count('id'))}
    for b in branches:
        b['quotes'] = quote_by_branch.get(b['branch'], 0)

    top_clients = [{
        'client': r['client'],
        'name': r['client_name'],
        'income': float(r['v'] or 0),
    } for r in (turnover.values('client', 'client_name')
                .annotate(v=Sum('total_income')).order_by('-v')[:15])]

    # Conversion by the person who quoted: the question the report exists for.
    by_person = [{
        'person': r['assigned_to_name'] or r['assigned_to'],
        'quotes': r['n'],
        'converted': r['c'],
        'conversion_pct': round(100 * r['c'] / r['n'], 1) if r['n'] else 0,
        'avg_days': round(r['d'], 1) if r['d'] is not None else None,
    } for r in (quotes.exclude(assigned_to_name='', assigned_to='')
                .values('assigned_to_name', 'assigned_to')
                .annotate(n=Count('id'), c=Count('id', filter=Q(converted=True)),
                          d=Avg('conversion_days'))
                .order_by('-n')[:20])]

    duplicates = quotes.filter(duplicate_flag='Duplicate').count()

    return {
        'loaded': True,
        'source': {
            'filename': imp.filename,
            'loaded_at': imp.loaded_at.isoformat(),
            'quote_rows': imp.quote_rows,
            'turnover_rows': imp.turnover_rows,
            'size_mb': round(imp.file_size / 1_048_576, 1),
        },
        'filters': {
            'applied': {k: v for k, v in filters.items() if v},
            'years': sorted({y for y in rows.values_list('year', flat=True)
                             .distinct() if y}),
            'branches': sorted({b for b in rows.values_list('branch', flat=True)
                                .distinct() if b}),
            'modes': sorted({m for m in quotes.values_list('transport_mode',
                                                           flat=True)
                             .distinct() if m}),
            'directions': sorted({d for d in quotes.values_list('direction',
                                                                flat=True)
                                  .distinct() if d}),
        },
        'totals': {
            'quotes': total_quotes,
            'converted': converted,
            'conversion_pct': round(100 * converted / total_quotes, 1)
                              if total_quotes else 0,
            'missed': quotes.filter(missed_opportunity=True).count(),
            'duplicates': duplicates,
            'income': float(income),
            'clients': rows.exclude(client='').values('client')
                       .distinct().count(),
            'avg_conversion_days': round(
                quotes.filter(converted=True)
                .aggregate(d=Avg('conversion_days'))['d'] or 0, 1),
        },
        'months': months,
        'branches': branches,
        'top_clients': top_clients,
        'by_person': by_person,
        'transport_modes': _group(quotes, 'transport_mode'),
        'directions': _group(quotes, 'direction'),
        'au_nz': _group(quotes, 'au_nz_row'),
        'lanes': _group(quotes, 'destination_country', limit=12),
    }
