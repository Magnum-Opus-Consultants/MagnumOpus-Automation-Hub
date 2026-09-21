import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0018_projecttask_dates'),
    ]

    operations = [
        migrations.AddField(
            model_name='projecttask',
            name='parent',
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.SET_NULL,
                related_name='subtasks',
                to='dashboard.projecttask',
            ),
        ),
    ]
