# Generated migration for PPG Period Analysis structure

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0002_revert_ppg_to_original_structure'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                DROP TABLE IF EXISTS ppg_pnl CASCADE;

                CREATE TABLE ppg_pnl (
                    id SERIAL PRIMARY KEY,
                    division VARCHAR(50),
                    account_name TEXT,
                    value NUMERIC(15, 2),
                    date INTEGER,
                    week VARCHAR(20),
                    report_date DATE,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(division, account_name, date, week)
                );

                CREATE INDEX idx_ppg_division ON ppg_pnl(division);
                CREATE INDEX idx_ppg_date ON ppg_pnl(date);
                CREATE INDEX idx_ppg_week ON ppg_pnl(week);
                CREATE INDEX idx_ppg_report_date ON ppg_pnl(report_date);
            """,
            reverse_sql="DROP TABLE IF EXISTS ppg_pnl CASCADE;"
        )
    ]
