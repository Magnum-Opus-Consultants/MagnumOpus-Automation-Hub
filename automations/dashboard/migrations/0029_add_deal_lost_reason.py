from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0028_create_dfw_pnl_table'),
    ]

    operations = [
        migrations.RunSQL(
            sql="ALTER TABLE useu_contacts ADD COLUMN IF NOT EXISTS deal_lost_reason VARCHAR(500) DEFAULT '';",
            reverse_sql="ALTER TABLE useu_contacts DROP COLUMN IF EXISTS deal_lost_reason;"
        ),
    ]
