from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0028_create_dfw_pnl_table'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE TABLE IF NOT EXISTS import_ops (
                id SERIAL PRIMARY KEY,
                shipment_id VARCHAR(500),
                shipment_direction VARCHAR(500),
                report_date VARCHAR(500),
                trans VARCHAR(500),
                customs_info VARCHAR(500),
                mode VARCHAR(500),
                origin VARCHAR(500),
                origin_country VARCHAR(500),
                destination VARCHAR(500),
                destination_country VARCHAR(500),
                consignor_code VARCHAR(500),
                consignor_name VARCHAR(500),
                consignee_code VARCHAR(500),
                consignee_name VARCHAR(500),
                house_ref VARCHAR(500),
                incoterm VARCHAR(500),
                additional_terms VARCHAR(500),
                ppd_ccx VARCHAR(500),
                goods_description VARCHAR(500),
                origin_etd VARCHAR(500),
                destination_eta VARCHAR(500),
                weight VARCHAR(500),
                weight_unit VARCHAR(500)
            );

            CREATE INDEX IF NOT EXISTS idx_import_ops_shipment_id ON import_ops(shipment_id);
            CREATE INDEX IF NOT EXISTS idx_import_ops_mode ON import_ops(mode);
            CREATE INDEX IF NOT EXISTS idx_import_ops_origin_country ON import_ops(origin_country);
            CREATE INDEX IF NOT EXISTS idx_import_ops_destination_country ON import_ops(destination_country);
            """,
            reverse_sql="DROP TABLE IF EXISTS import_ops;"
        ),
    ]