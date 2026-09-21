from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0019_projecttask_parent'),
    ]

    operations = [
        migrations.AddField(
            model_name='projecttask',
            name='project_name',
            field=models.CharField(blank=True, default='', max_length=100),
        ),
    ]
