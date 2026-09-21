from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0014_create_lax_pnl_table'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE TABLE IF NOT EXISTS lcl_pnl (
                id SERIAL PRIMARY KEY,
                division VARCHAR(50),
                account_name VARCHAR(255),
                value DECIMAL(15, 2),
                date INTEGER,
                date_fixed VARCHAR(50),
                budget_actual VARCHAR(50),
                week VARCHAR(50),
                report_date DATE,
                UNIQUE(division, account_name, date, week, budget_actual)
            );

            CREATE INDEX IF NOT EXISTS idx_lcl_pnl_date ON lcl_pnl(date);
            CREATE INDEX IF NOT EXISTS idx_lcl_pnl_week ON lcl_pnl(week);
            CREATE INDEX IF NOT EXISTS idx_lcl_pnl_budget_actual ON lcl_pnl(budget_actual);
            """,
            reverse_sql="DROP TABLE IF EXISTS lcl_pnl;"
        ),
    ]
