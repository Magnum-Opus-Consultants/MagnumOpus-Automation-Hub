"""Return Converted / Not Converted as text, the way the model's measures expect.

The workbook stores these as 1/0, so the first view did too. The Power BI model
does not: its M query built them as text -

    Not Converted = if [Booking #] = null then "Not Converted" else null
    Converted     = if [Booking #] <> null then "Converted"     else null

and the DAX measures compare against those strings. Handing them integers made
`Not Converted %` fail with "DAX comparison operations do not support comparing
values of type Text with Number".

The numeric form the M query also produced is kept under its own name,
"Converted Not Converted", which is what any measure doing arithmetic uses.
"""
from django.db import migrations

SQL = '''
DROP VIEW IF EXISTS pricing_report_v;
CREATE VIEW pricing_report_v AS
SELECT
    r.id                                          AS "Row ID",
    i.filename                                    AS "Source File",
    r.block                                       AS "Block",
    r.quote_no                                    AS "Quote #",
    NULLIF(r.booking_no, '')                      AS "Booking #",
    NULLIF(r.client, '')                          AS "Client",
    NULLIF(r.client_name, '')                     AS "Client Name",
    NULLIF(r.branch, '')                          AS "Branch",

    NULLIF(r.transport_mode, '')                  AS "Transport Mode",
    CASE WHEN r.transport_mode IN ('AIR', 'SEA') THEN r.transport_mode
         WHEN r.transport_mode = '' THEN NULL
         ELSE 'Other' END                         AS "Transport Mode Grouping",
    NULLIF(r.mode, '')                            AS "Mode",
    r.weight                                      AS "Weight",
    NULLIF(r.weight_unit, '')                     AS "UW",
    r.volume                                      AS "Volume",
    NULLIF(r.volume_unit, '')                     AS "UV",
    r.chargeable                                  AS "Chargeable",

    NULLIF(r.origin, '')                          AS "Origin",
    NULLIF(r.destination, '')                     AS "Destination",
    NULLIF(r.origin_country, '')                  AS "Origin Country",
    NULLIF(r.destination_country, '')             AS "Destination Country",
    NULLIF(r.incoterm, '')                        AS "Incoterm",

    NULLIF(r.direction, '')                       AS "Import/Export/Domestic",
    NULLIF(r.direction, '')                       AS "Import /Export",
    CASE WHEN r.direction = 'Import' THEN 'Import' END      AS "Import",
    CASE WHEN r.direction = 'Export' THEN 'Export' END      AS "Export",
    CASE WHEN r.direction = 'Domestic' THEN 'Domestic' END  AS "Domestic",
    NULLIF(r.au_nz_row, '')                       AS "AU/NZ / -  AU/NZ Row",
    CASE WHEN r.au_nz_row = 'AU/NZ' THEN 'AU/NZ' END        AS "AU/NZ",
    CASE WHEN r.au_nz_row = 'ROW' THEN 'ROW' END            AS "ROW",

    r.created_time                                AS "Created Time (UTC)",
    r.booked                                      AS "Booked",
    r.conversion_days                             AS "Conversion Time",
    r.month_start                                 AS "Month",
    NULLIF(r.month_label, '')                     AS "Month Label",
    r.year                                        AS "Year",
    NULLIF(r.quarter, '')                         AS "Quarter",
    r.month_sort                                  AS "Month Sort",

    NULLIF(r.assigned_to, '')                     AS "Assigned To",
    NULLIF(r.assigned_to_name, '')                AS "Assigned to Names",
    NULLIF(r.created_by, '')                      AS "Created By",
    NULLIF(r.created_by, '')                      AS "Created by name",

    -- Text, not 1/0: the measures compare against these exact strings.
    CASE WHEN r.converted THEN 'Converted' END              AS "Converted",
    CASE WHEN r.converted THEN NULL ELSE 'Not Converted' END AS "Not Converted",
    -- The numeric form, for anything doing arithmetic.
    CASE WHEN r.converted THEN 1 ELSE 0 END       AS "Converted Not Converted",
    CASE WHEN r.missed_opportunity THEN 1 ELSE 0 END        AS "Missed Oppertunity",

    r.total_income                                AS "Total Amount",
    r.total_income                                AS "Total Income",
    NULLIF(r.quote_status, '')                    AS "Quote Status",
    r.duplicate_pickup                            AS "Duplicate Pickup",
    NULLIF(r.duplicate_flag, '')                  AS "Duplicate",
    NULLIF(r.duplicate_flag, '')                  AS "Duplicate Filter",
    NULLIF(r.duplicate_flag, '')                  AS "Duplicate Fixed"
FROM pricing_row r
JOIN pricing_import i ON i.id = r.source_id
WHERE i.is_active;

COMMENT ON VIEW pricing_report_v IS
  'The Pricing Report, typed and named as the Power BI model expects. Shows '
  'the active import only.';
'''

DROP = 'DROP VIEW IF EXISTS pricing_report_v;'


class Migration(migrations.Migration):

    dependencies = [('dashboard', '0068_pricing_view_report_names')]

    operations = [migrations.RunSQL(SQL, DROP)]
