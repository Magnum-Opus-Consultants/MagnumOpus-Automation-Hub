"""Make the release a pass belongs to required.

Split from 0077 because PostgreSQL refuses to ALTER a table in the same
transaction that has just written rows to it ("pending trigger events"), and
0077 backfills every existing pass with a release first.
"""
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0077_iterations_belong_to_a_release'),
    ]

    operations = [
        migrations.AlterField(
            model_name='testiteration',
            name='version',
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.CASCADE,
                related_name='iterations', to='dashboard.testversion'),
        ),
    ]
