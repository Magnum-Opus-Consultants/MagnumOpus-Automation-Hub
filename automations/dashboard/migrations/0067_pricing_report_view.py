"""A read-only view of the pricing data, using the workbook's own column names.

The point of this view is that nothing downstream has to be rewritten. Power
Query, Power BI and any pivot built on the old workbook refer to columns like
"Assigned To Names", "AU/NZ ROW" and "Missed Oppertunity" - typo and all - so
the view hands back exactly those, rebuilt from the normalised table.

The pivot-helper columns are reconstructed rather than stored, because each is
a restatement of a column that already exists:

    Airfreight / Seafreight  from transport_mode
    Import / Export / Domestic  from direction
    AU/NZ / ROW  from au_nz_row
    Not Converted  from converted

Storing both would give two versions of the same fact and no way to tell which
one a report had used.
"""
from django.db import migrations

VIEW = '''
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
    NULLIF(r.transport_mode, '')                  AS "Transport Mode",
    NULLIF(r.mode, '')                            AS "Mode",
    CASE WHEN r.transport_mode = 'AIR' THEN 'AIR' END   AS "Airfreight",
    CASE WHEN r.transport_mode = 'SEA' THEN 'SEA' END   AS "Seafreight",
    CASE WHEN r.transport_mode IN ('AIR', 'SEA') THEN r.transport_mode
         WHEN r.transport_mode = '' THEN NULL
         ELSE 'Other' END                         AS "Transport Mode Grouping",
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
    CASE WHEN r.direction = 'Import' THEN 'Import' END      AS "Import",
    CASE WHEN r.direction = 'Export' THEN 'Export' END      AS "Export",
    CASE WHEN r.direction = 'Domestic' THEN 'Domestic' END  AS "Domestic",
    NULLIF(r.direction, '')                       AS "Import/Export",
    NULLIF(r.au_nz_row, '')                       AS "AU/NZ ROW",
    CASE WHEN r.au_nz_row = 'AU/NZ' THEN 'AU/NZ' END        AS "AU/NZ",
    CASE WHEN r.au_nz_row = 'ROW' THEN 'ROW' END            AS "ROW",
    r.created_time                                AS "Created Time (UTC)",
    r.booked                                      AS "Booked",
    r.conversion_days                             AS "Conversion Time",
    NULLIF(r.month_label, '')                     AS "Month",
    r.month_start                                 AS "Month Start",
    r.year                                        AS "Year",
    NULLIF(r.quarter, '')                         AS "Quarter",
    r.month_sort                                  AS "Month Sort",
    NULLIF(r.assigned_to, '')                     AS "Assigned To",
    NULLIF(r.assigned_to_name, '')                AS "Assigned To Names",
    NULLIF(r.created_by, '')                      AS "Created By",
    NULLIF(r.created_by, '')                      AS "Created by name",
    CASE WHEN r.converted THEN 1 ELSE 0 END       AS "Converted",
    CASE WHEN r.converted THEN 0 ELSE 1 END       AS "Not Converted",
    CASE WHEN r.missed_opportunity THEN 1 ELSE 0 END        AS "Missed Oppertunity",
    r.total_income                                AS "Total Income",
    NULLIF(r.quote_status, '')                    AS "Quote Status",
    r.duplicate_pickup                            AS "Duplicate Pickup",
    NULLIF(r.duplicate_flag, '')                  AS "Duplicate Filter",
    NULLIF(r.duplicate_flag, '')                  AS "Duplicate Fixed",
    NULLIF(r.branch, '')                          AS "Branch"
FROM pricing_row r
JOIN pricing_import i ON i.id = r.source_id
WHERE i.is_active;

COMMENT ON VIEW pricing_report_v IS
  'The Pricing Report in the workbook''s own column names, for Power Query and '
  'Power BI. Shows the active import only.';
'''

DROP = 'DROP VIEW IF EXISTS pricing_report_v;'


class Migration(migrations.Migration):

    dependencies = [('dashboard', '0066_pricing_report')]

    operations = [migrations.RunSQL(VIEW, DROP)]
