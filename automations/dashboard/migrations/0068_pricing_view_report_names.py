"""Rename the view's columns to exactly what the Pricing Report already asks for.

The first cut of this view used the workbook's column names. The Power BI model
built on top of that workbook had drifted from it in seven places, so repointing
the report broke every visual that touched one of them:

    view (before)        report expects
    -------------------  --------------------------
    Assigned To Names    Assigned to Names          (lower-case "to")
    AU/NZ ROW            AU/NZ / -  AU/NZ Row       (two spaces after the dash)
    Duplicate Filter     Duplicate
    Import/Export        Import/Export/Domestic
    -                    Import /Export             (space before the slash)
    Total Income         Total Amount
    Month (text label)   Month (a date)

The last one is the reason the month chart failed rather than just blanking: the
model hangs a date hierarchy off Month, which needs a real date, not the text
"January 2024". That label is still available as "Month Label".

The odd spellings are deliberate. They are what the report's 556 field
references contain, and renaming things in the report would mean touching every
visual instead of one view.
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

    -- Three spellings of the same idea, because the report uses all three.
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
    -- A real date: the model hangs its date hierarchy off this.
    r.month_start                                 AS "Month",
    NULLIF(r.month_label, '')                     AS "Month Label",
    r.year                                        AS "Year",
    NULLIF(r.quarter, '')                         AS "Quarter",
    r.month_sort                                  AS "Month Sort",

    NULLIF(r.assigned_to, '')                     AS "Assigned To",
    NULLIF(r.assigned_to_name, '')                AS "Assigned to Names",
    NULLIF(r.created_by, '')                      AS "Created By",
    NULLIF(r.created_by, '')                      AS "Created by name",

    CASE WHEN r.converted THEN 1 ELSE 0 END       AS "Converted",
    CASE WHEN r.converted THEN 0 ELSE 1 END       AS "Not Converted",
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
  'The Pricing Report, named exactly as the Power BI model expects. Shows the '
  'active import only.';
'''

DROP = 'DROP VIEW IF EXISTS pricing_report_v;'


class Migration(migrations.Migration):

    dependencies = [('dashboard', '0067_pricing_report_view')]

    operations = [migrations.RunSQL(VIEW, DROP)]
