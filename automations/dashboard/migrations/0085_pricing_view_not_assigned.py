"""Label unassigned quotes "Not Assigned" in the Pricing Report view.

Quotes with no Assigned To came through as blanks, so the report showed empty
rows and "(Blank)" slices. Only quote rows get the label; turnover rows have no
assignment at all and stay blank.
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

    -- Quotes nobody picked up say so, rather than showing as blanks (Gerald, 28 Sep 2026).
    -- Turnover rows have no assignment and stay blank.
    CASE WHEN r.block = 'quote' THEN COALESCE(NULLIF(r.assigned_to, ''), 'Not Assigned')
         ELSE NULLIF(r.assigned_to, '') END      AS "Assigned To",
    CASE WHEN r.block = 'quote' THEN COALESCE(NULLIF(r.assigned_to_name, ''), 'Not Assigned')
         ELSE NULLIF(r.assigned_to_name, '') END AS "Assigned to Names",
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

-- Dropping the view drops its grants; Power BI reads it as powerbi.
GRANT ALL ON pricing_report_v TO powerbi;
'''

DROP = 'DROP VIEW IF EXISTS pricing_report_v;'


class Migration(migrations.Migration):

    dependencies = [('dashboard', '0084_projecttask_workspace')]

    operations = [migrations.RunSQL(SQL, DROP)]
