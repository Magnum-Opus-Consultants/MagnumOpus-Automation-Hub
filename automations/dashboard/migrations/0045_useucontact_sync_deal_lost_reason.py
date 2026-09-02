"""Record useu_contacts.deal_lost_reason in Django's migration state.

The column already exists (varchar(500), nullable, default '') but no migration
ever recorded it, so `makemigrations` regenerated an AddField for it on every
run — a migration that fails with "column already exists" if actually applied.
That is why the same operation shows up in the names of 0037/0038/0039 and why
0043 had to leave it out.

State-only: `database_operations` is empty because the column is already there.
This makes `makemigrations --check` clean and removes the failing-migration trap.
"""
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0044_projecttask_sync_existing_columns'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            database_operations=[],   # column already present — nothing to run
            state_operations=[
                migrations.AddField(
                    model_name='useucontact',
                    name='deal_lost_reason',
                    field=models.CharField(blank=True, default='', max_length=500),
                ),
            ],
        ),
    ]
