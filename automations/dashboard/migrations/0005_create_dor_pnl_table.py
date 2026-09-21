# Generated migration to create DOR P&L table

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0004_add_date_fixed_and_budget_actual'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE TABLE dor_pnl (
                    id SERIAL PRIMARY KEY,
                    division VARCHAR(50),
                    account_name TEXT,
                    value NUMERIC(15, 2),
                    date INTEGER,
                    date_fixed DATE,
                    budget_actual VARCHAR(20),
                    week VARCHAR(20),
                    report_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(division, account_name, date, week, budget_actual)
                );

                CREATE INDEX idx_dor_division ON dor_pnl(division);
                CREATE INDEX idx_dor_date ON dor_pnl(date);
                CREATE INDEX idx_dor_week ON dor_pnl(week);
                CREATE INDEX idx_dor_report_date ON dor_pnl(report_date);
                CREATE INDEX idx_dor_date_fixed ON dor_pnl(date_fixed);
                CREATE INDEX idx_dor_budget_actual ON dor_pnl(budget_actual);
            """,
            reverse_sql="DROP TABLE IF EXISTS dor_pnl CASCADE;"
        )
    ]
