from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0005_create_dor_pnl_table'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE TABLE IF NOT EXISTS con_pnl (
                    id SERIAL PRIMARY KEY,
                    division VARCHAR(50),
                    account_name TEXT,
                    value NUMERIC,
                    date INTEGER,
                    week VARCHAR(20),
                    report_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    date_fixed DATE,
                    budget_actual VARCHAR(20),
                    UNIQUE(division, account_name, date, week, budget_actual)
                );

                CREATE INDEX IF NOT EXISTS idx_con_pnl_date ON con_pnl(date);
                CREATE INDEX IF NOT EXISTS idx_con_pnl_division ON con_pnl(division);
                CREATE INDEX IF NOT EXISTS idx_con_pnl_week ON con_pnl(week);
                CREATE INDEX IF NOT EXISTS idx_con_pnl_budget_actual ON con_pnl(budget_actual);
            """,
            reverse_sql="DROP TABLE IF EXISTS con_pnl CASCADE;"
        ),
    ]
