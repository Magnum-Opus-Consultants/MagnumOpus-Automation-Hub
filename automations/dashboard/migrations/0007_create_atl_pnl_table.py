from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0006_create_con_pnl_table'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE TABLE IF NOT EXISTS atl_pnl (
                    id SERIAL PRIMARY KEY,
                    division VARCHAR(50),
                    account_name VARCHAR(255),
                    value DECIMAL(15, 2),
                    date BIGINT,
                    date_fixed VARCHAR(50),
                    budget_actual VARCHAR(50),
                    week VARCHAR(50),
                    report_date DATE,
                    UNIQUE(division, account_name, date, week, budget_actual)
                );

                CREATE INDEX IF NOT EXISTS idx_atl_pnl_division ON atl_pnl(division);
                CREATE INDEX IF NOT EXISTS idx_atl_pnl_budget_actual ON atl_pnl(budget_actual);
                CREATE INDEX IF NOT EXISTS idx_atl_pnl_date ON atl_pnl(date);
            """,
            reverse_sql="DROP TABLE IF EXISTS atl_pnl;"
        ),
    ]
