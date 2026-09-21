# Generated migration to create TFS Weekly Data table

from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0031_merge_20260323_1554'),
    ]

    operations = [
        migrations.RunSQL(
            sql="""
                CREATE TABLE tfs_weekly (
                    id SERIAL PRIMARY KEY,
                    week_number VARCHAR(10) NOT NULL,
                    year INTEGER NOT NULL,
                    revenue NUMERIC(15, 2),
                    miles NUMERIC(15, 2),
                    revenue_per_mile NUMERIC(10, 4),
                    revenue_per_truck NUMERIC(15, 2),
                    utilization_pct NUMERIC(5, 4),
                    yoy_change NUMERIC(8, 4),
                    num_trucks INTEGER DEFAULT 32,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(week_number, year)
                );

                CREATE INDEX idx_tfs_week ON tfs_weekly(week_number);
                CREATE INDEX idx_tfs_year ON tfs_weekly(year);
            """,
            reverse_sql="DROP TABLE IF EXISTS tfs_weekly CASCADE;"
        )
    ]
