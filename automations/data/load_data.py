"""Load Up-Down Trader Report data into PostgreSQL tables."""
import os, sys, re, django

os.environ['DJANGO_SETTINGS_MODULE'] = 'automations.settings'
# Run from automations/ directory
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))
django.setup()

import openpyxl
from django.db import connection
from psycopg2.extras import execute_values

DATA_DIR = os.path.dirname(__file__)

MONTH_NAMES = ['JAN', 'FEB', 'MAR', 'APR', 'MAY', 'JUN',
               'JUL', 'AUG', 'SEP', 'OCT', 'NOV', 'DEC']


def _extract_year(filename):
    """Extract first 4-digit year (20XX) from a filename."""
    m = re.search(r'20\d{2}', os.path.basename(filename))
    if m:
        return int(m.group())
    return None


def _ensure_year_columns(year):
    """Add m_{year}01-m_{year}12, total_{year}, and budget_{year} columns if they don't exist."""
    with connection.cursor() as cur:
        for month in range(1, 13):
            cur.execute(f"ALTER TABLE customer_spend ADD COLUMN IF NOT EXISTS m_{year}{month:02d} NUMERIC(14,2)")
        cur.execute(f"ALTER TABLE customer_spend ADD COLUMN IF NOT EXISTS total_{year} NUMERIC(14,2)")
        cur.execute(f"ALTER TABLE customer_spend ADD COLUMN IF NOT EXISTS budget_{year} NUMERIC(14,2)")


