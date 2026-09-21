# Generated migration to add date_fixed and budget_actual columns

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0003_update_ppg_for_period_analysis'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                ALTER TABLE ppg_pnl
                ADD COLUMN date_fixed DATE,
                ADD COLUMN budget_actual VARCHAR(20);

                CREATE INDEX idx_ppg_date_fixed ON ppg_pnl(date_fixed);
                CREATE INDEX idx_ppg_budget_actual ON ppg_pnl(budget_actual);
            """,
            reverse_sql="""
                DROP INDEX IF EXISTS idx_ppg_date_fixed;
                DROP INDEX IF EXISTS idx_ppg_budget_actual;
                ALTER TABLE ppg_pnl DROP COLUMN IF EXISTS date_fixed;
                ALTER TABLE ppg_pnl DROP COLUMN IF EXISTS budget_actual;
            """
        )
    ]
