from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0011_create_imp_pnl_table'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE TABLE IF NOT EXISTS hou_pnl (
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

            CREATE INDEX IF NOT EXISTS idx_hou_pnl_date ON hou_pnl(date);
            CREATE INDEX IF NOT EXISTS idx_hou_pnl_week ON hou_pnl(week);
            CREATE INDEX IF NOT EXISTS idx_hou_pnl_budget_actual ON hou_pnl(budget_actual);
            """,
            reverse_sql="DROP TABLE IF EXISTS hou_pnl;"
        ),
    ]