def _get_year_columns_from_db():
    """Discover which years have columns in customer_spend table."""
    with connection.cursor() as cur:
        cur.execute("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'customer_spend' AND column_name ~ '^m_\\d{6}$'
            ORDER BY column_name
        """)
        cols = [r[0] for r in cur.fetchall()]
    years = sorted(set(int(c[2:6]) for c in cols))
    return years


def ensure_tables():
    """Create tables if they don't exist."""
    with connection.cursor() as cur:
        cur.execute("""
        CREATE TABLE IF NOT EXISTS tfs_weekly_data (
            id SERIAL PRIMARY KEY,
            week_number VARCHAR(10),
            year_2023 NUMERIC(12,2),
            year_2024 NUMERIC(12,2),
            year_2025 NUMERIC(12,2),
            year_2026 NUMERIC(12,2),
            prev_year_pct_change NUMERIC(8,4)
        );
        DROP TABLE IF EXISTS shipment_profile;
        CREATE TABLE shipment_profile (
            id SERIAL PRIMARY KEY,
            shipment_id TEXT, shipment_direction TEXT, shipment_report_date TEXT,
            trans TEXT, customs_info TEXT, mode TEXT, origin TEXT, origin_ctry TEXT,
            destination TEXT, destination_country TEXT, consignor_code TEXT,
            consignor_name TEXT, consignee_code TEXT, consignee_name TEXT,
            house_ref TEXT, incoterm TEXT, additional_terms TEXT, ppd_ccx TEXT,
            goods_description TEXT, origin_etd TEXT, destination_eta TEXT,
            weight TEXT, weight_uq TEXT, volume TEXT, volume_uq TEXT,
            loading_meters TEXT, chargeable TEXT, chargeable_uq TEXT,
            inner_count TEXT, inner_uq TEXT, outer_count TEXT, outer_uq TEXT,
            added TEXT, controlling_customer_code TEXT, controlling_customer_name TEXT,
            controlling_agent_code TEXT, controlling_agent_name TEXT,
            controlling_agent_address TEXT, controlling_agent_country TEXT,
            transport_job TEXT, brokerage_job TEXT, is_master_lead TEXT,
            master_lead_ref TEXT, import_broker_code TEXT, import_broker_name TEXT,
            export_broker_code TEXT, export_broker_name TEXT, job_branch TEXT,
            job_dept TEXT, local_client_code TEXT, local_client_name TEXT,
            job_sales_rep TEXT, job_operator TEXT, job_status TEXT, job_opened TEXT,
            recognized_revenue TEXT, recognized_wip TEXT, total_recognized_income TEXT,
            recognized_cost TEXT, recognized_accrual TEXT, total_recognized_expense TEXT,
            job_profit TEXT, consol_id TEXT, first_load TEXT, last_discharge TEXT,
            etd_first_load TEXT, eta_last_discharge TEXT, master TEXT, vessel TEXT,
            flight_voyage TEXT, load_port TEXT, discharge_port TEXT,
            etd_load TEXT, eta_discharge TEXT, sending_agent_code TEXT,
            sending_agent_name TEXT, receiving_agent TEXT, receiving_agent_name TEXT,
            co_loaded_with TEXT, co_loader_name TEXT, carrier_code TEXT,
            carrier_name TEXT, teu TEXT, container_count TEXT, other TEXT,
            cnt_20f TEXT, cnt_20r TEXT, cnt_20h TEXT, cnt_40f TEXT, cnt_40r TEXT,
            cnt_40h TEXT, cnt_45f TEXT, cnt_gen TEXT, unrecognized_revenue TEXT,
            unrecognized_wip TEXT, unrecognized_cost TEXT, unrecognized_accrual TEXT,
            total_revenue TEXT, total_wip TEXT, total_income TEXT,
            service_level_code TEXT, shippers_reference TEXT, consignor_city TEXT,
            consignor_state TEXT, consignor_postcode TEXT, consignee_city TEXT,
            consignee_state TEXT, consignee_postcode TEXT, consol_atd TEXT,
            consol_ata TEXT, job_revenue_recognition_date TEXT, direction TEXT,
            local_client_ar_group_code TEXT, local_client_ar_group_name TEXT,
            overseas_agent_code TEXT, overseas_agent_name TEXT,
            job_overseas_agent_ar_group_code TEXT,
            job_overseas_agent_ar_group_name TEXT,
            total_cost TEXT, total_accrual TEXT, total_expense TEXT
        );
        CREATE TABLE IF NOT EXISTS customer_spend_operational (
            id SERIAL PRIMARY KEY,
            shipment_id TEXT, shipment_direction TEXT, shipment_report_date TEXT,
            trans TEXT, customs_info TEXT, mode TEXT, origin TEXT, origin_ctry TEXT,
            destination TEXT, destination_country TEXT, consignor_code TEXT,
            consignor_name TEXT, consignee_code TEXT, consignee_name TEXT,
            house_ref TEXT, incoterm TEXT, additional_terms TEXT, ppd_ccx TEXT,
            goods_description TEXT, origin_etd TEXT, destination_eta TEXT,
            weight TEXT, weight_uq TEXT, volume TEXT, volume_uq TEXT,
            loading_meters TEXT, chargeable TEXT, chargeable_uq TEXT,
            inner_count TEXT, inner_uq TEXT, outer_count TEXT, outer_uq TEXT,
            added TEXT, controlling_customer_code TEXT, controlling_customer_name TEXT,
            controlling_agent_code TEXT, controlling_agent_name TEXT,
            controlling_agent_address TEXT, controlling_agent_country TEXT,
            transport_job TEXT, brokerage_job TEXT, is_master_lead TEXT,
            master_lead_ref TEXT, import_broker_code TEXT, import_broker_name TEXT,
            export_broker_code TEXT, export_broker_name TEXT, job_branch TEXT,
            job_dept TEXT, local_client_code TEXT, local_client_name TEXT,
            job_sales_rep TEXT, job_operator TEXT, job_status TEXT, job_opened TEXT,
            recognized_revenue TEXT, recognized_wip TEXT, total_recognized_income TEXT,
            recognized_cost TEXT, recognized_accrual TEXT, total_recognized_expense TEXT,
            job_profit TEXT, consol_id TEXT, first_load TEXT, last_discharge TEXT,
            etd_first_load TEXT, eta_last_discharge TEXT, master TEXT, vessel TEXT,
            flight_voyage TEXT, load_port TEXT, discharge_port TEXT,
            etd_load TEXT, eta_discharge TEXT, sending_agent_code TEXT,
            sending_agent_name TEXT, receiving_agent TEXT, receiving_agent_name TEXT,
            co_loaded_with TEXT, co_loader_name TEXT, carrier_code TEXT,
            carrier_name TEXT, teu TEXT, container_count TEXT, other TEXT,
            cnt_20f TEXT, cnt_20r TEXT, cnt_20h TEXT, cnt_40f TEXT, cnt_40r TEXT,
            cnt_40h TEXT, cnt_45f TEXT, cnt_gen TEXT, unrecognized_revenue TEXT,
            unrecognized_wip TEXT, unrecognized_cost TEXT, unrecognized_accrual TEXT,
            total_revenue TEXT, total_wip TEXT, total_income TEXT,
            service_level_code TEXT, shippers_reference TEXT, consignor_city TEXT,
            consignor_state TEXT, consignor_postcode TEXT, consignee_city TEXT,
            consignee_state TEXT, consignee_postcode TEXT, consol_atd TEXT,
            consol_ata TEXT, job_revenue_recognition_date TEXT, direction TEXT,
            local_client_ar_group_code TEXT, local_client_ar_group_name TEXT,
            overseas_agent_code TEXT, overseas_agent_name TEXT,
            job_overseas_agent_ar_group_code TEXT,
            job_overseas_agent_ar_group_name TEXT,
            total_cost TEXT, total_accrual TEXT, total_expense TEXT
        );
        CREATE TABLE IF NOT EXISTS customer_spend (
            id SERIAL PRIMARY KEY,
            debtor VARCHAR(50) UNIQUE, debtor_name VARCHAR(200), total NUMERIC(14,2)
        );
        -- Ensure UNIQUE constraint exists (for upsert support)
        CREATE UNIQUE INDEX IF NOT EXISTS customer_spend_debtor_key ON customer_spend (debtor);
        -- Year of the source file each operational row came from (for per-file year bucketing)
        ALTER TABLE customer_spend_operational ADD COLUMN IF NOT EXISTS source_year INT;
        """)
    print("Tables verified/created")


def load_tfs_weekly():
    """Load TFS Financial Data sheet into tfs_weekly_data."""
    f = os.path.join(DATA_DIR, 'TFS Weekly Data - Sample.xlsx')
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    ws = wb['TFS Financial Data ']
    rows = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        week = row[0]
        if not week:
            continue
        rows.append((
            str(week),
            float(row[1]) if row[1] else None,
            float(row[2]) if row[2] else None,
            float(row[3]) if row[3] else None,
            float(row[4]) if row[4] else None,
            float(row[5]) if row[5] else None,
        ))
    wb.close()

    with connection.cursor() as cur:
        cur.execute("TRUNCATE tfs_weekly_data RESTART IDENTITY")
        execute_values(cur,
            "INSERT INTO tfs_weekly_data (week_number, year_2023, year_2024, year_2025, year_2026, prev_year_pct_change) VALUES %s",
            rows)
    print(f"tfs_weekly_data: {len(rows)} rows loaded")


def load_shipment_profile():
    """Load Shipment Profile sheet into shipment_profile."""
    f = os.path.join(DATA_DIR, 'Shipment Profile Report for January 2025.xlsx')
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    ws = wb['Shipment Profile']
    rows = []
    for i, row in enumerate(ws.iter_rows(min_row=16, values_only=True), 16):
        # Data starts at column C (index 2)
        vals = list(row[2:])  # skip first 2 empty columns
        if not vals or not vals[0]:
            continue
        # 121 columns mapped to table columns
        def s(v): return str(v).strip() if v else None
        def n(v):
            try: return float(v) if v else None
            except: return None
        def i_val(v):
            try: return int(v) if v else None
            except: return None

        rows.append((
            s(vals[0]),   # shipment_id
            s(vals[1]),   # shipment_direction
            s(vals[2]),   # shipment_report_date
            s(vals[3]),   # trans
            s(vals[4]),   # customs_info
            s(vals[5]),   # mode
            s(vals[6]),   # origin
            s(vals[7]),   # origin_ctry
            s(vals[8]),   # destination
            s(vals[9]),   # destination_country
            s(vals[10]),  # consignor_code
            s(vals[11]),  # consignor_name
            s(vals[12]),  # consignee_code
            s(vals[13]),  # consignee_name
            s(vals[14]),  # house_ref
            s(vals[15]),  # incoterm
            s(vals[16]),  # additional_terms
            s(vals[17]),  # ppd_ccx
            s(vals[18]),  # goods_description
            s(vals[19]),  # origin_etd
            s(vals[20]),  # destination_eta
            n(vals[21]),  # weight
            s(vals[22]),  # weight_uq
            n(vals[23]),  # volume
            s(vals[24]),  # volume_uq
            n(vals[25]),  # loading_meters
            n(vals[26]),  # chargeable
            s(vals[27]),  # chargeable_uq
            n(vals[28]),  # inner_count
            s(vals[29]),  # inner_uq
            n(vals[30]),  # outer_count
            s(vals[31]),  # outer_uq
            s(vals[32]),  # added
            s(vals[33]),  # controlling_customer_code
            s(vals[34]),  # controlling_customer_name
            s(vals[35]),  # controlling_agent_code
            s(vals[36]),  # controlling_agent_name
            s(vals[37]),  # controlling_agent_address
            s(vals[38]),  # controlling_agent_country
            s(vals[39]),  # transport_job
            s(vals[40]),  # brokerage_job
            s(vals[41]),  # is_master_lead
            s(vals[42]),  # master_lead_ref
            s(vals[43]),  # import_broker_code
            s(vals[44]),  # import_broker_name
            s(vals[45]),  # export_broker_code
            s(vals[46]),  # export_broker_name
            s(vals[47]),  # job_branch
            s(vals[48]),  # job_dept
            s(vals[49]),  # local_client_code
            s(vals[50]),  # local_client_name
            s(vals[51]),  # job_sales_rep
            s(vals[52]),  # job_operator
            s(vals[53]),  # job_status
            s(vals[54]),  # job_opened
            n(vals[55]),  # recognized_revenue
            n(vals[56]),  # recognized_wip
            n(vals[57]),  # total_recognized_income
            n(vals[58]),  # recognized_cost
            n(vals[59]),  # recognized_accrual
            n(vals[60]),  # total_recognized_expense
            n(vals[61]),  # job_profit
            s(vals[62]),  # consol_id
            s(vals[63]),  # first_load
            s(vals[64]),  # last_discharge
            s(vals[65]),  # etd_first_load
            s(vals[66]),  # eta_last_discharge
            s(vals[67]),  # master
            s(vals[68]),  # vessel
            s(vals[69]),  # flight_voyage
            s(vals[70]),  # load_port
            s(vals[71]),  # discharge_port
            s(vals[72]),  # etd_load
            s(vals[73]),  # eta_discharge
            s(vals[74]),  # sending_agent_code
            s(vals[75]),  # sending_agent_name
            s(vals[76]),  # receiving_agent
            s(vals[77]),  # receiving_agent_name
            s(vals[78]),  # co_loaded_with
            s(vals[79]),  # co_loader_name
            s(vals[80]),  # carrier_code
            s(vals[81]),  # carrier_name
            n(vals[82]),  # teu
            i_val(vals[83]),  # container_count
            i_val(vals[84]),  # other
            i_val(vals[85]),  # cnt_20f
            i_val(vals[86]),  # cnt_20r
            i_val(vals[87]),  # cnt_20h
            i_val(vals[88]),  # cnt_40f
            i_val(vals[89]),  # cnt_40r
            i_val(vals[90]),  # cnt_40h
            i_val(vals[91]),  # cnt_45f
            i_val(vals[92]),  # cnt_gen
            n(vals[93]),  # unrecognized_revenue
            n(vals[94]),  # unrecognized_wip
            n(vals[95]),  # unrecognized_cost
            n(vals[96]),  # unrecognized_accrual
            n(vals[97]),  # total_revenue
            n(vals[98]),  # total_wip
            n(vals[99]),  # total_income
            s(vals[100]), # service_level_code
            s(vals[101]), # shippers_reference
            s(vals[102]), # consignor_city
            s(vals[103]), # consignor_state
            s(vals[104]), # consignor_postcode
            s(vals[105]), # consignee_city
            s(vals[106]), # consignee_state
            s(vals[107]), # consignee_postcode
            s(vals[108]), # consol_atd
            s(vals[109]), # consol_ata
            s(vals[110]), # job_revenue_recognition_date
            s(vals[111]), # direction
            s(vals[112]), # local_client_ar_group_code
            s(vals[113]), # local_client_ar_group_name
            s(vals[114]), # overseas_agent_code
            s(vals[115]), # overseas_agent_name
            s(vals[116]), # job_overseas_agent_ar_group_code
            s(vals[117]), # job_overseas_agent_ar_group_name
            n(vals[118]), # total_cost
            n(vals[119]), # total_accrual
            n(vals[120]) if len(vals) > 120 else None,  # total_expense
        ))
    wb.close()

    cols = (
        'shipment_id,shipment_direction,shipment_report_date,trans,customs_info,mode,'
        'origin,origin_ctry,destination,destination_country,consignor_code,consignor_name,'
        'consignee_code,consignee_name,house_ref,incoterm,additional_terms,ppd_ccx,'
        'goods_description,origin_etd,destination_eta,weight,weight_uq,volume,volume_uq,'
        'loading_meters,chargeable,chargeable_uq,inner_count,inner_uq,outer_count,outer_uq,'
        'added,controlling_customer_code,controlling_customer_name,controlling_agent_code,'
        'controlling_agent_name,controlling_agent_address,controlling_agent_country,'
        'transport_job,brokerage_job,is_master_lead,master_lead_ref,import_broker_code,'
        'import_broker_name,export_broker_code,export_broker_name,job_branch,job_dept,'
        'local_client_code,local_client_name,job_sales_rep,job_operator,job_status,job_opened,'
        'recognized_revenue,recognized_wip,total_recognized_income,recognized_cost,'
        'recognized_accrual,total_recognized_expense,job_profit,consol_id,first_load,'
        'last_discharge,etd_first_load,eta_last_discharge,master,vessel,flight_voyage,'
        'load_port,discharge_port,etd_load,eta_discharge,sending_agent_code,sending_agent_name,'
        'receiving_agent,receiving_agent_name,co_loaded_with,co_loader_name,carrier_code,'
        'carrier_name,teu,container_count,other,cnt_20f,cnt_20r,cnt_20h,cnt_40f,cnt_40r,'
        'cnt_40h,cnt_45f,cnt_gen,unrecognized_revenue,unrecognized_wip,unrecognized_cost,'
        'unrecognized_accrual,total_revenue,total_wip,total_income,service_level_code,'
        'shippers_reference,consignor_city,consignor_state,consignor_postcode,consignee_city,'
        'consignee_state,consignee_postcode,consol_atd,consol_ata,job_revenue_recognition_date,'
        'direction,local_client_ar_group_code,local_client_ar_group_name,overseas_agent_code,'
        'overseas_agent_name,job_overseas_agent_ar_group_code,job_overseas_agent_ar_group_name,'
        'total_cost,total_accrual,total_expense'
    )

    with connection.cursor() as cur:
        cur.execute("TRUNCATE shipment_profile RESTART IDENTITY")
        execute_values(cur,
            f"INSERT INTO shipment_profile ({cols}) VALUES %s",
            rows, page_size=500)
    print(f"shipment_profile: {len(rows)} rows loaded")


def load_customer_spend_operational():
    """Load Operational Data sheet from 2025 Customer Spend into customer_spend_operational."""
    f = os.path.join(DATA_DIR, '2025 Customer Spend Data .xlsx')
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    ws = wb['Operational Data']
    rows = []
    for row in ws.iter_rows(min_row=16, values_only=True):
        vals = list(row[2:])  # data starts at column C
        if not vals or not vals[0]:
            continue
        def s(v): return str(v).strip() if v else None
        def n(v):
            try: return float(v) if v else None
            except: return None
        def i_val(v):
            try: return int(v) if v else None
            except: return None

        rows.append((
            s(vals[0]), s(vals[1]), s(vals[2]), s(vals[3]), s(vals[4]), s(vals[5]),
            s(vals[6]), s(vals[7]), s(vals[8]), s(vals[9]), s(vals[10]), s(vals[11]),
            s(vals[12]), s(vals[13]), s(vals[14]), s(vals[15]), s(vals[16]), s(vals[17]),
            s(vals[18]), s(vals[19]), s(vals[20]), n(vals[21]), s(vals[22]), n(vals[23]),
            s(vals[24]), n(vals[25]), n(vals[26]), s(vals[27]), n(vals[28]), s(vals[29]),
            n(vals[30]), s(vals[31]), s(vals[32]), s(vals[33]), s(vals[34]), s(vals[35]),
            s(vals[36]), s(vals[37]), s(vals[38]), s(vals[39]), s(vals[40]), s(vals[41]),
            s(vals[42]), s(vals[43]), s(vals[44]), s(vals[45]), s(vals[46]), s(vals[47]),
            s(vals[48]), s(vals[49]), s(vals[50]), s(vals[51]), s(vals[52]), s(vals[53]),
            s(vals[54]), n(vals[55]), n(vals[56]), n(vals[57]), n(vals[58]), n(vals[59]),
            n(vals[60]), n(vals[61]), s(vals[62]), s(vals[63]), s(vals[64]), s(vals[65]),
            s(vals[66]), s(vals[67]), s(vals[68]), s(vals[69]), s(vals[70]), s(vals[71]),
            s(vals[72]), s(vals[73]), s(vals[74]), s(vals[75]), s(vals[76]), s(vals[77]),
            s(vals[78]), s(vals[79]), s(vals[80]), s(vals[81]), n(vals[82]), i_val(vals[83]),
            i_val(vals[84]), i_val(vals[85]), i_val(vals[86]), i_val(vals[87]), i_val(vals[88]),
            i_val(vals[89]), i_val(vals[90]), i_val(vals[91]), i_val(vals[92]),
            n(vals[93]), n(vals[94]), n(vals[95]), n(vals[96]), n(vals[97]), n(vals[98]),
            n(vals[99]), s(vals[100]), s(vals[101]), s(vals[102]), s(vals[103]), s(vals[104]),
            s(vals[105]), s(vals[106]), s(vals[107]), s(vals[108]), s(vals[109]), s(vals[110]),
            s(vals[111]), s(vals[112]), s(vals[113]), s(vals[114]), s(vals[115]),
            s(vals[116]), s(vals[117]), n(vals[118]), n(vals[119]),
            n(vals[120]) if len(vals) > 120 else None,
        ))
    wb.close()

    cols = (
        'shipment_id,shipment_direction,shipment_report_date,trans,customs_info,mode,'
        'origin,origin_ctry,destination,destination_country,consignor_code,consignor_name,'
        'consignee_code,consignee_name,house_ref,incoterm,additional_terms,ppd_ccx,'
        'goods_description,origin_etd,destination_eta,weight,weight_uq,volume,volume_uq,'
        'loading_meters,chargeable,chargeable_uq,inner_count,inner_uq,outer_count,outer_uq,'
        'added,controlling_customer_code,controlling_customer_name,controlling_agent_code,'
        'controlling_agent_name,controlling_agent_address,controlling_agent_country,'
        'transport_job,brokerage_job,is_master_lead,master_lead_ref,import_broker_code,'
        'import_broker_name,export_broker_code,export_broker_name,job_branch,job_dept,'
        'local_client_code,local_client_name,job_sales_rep,job_operator,job_status,job_opened,'
        'recognized_revenue,recognized_wip,total_recognized_income,recognized_cost,'
        'recognized_accrual,total_recognized_expense,job_profit,consol_id,first_load,'
        'last_discharge,etd_first_load,eta_last_discharge,master,vessel,flight_voyage,'
        'load_port,discharge_port,etd_load,eta_discharge,sending_agent_code,sending_agent_name,'
        'receiving_agent,receiving_agent_name,co_loaded_with,co_loader_name,carrier_code,'
        'carrier_name,teu,container_count,other,cnt_20f,cnt_20r,cnt_20h,cnt_40f,cnt_40r,'
        'cnt_40h,cnt_45f,cnt_gen,unrecognized_revenue,unrecognized_wip,unrecognized_cost,'
        'unrecognized_accrual,total_revenue,total_wip,total_income,service_level_code,'
        'shippers_reference,consignor_city,consignor_state,consignor_postcode,consignee_city,'
        'consignee_state,consignee_postcode,consol_atd,consol_ata,job_revenue_recognition_date,'
        'direction,local_client_ar_group_code,local_client_ar_group_name,overseas_agent_code,'
        'overseas_agent_name,job_overseas_agent_ar_group_code,job_overseas_agent_ar_group_name,'
        'total_cost,total_accrual,total_expense'
    )

    with connection.cursor() as cur:
        cur.execute("TRUNCATE customer_spend_operational RESTART IDENTITY")
        execute_values(cur,
            f"INSERT INTO customer_spend_operational ({cols}) VALUES %s",
            rows, page_size=500)
    print(f"customer_spend_operational: {len(rows)} rows loaded")


def load_customer_spend():
    """Load Financial Data sheet into customer_spend."""
    f = os.path.join(DATA_DIR, '2025 Customer Spend Data .xlsx')
    wb = openpyxl.load_workbook(f, read_only=True, data_only=True)
    ws = wb['Financial Data ']
    rows = []
    for row in ws.iter_rows(min_row=14, values_only=True):
        # Data starts at column D (index 3)
        vals = list(row[3:])
        if not vals or not vals[0]:
            continue
        def n(v):
            try: return float(v) if v else None
            except: return None

        debtor = str(vals[0]).strip() if vals[0] else None
        debtor_name = str(vals[1]).strip() if vals[1] else None
        if not debtor:
            continue

        rows.append((
            debtor,
            debtor_name,
            n(vals[2]),   # total
            n(vals[3]),   # 202501
            n(vals[4]),   # 202502
            n(vals[5]),   # 202503
            n(vals[6]),   # 202504
            n(vals[7]),   # 202505
            n(vals[8]),   # 202506
            n(vals[9]),   # 202507
            n(vals[10]),  # 202508
            n(vals[11]),  # 202509
            n(vals[12]) if len(vals) > 12 else None,  # 202510
            n(vals[13]) if len(vals) > 13 else None,  # 202511
            n(vals[14]) if len(vals) > 14 else None,  # 202512
        ))
    wb.close()

    with connection.cursor() as cur:
        cur.execute("TRUNCATE customer_spend RESTART IDENTITY")
        execute_values(cur,
            "INSERT INTO customer_spend (debtor, debtor_name, total, m_202501, m_202502, m_202503, m_202504, m_202505, m_202506, m_202507, m_202508, m_202509, m_202510, m_202511, m_202512) VALUES %s",
            rows)
    print(f"customer_spend: {len(rows)} rows loaded")


OPERATIONAL_COLS = (
    'shipment_id,shipment_direction,shipment_report_date,trans,customs_info,mode,'
    'origin,origin_ctry,destination,destination_country,consignor_code,consignor_name,'
    'consignee_code,consignee_name,house_ref,incoterm,additional_terms,ppd_ccx,'
    'goods_description,origin_etd,destination_eta,weight,weight_uq,volume,volume_uq,'
    'loading_meters,chargeable,chargeable_uq,inner_count,inner_uq,outer_count,outer_uq,'
    'added,controlling_customer_code,controlling_customer_name,controlling_agent_code,'
    'controlling_agent_name,controlling_agent_address,controlling_agent_country,'
    'transport_job,brokerage_job,is_master_lead,master_lead_ref,import_broker_code,'
    'import_broker_name,export_broker_code,export_broker_name,job_branch,job_dept,'
    'local_client_code,local_client_name,job_sales_rep,job_operator,job_status,job_opened,'
    'recognized_revenue,recognized_wip,total_recognized_income,recognized_cost,'
    'recognized_accrual,total_recognized_expense,job_profit,consol_id,first_load,'
    'last_discharge,etd_first_load,eta_last_discharge,master,vessel,flight_voyage,'
    'load_port,discharge_port,etd_load,eta_discharge,sending_agent_code,sending_agent_name,'
    'receiving_agent,receiving_agent_name,co_loaded_with,co_loader_name,carrier_code,'
    'carrier_name,teu,container_count,other,cnt_20f,cnt_20r,cnt_20h,cnt_40f,cnt_40r,'
    'cnt_40h,cnt_45f,cnt_gen,unrecognized_revenue,unrecognized_wip,unrecognized_cost,'
    'unrecognized_accrual,total_revenue,total_wip,total_income,service_level_code,'
    'shippers_reference,consignor_city,consignor_state,consignor_postcode,consignee_city,'
    'consignee_state,consignee_postcode,consol_atd,consol_ata,job_revenue_recognition_date,'
    'direction,local_client_ar_group_code,local_client_ar_group_name,overseas_agent_code,'
    'overseas_agent_name,job_overseas_agent_ar_group_code,job_overseas_agent_ar_group_name,'
    'total_cost,total_accrual,total_expense'
)


def _parse_operational_rows(file_path):
    """Parse operational data rows from an Excel file.
    Tries 'Operational Data' sheet first, then 'Shipment Profile'.
    """
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    if 'Operational Data' in wb.sheetnames:
        ws = wb['Operational Data']
    elif 'Shipment Profile' in wb.sheetnames:
        ws = wb['Shipment Profile']
    else:
        wb.close()
        return []
    rows = []
    for row in ws.iter_rows(min_row=16, values_only=True):
        vals = list(row[2:])  # data starts at column C
        if not vals or not vals[0]:
            continue
        def s(v): return str(v).strip() if v else None
        def n(v):
            try: return float(v) if v else None
            except: return None
        def i_val(v):
            try: return int(v) if v else None
            except: return None

        rows.append((
            s(vals[0]), s(vals[1]), s(vals[2]), s(vals[3]), s(vals[4]), s(vals[5]),
            s(vals[6]), s(vals[7]), s(vals[8]), s(vals[9]), s(vals[10]), s(vals[11]),
            s(vals[12]), s(vals[13]), s(vals[14]), s(vals[15]), s(vals[16]), s(vals[17]),
            s(vals[18]), s(vals[19]), s(vals[20]), n(vals[21]), s(vals[22]), n(vals[23]),
            s(vals[24]), n(vals[25]), n(vals[26]), s(vals[27]), n(vals[28]), s(vals[29]),
            n(vals[30]), s(vals[31]), s(vals[32]), s(vals[33]), s(vals[34]), s(vals[35]),
            s(vals[36]), s(vals[37]), s(vals[38]), s(vals[39]), s(vals[40]), s(vals[41]),
            s(vals[42]), s(vals[43]), s(vals[44]), s(vals[45]), s(vals[46]), s(vals[47]),
            s(vals[48]), s(vals[49]), s(vals[50]), s(vals[51]), s(vals[52]), s(vals[53]),
            s(vals[54]), n(vals[55]), n(vals[56]), n(vals[57]), n(vals[58]), n(vals[59]),
            n(vals[60]), n(vals[61]), s(vals[62]), s(vals[63]), s(vals[64]), s(vals[65]),
            s(vals[66]), s(vals[67]), s(vals[68]), s(vals[69]), s(vals[70]), s(vals[71]),
            s(vals[72]), s(vals[73]), s(vals[74]), s(vals[75]), s(vals[76]), s(vals[77]),
            s(vals[78]), s(vals[79]), s(vals[80]), s(vals[81]), n(vals[82]), i_val(vals[83]),
            i_val(vals[84]), i_val(vals[85]), i_val(vals[86]), i_val(vals[87]), i_val(vals[88]),
            i_val(vals[89]), i_val(vals[90]), i_val(vals[91]), i_val(vals[92]),
            n(vals[93]), n(vals[94]), n(vals[95]), n(vals[96]), n(vals[97]), n(vals[98]),
            n(vals[99]), s(vals[100]), s(vals[101]), s(vals[102]), s(vals[103]), s(vals[104]),
            s(vals[105]), s(vals[106]), s(vals[107]), s(vals[108]), s(vals[109]), s(vals[110]),
            s(vals[111]), s(vals[112]), s(vals[113]), s(vals[114]), s(vals[115]),
            s(vals[116]), s(vals[117]), n(vals[118]), n(vals[119]),
            n(vals[120]) if len(vals) > 120 else None,
        ))
    wb.close()
    return rows


def _parse_customer_spend_rows(file_path):
    """Parse customer spend (Financial Data) rows from an Excel file."""
    wb = openpyxl.load_workbook(file_path, read_only=True, data_only=True)
    if 'Financial Data ' in wb.sheetnames:
        ws = wb['Financial Data ']
    elif 'Financial Data' in wb.sheetnames:
        ws = wb['Financial Data']
    elif 'Turnover-Debtor-Period' in wb.sheetnames:
        ws = wb['Turnover-Debtor-Period']
    else:
        wb.close()
        return []
    rows = []
    for row in ws.iter_rows(min_row=14, values_only=True):
        vals = list(row[3:])  # Data starts at column D (index 3)
        if not vals or not vals[0]:
            continue
        def n(v):
            try: return float(v) if v else None
            except: return None

        debtor = str(vals[0]).strip() if vals[0] else None
        debtor_name = str(vals[1]).strip() if vals[1] else None
        if not debtor:
            continue

        rows.append((
            debtor,
            debtor_name,
            n(vals[2]),   # total
            n(vals[3]),   # 202501
            n(vals[4]),   # 202502
            n(vals[5]),   # 202503
            n(vals[6]),   # 202504
            n(vals[7]),   # 202505
            n(vals[8]),   # 202506
            n(vals[9]),   # 202507
            n(vals[10]),  # 202508
            n(vals[11]),  # 202509
            n(vals[12]) if len(vals) > 12 else None,  # 202510
            n(vals[13]) if len(vals) > 13 else None,  # 202511
            n(vals[14]) if len(vals) > 14 else None,  # 202512
        ))
    wb.close()
    return rows


def upsert_customer_spend(file_path, year=None, progress_callback=None):
    """Load Financial Data from uploaded Excel, upsert into customer_spend.
    Year is extracted from filename if not provided."""
    if year is None:
        year = _extract_year(file_path)
    if not year:
        raise ValueError(f"Cannot determine year from filename: {file_path}")

    if progress_callback:
        progress_callback(f'Parsing {year} Excel file...', 0, 100)

    _ensure_year_columns(year)

    rows = _parse_customer_spend_rows(file_path)
    total = len(rows)

    if progress_callback:
        progress_callback(f'Parsed {total} rows, inserting {year} data...', 10, 100)

    # Build dynamic column names for this year
    month_cols = [f'm_{year}{m:02d}' for m in range(1, 13)]
    total_col = f'total_{year}'
    all_cols = ['debtor', 'debtor_name', total_col] + month_cols
    placeholders = ', '.join(['%s'] * len(all_cols))
    update_sets = ', '.join(
        [f'debtor_name = EXCLUDED.debtor_name', f'{total_col} = EXCLUDED.{total_col}']
        + [f'{c} = EXCLUDED.{c}' for c in month_cols]
    )
    insert_sql = f"""
        INSERT INTO customer_spend ({', '.join(all_cols)})
        VALUES ({placeholders})
        ON CONFLICT (debtor) DO UPDATE SET {update_sets}
    """

    with connection.cursor() as cur:
        for i, row in enumerate(rows):
            # row is (debtor, debtor_name, total, m01..m12)
            cur.execute(insert_sql, row)
            if progress_callback and (i + 1) % 100 == 0:
                pct = 10 + int(80 * (i + 1) / total)
                progress_callback(f'Inserted {i + 1}/{total} rows...', pct, 100)

    if progress_callback:
        progress_callback(f'Customer Spend {year}: {total} rows upserted', 90, 100)

    return total


def upsert_customer_spend_operational(file_path, progress_callback=None, truncate=True):
    """Load Operational Data from uploaded Excel into customer_spend_operational."""
    if progress_callback:
        progress_callback('Parsing Operational Excel file...', 0, 100)

    rows = _parse_operational_rows(file_path)
    total = len(rows)

    if progress_callback:
        progress_callback(f'Parsed {total} rows, loading...', 30, 100)

    with connection.cursor() as cur:
        if truncate:
            cur.execute("TRUNCATE customer_spend_operational RESTART IDENTITY")
        execute_values(cur,
            f"INSERT INTO customer_spend_operational ({OPERATIONAL_COLS}) VALUES %s",
            rows, page_size=500)

    if progress_callback:
        progress_callback(f'Operational: {total} rows loaded', 90, 100)

    return total


def dedupe_operational():
    """Remove exact-duplicate rows from customer_spend_operational.

    The SharePoint shipment files overlap (the same shipments appear in more
    than one file), so appending every file loads each shipment multiple times,
    which doubles every SUM in the report (revenue, profit, KG, ...).  This
    removes rows that are identical in every column except the serial id,
    keeping one copy of each. Job counts use COUNT(DISTINCT shipment_id) so they
    were unaffected; only the summed values were inflated.
    """
    with connection.cursor() as cur:
        cur.execute("""
            DELETE FROM customer_spend_operational
            WHERE id IN (
                SELECT id FROM (
                    SELECT id, ROW_NUMBER() OVER (
                        PARTITION BY (to_jsonb(t.*) - 'id' - 'source_year') ORDER BY id
                    ) AS rn
                    FROM customer_spend_operational t
                ) s WHERE rn > 1
            )
        """)
        removed = cur.rowcount
    print(f"dedupe_operational: removed {removed} duplicate rows")
    return removed


def trim_to_source_year():
    """Keep only rows whose revenue-recognition year matches the year of the file
    they came from (source_year).

    Each yearly shipment file contains some shipments whose revenue is recognised
    in a neighbouring year. Without this, the 2025 file's 2024-recognised rows
    would bleed into the 2024 column (inflating it), and vice-versa. Keeping a row
    only when its recognition year equals its source-file year means each year's
    totals come purely from that year's file — so the report matches each yearly
    Excel. Mirrors the report's date logic (IMM/blank recognition date falls back
    to job_opened). Rows that were never tagged (source_year IS NULL) are dropped.
    """
    date_expr = """CASE WHEN job_revenue_recognition_date = 'IMM'
                            OR job_revenue_recognition_date IS NULL
                       THEN job_opened
                       ELSE job_revenue_recognition_date END"""
    with connection.cursor() as cur:
        cur.execute(f"""
            DELETE FROM customer_spend_operational
            WHERE source_year IS NULL
               OR EXTRACT(YEAR FROM CAST(NULLIF({date_expr}, '') AS DATE))
                  IS DISTINCT FROM source_year
        """)
        removed = cur.rowcount
    print(f"trim_to_source_year: removed {removed} rows")
    return removed


def rebuild_summary_view():
    """Rebuild customer_spend_summary VIEW from operational data, grouped by controlling agent."""
    # Maintained mapping of controlling agent (ORG CODE) -> responsible Sales Rep.
    # The team populates this per org; the report shows blank where unmapped:
    #   INSERT INTO agent_sales_rep (org_code, sales_rep) VALUES ('DHLEXPSYD', 'Jane Doe')
    #     ON CONFLICT (org_code) DO UPDATE SET sales_rep = EXCLUDED.sales_rep;
    with connection.cursor() as cur:
        cur.execute("""CREATE TABLE IF NOT EXISTS agent_sales_rep (
            org_code TEXT PRIMARY KEY,
            sales_rep TEXT
        )""")

    date_expr = """CASE WHEN job_revenue_recognition_date = 'IMM'
                        OR job_revenue_recognition_date IS NULL
                   THEN job_opened
                   ELSE job_revenue_recognition_date END"""

    with connection.cursor() as cur:
        cur.execute(f"""
            SELECT DISTINCT EXTRACT(YEAR FROM CAST(NULLIF({date_expr}, '') AS DATE))::INT AS y
            FROM customer_spend_operational
            WHERE NULLIF({date_expr}, '') IS NOT NULL
            ORDER BY y
        """)
        years = [r[0] for r in cur.fetchall() if r[0] is not None]

    if not years:
        print("No year data found in operational data — skipping view rebuild")
        return

    current_year = years[-1]

    # Blank / missing controlling agent -> "Unassigned" (used in SELECT and GROUP BY
    # so all blank-agent rows collapse into a single Unassigned row).
    agent_name = "COALESCE(NULLIF(TRIM(controlling_agent_name), ''), 'Unassigned')"

    sub = f"""(
        SELECT controlling_agent_code,
               controlling_agent_name,
               EXTRACT(YEAR FROM CAST(NULLIF({date_expr}, '') AS DATE))::INT AS rev_year,
               TO_CHAR(CAST(NULLIF({date_expr}, '') AS DATE), 'YYYY-MM') AS rev_month,
               CAST(NULLIF(total_recognized_income, '') AS NUMERIC) AS recognized_income,
               CAST(NULLIF(job_profit, '') AS NUMERIC) AS profit,
               UPPER(COALESCE(trans, '')) AS trans_mode,
               UPPER(COALESCE(mode, '')) AS ship_mode,
               CASE WHEN chargeable_uq = 'LB' THEN CAST(NULLIF(chargeable, '') AS NUMERIC) * 0.453592
                    ELSE CAST(NULLIF(chargeable, '') AS NUMERIC) END AS chg_kg_val,
               CASE WHEN chargeable_uq = 'M3' THEN CAST(NULLIF(chargeable, '') AS NUMERIC) END AS chg_m3_val,
               CAST(NULLIF(teu, '') AS NUMERIC) AS teu_val,
               shipment_id AS job_ref,
               controlling_customer_code AS cust_ref,
               controlling_agent_country AS agent_country
        FROM customer_spend_operational
        WHERE NULLIF({date_expr}, '') IS NOT NULL
    ) sub"""

    select_cols = [
        'controlling_agent_code AS "ORG CODE"',
        f'{agent_name} AS "CONTROLLING AGENT"',
        'MAX(agent_country) AS "COUNTRY"',
        "COALESCE(NULLIF(MAX(asr.sales_rep), ''), 'Unassigned') AS \"SALES REP\"",
    ]

    for y in years:
        select_cols.append(
            f"ROUND(COALESCE(SUM(CASE WHEN rev_year = {y} THEN recognized_income END), 0), 2) AS \"Revenue {y}\""
        )
        select_cols.append(
            f"ROUND(COALESCE(SUM(CASE WHEN rev_year = {y} THEN profit END), 0), 2) AS \"Profit {y}\""
        )
        select_cols.append(
            f"ROUND(COALESCE(SUM(CASE WHEN rev_year = {y} THEN profit END), 0) "
            f"/ NULLIF(SUM(CASE WHEN rev_year = {y} THEN recognized_income END), 0) * 100, 1) AS \"Profit % {y}\""
        )
        select_cols.append(
            f"COUNT(DISTINCT CASE WHEN rev_year = {y} THEN cust_ref END) AS \"Customers {y}\""
        )

    for y in years:
        for m in range(1, 13):
            mn = MONTH_NAMES[m - 1]
            ms = f'{y}-{m:02d}'
            select_cols.append(
                f"ROUND(COALESCE(SUM(CASE WHEN rev_month = '{ms}' THEN recognized_income END), 0), 2) AS \"{y} {mn} REV\""
            )
            select_cols.append(
                f"ROUND(COALESCE(SUM(CASE WHEN rev_month = '{ms}' THEN profit END), 0), 2) AS \"{y} {mn} PROFIT\""
            )
            select_cols.append(
                f"ROUND(COALESCE(SUM(CASE WHEN rev_month = '{ms}' THEN profit END), 0) "
                f"/ NULLIF(SUM(CASE WHEN rev_month = '{ms}' THEN recognized_income END), 0) * 100, 1) AS \"{y} {mn} Profit %\""
            )
            select_cols.append(
                f"COUNT(DISTINCT CASE WHEN rev_month = '{ms}' THEN job_ref END) AS \"{y} {mn} Job No\""
            )
            select_cols.append(
                f"COUNT(DISTINCT CASE WHEN rev_month = '{ms}' THEN cust_ref END) AS \"{y} {mn} Customers\""
            )
            select_cols.append(
                f"ROUND(COALESCE(SUM(CASE WHEN rev_month = '{ms}' AND trans_mode = 'AIR' THEN chg_kg_val END), 0))::INT AS \"{y} {mn} Chg KG\""
            )
            select_cols.append(
                f"ROUND(COALESCE(SUM(CASE WHEN rev_month = '{ms}' AND ship_mode IN ('LCL', 'LTL') THEN chg_m3_val END), 0))::INT AS \"{y} {mn} Chg M3\""
            )
            select_cols.append(
                f"ROUND(COALESCE(SUM(CASE WHEN rev_month = '{ms}' AND ship_mode IN ('FCL', 'FTL', 'BBK') THEN teu_val END), 0))::INT AS \"{y} {mn} TEU\""
            )

    sql = f"""DROP VIEW IF EXISTS customer_spend_summary;
CREATE VIEW customer_spend_summary AS
SELECT
    {(',' + chr(10) + '    ').join(select_cols)}
FROM {sub}
LEFT JOIN agent_sales_rep asr ON asr.org_code = sub.controlling_agent_code
GROUP BY controlling_agent_code, {agent_name}
ORDER BY SUM(CASE WHEN rev_year = {current_year} THEN recognized_income END) DESC NULLS LAST;"""

    with connection.cursor() as cur:
        cur.execute(sql)

    # Build revenue_by_sales_rep view — one row per rep per year
    rep_sql = """
    DROP VIEW IF EXISTS revenue_by_sales_rep;
    CREATE VIEW revenue_by_sales_rep AS
    SELECT
        job_sales_rep AS "SALES REP",
        EXTRACT(YEAR FROM CAST(NULLIF(
            CASE WHEN job_revenue_recognition_date = 'IMM' OR job_revenue_recognition_date IS NULL
                 THEN job_opened
                 ELSE job_revenue_recognition_date END
        , '') AS DATE))::INT AS "YEAR",
        SUM(CAST(NULLIF(recognized_revenue, '') AS NUMERIC)) AS "REVENUE",
        SUM(CAST(NULLIF(job_profit, '') AS NUMERIC)) AS "PROFIT",
        COUNT(DISTINCT shipment_id) AS "JOBS"
    FROM customer_spend_operational
    WHERE job_sales_rep IS NOT NULL AND job_sales_rep != ''
    GROUP BY job_sales_rep,
             EXTRACT(YEAR FROM CAST(NULLIF(
                 CASE WHEN job_revenue_recognition_date = 'IMM' OR job_revenue_recognition_date IS NULL
                      THEN job_opened
                      ELSE job_revenue_recognition_date END
             , '') AS DATE))
    ORDER BY "REVENUE" DESC NULLS LAST;
    """
    with connection.cursor() as cur:
        cur.execute(rep_sql)
    print("revenue_by_sales_rep view rebuilt")

    # Build monthly_revenue_trend view — one row per month per year per rep per customer
    date_expr = """CASE WHEN job_revenue_recognition_date = 'IMM' OR job_revenue_recognition_date IS NULL
                        THEN job_opened
                        ELSE job_revenue_recognition_date END"""
    trend_sql = f"""
    DROP VIEW IF EXISTS monthly_revenue_trend;
    CREATE VIEW monthly_revenue_trend AS
    SELECT
        controlling_customer_code AS "CUSTOMER CODE",
        controlling_customer_name AS "CUSTOMER NAME",
        job_sales_rep AS "SALES REP",
        EXTRACT(YEAR FROM CAST(NULLIF({date_expr}, '') AS DATE))::INT AS "YEAR",
        EXTRACT(MONTH FROM CAST(NULLIF({date_expr}, '') AS DATE))::INT AS "MONTH NUM",
        TO_CHAR(CAST(NULLIF({date_expr}, '') AS DATE), 'MON') AS "MONTH",
        SUM(CAST(NULLIF(recognized_revenue, '') AS NUMERIC)) AS "REVENUE",
        SUM(CAST(NULLIF(job_profit, '') AS NUMERIC)) AS "PROFIT",
        COUNT(DISTINCT shipment_id) AS "JOBS",
        SUM(CASE WHEN weight_uq = 'LB' THEN CAST(NULLIF(weight, '') AS NUMERIC) * 0.453592
                 ELSE CAST(NULLIF(weight, '') AS NUMERIC) END) AS "ACT KG",
        SUM(CASE WHEN chargeable_uq = 'LB' THEN CAST(NULLIF(chargeable, '') AS NUMERIC) * 0.453592
                 WHEN chargeable_uq = 'CF' THEN CAST(NULLIF(chargeable, '') AS NUMERIC) * 0.0283168
                 ELSE CAST(NULLIF(chargeable, '') AS NUMERIC) END) AS "CHG KG",
        SUM(CASE WHEN volume_uq = 'CF' THEN CAST(NULLIF(volume, '') AS NUMERIC) * 0.0283168
                 ELSE CAST(NULLIF(volume, '') AS NUMERIC) END) AS "ACT M3",
        SUM(CAST(NULLIF(teu, '') AS NUMERIC)) AS "TEU"
    FROM customer_spend_operational
    WHERE job_sales_rep IS NOT NULL AND job_sales_rep != ''
    GROUP BY controlling_customer_code, controlling_customer_name, job_sales_rep,
             EXTRACT(YEAR FROM CAST(NULLIF({date_expr}, '') AS DATE)),
             EXTRACT(MONTH FROM CAST(NULLIF({date_expr}, '') AS DATE)),
             TO_CHAR(CAST(NULLIF({date_expr}, '') AS DATE), 'MON')
    ORDER BY "YEAR", "MONTH NUM";
    """
    with connection.cursor() as cur:
        cur.execute(trend_sql)
    print("monthly_revenue_trend view rebuilt")

    # Build customer_spend_trend view — tidy/long, one row per controlling agent
    # per month, with a real PERIOD date for time-series (trading) charts. Uses
    # the same measure rules as the main report: KG=AIR, M3=LCL/LTL, TEU=FCL/FTL/BBK.
    agent_trend_sql = f"""
    DROP VIEW IF EXISTS customer_spend_trend;
    CREATE VIEW customer_spend_trend AS
    SELECT
        controlling_agent_code AS "ORG CODE",
        {agent_name} AS "CONTROLLING AGENT",
        MAX(agent_country) AS "COUNTRY",
        COALESCE(NULLIF(MAX(asr.sales_rep), ''), 'Unassigned') AS "SALES REP",
        make_date(rev_year, rev_month_num, 1) AS "PERIOD",
        rev_year AS "YEAR",
        rev_month_num AS "MONTH NUM",
        TO_CHAR(make_date(rev_year, rev_month_num, 1), 'Mon') AS "MONTH",
        ROUND(SUM(recognized_income), 2) AS "REVENUE",
        ROUND(SUM(profit), 2) AS "PROFIT",
        ROUND(SUM(profit) / NULLIF(SUM(recognized_income), 0) * 100, 1) AS "PROFIT %",
        COUNT(DISTINCT job_ref) AS "JOBS",
        COUNT(DISTINCT cust_ref) AS "CUSTOMERS",
        ROUND(COALESCE(SUM(CASE WHEN trans_mode = 'AIR' THEN chg_kg_val END), 0))::INT AS "CHG KG",
        ROUND(COALESCE(SUM(CASE WHEN ship_mode IN ('LCL', 'LTL') THEN chg_m3_val END), 0))::INT AS "CHG M3",
        ROUND(COALESCE(SUM(CASE WHEN ship_mode IN ('FCL', 'FTL', 'BBK') THEN teu_val END), 0))::INT AS "TEU"
    FROM (
        SELECT controlling_agent_code, controlling_agent_name,
               EXTRACT(YEAR FROM CAST(NULLIF({date_expr}, '') AS DATE))::INT AS rev_year,
               EXTRACT(MONTH FROM CAST(NULLIF({date_expr}, '') AS DATE))::INT AS rev_month_num,
               CAST(NULLIF(total_recognized_income, '') AS NUMERIC) AS recognized_income,
               CAST(NULLIF(job_profit, '') AS NUMERIC) AS profit,
               UPPER(COALESCE(trans, '')) AS trans_mode,
               UPPER(COALESCE(mode, '')) AS ship_mode,
               CASE WHEN chargeable_uq = 'LB' THEN CAST(NULLIF(chargeable, '') AS NUMERIC) * 0.453592
                    ELSE CAST(NULLIF(chargeable, '') AS NUMERIC) END AS chg_kg_val,
               CAST(NULLIF(chargeable, '') AS NUMERIC) AS chg_m3_val,
               CAST(NULLIF(teu, '') AS NUMERIC) AS teu_val,
               shipment_id AS job_ref,
               controlling_customer_code AS cust_ref,
               controlling_agent_country AS agent_country
        FROM customer_spend_operational
        WHERE NULLIF({date_expr}, '') IS NOT NULL
    ) t
    LEFT JOIN agent_sales_rep asr ON asr.org_code = t.controlling_agent_code
    GROUP BY controlling_agent_code, {agent_name}, rev_year, rev_month_num
    ORDER BY "CONTROLLING AGENT", "PERIOD";
    """
    with connection.cursor() as cur:
        cur.execute(agent_trend_sql)
    print("customer_spend_trend view rebuilt")

    # Build monthly_active_customers view — distinct active customers per month.
    # A distinct count can't be summed from the agent-level trend (a customer
    # using two agents would be double-counted), so this is its own view: one
    # row per month with the business-wide count of distinct controlling
    # customers that had a shipment that month. PERIOD is a real date for charts.
    active_cust_sql = f"""
    DROP VIEW IF EXISTS monthly_active_customers;
    CREATE VIEW monthly_active_customers AS
    SELECT
        make_date(rev_year, rev_month_num, 1) AS "PERIOD",
        rev_year AS "YEAR",
        rev_month_num AS "MONTH NUM",
        TO_CHAR(make_date(rev_year, rev_month_num, 1), 'Mon') AS "MONTH",
        COUNT(DISTINCT customer_code) AS "ACTIVE CUSTOMERS"
    FROM (
        SELECT controlling_customer_code AS customer_code,
               EXTRACT(YEAR FROM CAST(NULLIF({date_expr}, '') AS DATE))::INT AS rev_year,
               EXTRACT(MONTH FROM CAST(NULLIF({date_expr}, '') AS DATE))::INT AS rev_month_num
        FROM customer_spend_operational
        WHERE NULLIF({date_expr}, '') IS NOT NULL
          AND controlling_customer_code IS NOT NULL
          AND controlling_customer_code != ''
    ) t
    GROUP BY rev_year, rev_month_num
    ORDER BY "PERIOD";
    """
    with connection.cursor() as cur:
        cur.execute(active_cust_sql)
    print("monthly_active_customers view rebuilt")

    print(f"customer_spend_summary view rebuilt with years: {years}")
    return years


if __name__ == '__main__':
    print("Loading Up-Down Trader Report data...")
    ensure_tables()
    load_tfs_weekly()
    load_shipment_profile()
    load_customer_spend_operational()
    load_customer_spend()
    dedupe_operational()
    rebuild_summary_view()
    print("Done!")
