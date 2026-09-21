from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0032_create_tfs_weekly_table'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            -- Convert date_fixed from varchar to date (matching ppg_pnl structure)
            ALTER TABLE ccd_pnl
                ALTER COLUMN date_fixed TYPE date
                USING date_fixed::timestamp::date;

            -- Convert account_name from varchar to text (matching ppg_pnl structure)
            ALTER TABLE ccd_pnl
                ALTER COLUMN account_name TYPE text;
            """,
            reverse_sql="""
            ALTER TABLE ccd_pnl
                ALTER COLUMN date_fixed TYPE varchar(50)
                USING date_fixed::varchar;
            ALTER TABLE ccd_pnl
                ALTER COLUMN account_name TYPE varchar(255);
            """
        ),
    ]
