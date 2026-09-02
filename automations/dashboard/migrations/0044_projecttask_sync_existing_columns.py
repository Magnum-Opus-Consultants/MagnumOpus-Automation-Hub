"""Bring Django's migration state in line with the existing projecttask table.

`dashboard_projecttask` already has `company`, `start_time` and `end_time` — they
were added to the database outside of migrations, so no migration ever recorded
them and the model had drifted away from the table. dashboard/views.py still
writes all three, which meant task creation raised TypeError.

The fields are now declared on the model, so this migration records that in
state only: `database_operations` is deliberately empty because running the
AddFields would fail with "column already exists".
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0043_useucontact_deal_lost_reason_repository_domain'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],   # columns already present — nothing to run
            state_operations=[
                migrations.AddField(
                    model_name='projecttask',
                    name='company',
                    field=models.CharField(
                        blank=True, default='', max_length=20,
                        choices=[
                            ('magnum_opus', 'Magnum Opus Consultants'),
                            ('food_safety', 'Food Safety Agency'),
                            ('eclick', 'E-Click'),
                        ],
                    ),
                ),
                migrations.AddField(
                    model_name='projecttask',
                    name='start_time',
                    field=models.TimeField(blank=True, null=True),
                ),
                migrations.AddField(
                    model_name='projecttask',
                    name='end_time',
                    field=models.TimeField(blank=True, null=True),
                ),
            ],
        ),
    ]
