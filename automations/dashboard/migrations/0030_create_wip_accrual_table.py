from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0029_create_import_ops_table'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
            CREATE TABLE IF NOT EXISTS wip_accrual (
                id SERIAL PRIMARY KEY,
                type VARCHAR(500),
                branch VARCHAR(500),
                dept VARCHAR(500),
                charge_code VARCHAR(500),
                job VARCHAR(500),
                local_ref VARCHAR(500),
                wip VARCHAR(500),
                accrual VARCHAR(500),
                net_total VARCHAR(500),
                added VARCHAR(500),
                age VARCHAR(500),
                debtor_creditor VARCHAR(500),
                stat VARCHAR(500),
                job_branch VARCHAR(500),
                controlling_agent VARCHAR(500),
                controlling_customer VARCHAR(500),
                management_group VARCHAR(500),
                exp_group VARCHAR(500),
                orig VARCHAR(500),
                eta VARCHAR(500),
                etd VARCHAR(500),
                posted_by VARCHAR(500),
                posted_by_fullname VARCHAR(500)
            );

            CREATE INDEX IF NOT EXISTS idx_wip_accrual_branch ON wip_accrual(branch);
            CREATE INDEX IF NOT EXISTS idx_wip_accrual_dept ON wip_accrual(dept);
            CREATE INDEX IF NOT EXISTS idx_wip_accrual_job ON wip_accrual(job);
            CREATE INDEX IF NOT EXISTS idx_wip_accrual_type ON wip_accrual(type);
            """,
            reverse_sql="DROP TABLE IF EXISTS wip_accrual;"
        ),
    ]