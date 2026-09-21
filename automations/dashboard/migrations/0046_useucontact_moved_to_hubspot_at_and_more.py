"""Reconcile USEUContact with the columns production already carries.

This branch forked from the deployed lineage at 0036, so it never recorded
server migrations 0037 (moved_to_hubspot_at) or 0041 (opted_out_at).

`moved_to_hubspot_at` and its index are already present in the database, so
that field is synced into migration state only. `opted_out_at` genuinely does
not exist here yet and is added for real.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0045_useucontact_sync_deal_lost_reason'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],
            state_operations=[
                migrations.AddField(
                    model_name='useucontact',
                    name='moved_to_hubspot_at',
                    field=models.DateTimeField(blank=True, db_index=True, null=True),
                ),
            ],
        ),
        migrations.AddField(
            model_name='useucontact',
            name='opted_out_at',
            field=models.DateTimeField(blank=True, db_index=True, null=True),
        ),
        # Choices only - no DDL.
        migrations.AlterField(
            model_name='useucontact',
            name='status',
            field=models.CharField(
                choices=[
                    ('Active', 'Active'),
                    ('Undeliverable', 'Undeliverable'),
                    ('Inactive', 'Inactive'),
                    ('Lost', 'Lost'),
                    ('Move to HubSpot', 'Move to HubSpot'),
                ],
                default='Active',
                max_length=20,
            ),
        ),
    ]
