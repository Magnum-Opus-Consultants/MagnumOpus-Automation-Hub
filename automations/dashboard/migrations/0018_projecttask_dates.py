from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0017_project_task'),
    ]

    operations = [
        migrations.AddField(
            model_name='projecttask',
            name='start_date',
            field=models.DateField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='projecttask',
            name='end_date',
            field=models.DateField(blank=True, null=True),
        ),
    ]
