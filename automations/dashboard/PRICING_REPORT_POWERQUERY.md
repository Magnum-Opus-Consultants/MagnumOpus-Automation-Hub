# Pricing Report — the Power Query, after the move to the database

## The short version

The old query was ~300 lines: read a file off one person's desktop, retype 160
columns, then rebuild a dozen derived columns with nested if-thens. All of that
now happens when the workbook is loaded into Sentinel, so the query is four
lines and returns the same columns under the same names.

```m
let
    Source   = PostgreSQL.Database("10.0.0.30:5432", "automation_platform"),
    Pricing  = Source{[Schema="public", Item="pricing_report_v"]}[Data]
in
    Pricing
```

That is the whole thing. Point Power BI at it, refresh, and every existing
pivot and measure keeps working — the view hands back the workbook's own column
names, including `Missed Oppertunity` with its typo and `AU/NZ ROW` with its
slash.

Running it on the same machine as the database? Use `127.0.0.1:5432` instead.

## Signing in

Power BI will ask once, then remember it:

| | |
|---|---|
| Authentication | **Database** (not Windows) |
| User name | `powerbi` |
| Password | the one in Sentinel's `.env` — ask, don't guess |
| Encryption | leave the "encrypt connections" box **unticked** unless the server has TLS on |
| Privacy level | **Organizational** |

If Power BI complains it cannot find a Npgsql provider, install
**Npgsql 4.0.x** — the newer 8.x releases do not register the Power BI data
provider.

## What you no longer have to do

Every one of these is applied by the loader before the row reaches the database,
so the step is gone from the query rather than hidden somewhere:

| Old step | Now |
|---|---|
| `Table.TransformColumnTypes` over 160 columns | typed by the database |
| `Assigned To` → name, 21 nested if-thens | `Assigned To Names` |
| `Created By` → name, 160 nested if-thens | `Created by name` |
| `Duration.TotalDays([Booked] - [Created Time (UTC)])` | `Conversion Time` |
| Converted / Not Converted / Converted Not Converted | `Converted`, `Not Converted` (1/0) |
| `Text.Start([Origin], Text.Length([Origin]) - 3)` | `Origin Country`, `Destination Country` |
| `Date.ToText(..., "MMM yyyy")` | `Month`, plus a real date in `Month Start` |
| `Table.Group` + `Table.Join` duplicate detection | `Duplicate Filter` / `Duplicate Fixed` |
| AU/NZ vs ROW conditional | `AU/NZ ROW`, `AU/NZ`, `ROW` |
| Import / Export / Domestic conditional | `Import/Export`, and the three flag columns |
| `Table.Combine({..., AnalysisTable})` | already appended — see **Block** below |
| Transport mode grouping | `Transport Mode Grouping` |

## The one new column: `Block`

The turnover analysis rows are already appended, exactly as `Table.Combine` did
it — but now you can tell the two apart without checking whether `Total Income`
happens to be blank:

* `Block = 'quote'` — the 71,501 pricing rows
* `Block = 'turnover'` — the 13,486 turnover rows carrying income and branch

Mixing them is nearly always a mistake, so filter on it in any measure that
counts quotes or sums income:

```m
// quotes only
= Table.SelectRows(Pricing, each [Block] = "quote")
```

```dax
-- DAX equivalents
Quotes  = CALCULATE(COUNTROWS('Pricing'), 'Pricing'[Block] = "quote")
Income  = CALCULATE(SUM('Pricing'[Total Income]), 'Pricing'[Block] = "turnover")
```

## Only the current load is visible

The view shows whichever import is marked active in Sentinel, so a refresh never
picks up a half-loaded file, and switching back to an earlier load on the Data
Analysis page changes what Power BI sees on its next refresh. `Source File`
carries the filename if you want it on the report.

## Pushing the filter down to the database

By default Power Query pulls all 84,987 rows and filters in memory. For a report
that only ever looks at one year, let the database do it — the row count over
the wire drops by two thirds:

```m
let
    Source  = PostgreSQL.Database("10.0.0.30:5432", "automation_platform"),
    Pricing = Source{[Schema="public", Item="pricing_report_v"]}[Data],
    Recent  = Table.SelectRows(Pricing, each [Year] >= 2025)
in
    Recent
```

`Table.SelectRows` on a plain column folds into SQL, so this becomes a `WHERE`
clause rather than a client-side scan.

## If you would rather not use the view

The underlying tables are `pricing_row` (one row per source row, snake_case
columns) and `pricing_import` (one row per load). The view is just a friendlier
face on a join of the two, and the same `powerbi` login reads either.
