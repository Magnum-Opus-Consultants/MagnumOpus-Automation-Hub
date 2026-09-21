from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0033_fix_ccd_pnl_structure'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE TABLE IF NOT EXISTS condor_pnl (
                id SERIAL PRIMARY KEY,
                division VARCHAR(50),
                account_name TEXT,
                value DECIMAL(15, 2),
                date INTEGER,
                week VARCHAR(50),
                report_date DATE,
                created_at TIMESTAMP DEFAULT NOW(),
                date_fixed DATE,
                budget_actual VARCHAR(50),
                UNIQUE(division, account_name, date, week, budget_actual)
            );

            CREATE INDEX IF NOT EXISTS idx_condor_pnl_date ON condor_pnl(date);
            CREATE INDEX IF NOT EXISTS idx_condor_pnl_week ON condor_pnl(week);
            CREATE INDEX IF NOT EXISTS idx_condor_pnl_budget_actual ON condor_pnl(budget_actual);
            """,
            reverse_sql="DROP TABLE IF EXISTS condor_pnl;"
        ),
    ]
