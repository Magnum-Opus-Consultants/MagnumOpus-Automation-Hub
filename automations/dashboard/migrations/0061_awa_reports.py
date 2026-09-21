"""The CargoWise report runs move from a JSON file on disk into the database.

State the scripts kept in output/_status.json is adopted on first read by
awa_reports.import_legacy_state(), so nothing that has been running daily for
months appears as "never run".
"""
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('dashboard', '0060_clientsite_template'),
    ]

    operations = [
        migrations.CreateModel(
            name='AwaReportState',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('script', models.CharField(max_length=100, unique=True)),
                ('name', models.CharField(max_length=200)),
                ('run_days', models.CharField(blank=True, default='', max_length=20)),
                ('is_enabled', models.BooleanField(default=True)),
                ('last_outcome', models.CharField(blank=True, default='',
                                                  max_length=12)),
                ('last_run_at', models.DateTimeField(blank=True, null=True)),
                ('last_success_at', models.DateTimeField(blank=True, null=True)),
                ('last_rows', models.IntegerField(blank=True, null=True)),
                ('last_error', models.TextField(blank=True, default='')),
                ('consecutive_failures', models.IntegerField(default=0)),
            ],
            options={
                'db_table': 'awa_report_state',
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='AwaReportRun',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True,
                                           serialize=False, verbose_name='ID')),
                ('script', models.CharField(db_index=True, max_length=100)),
                ('name', models.CharField(max_length=200)),
                ('outcome', models.CharField(
                    choices=[('ok', 'Updated'), ('failed', 'Failed'),
                             ('skipped', 'Not scheduled today')], max_length=12)),
                ('rows', models.IntegerField(blank=True, null=True)),
                ('error', models.TextField(blank=True, default='')),
                ('log_tail', models.TextField(blank=True, default='')),
                ('duration_seconds', models.FloatField(blank=True, null=True)),
                ('started_at', models.DateTimeField(db_index=True)),
                ('finished_at', models.DateTimeField(blank=True, null=True)),
                ('batch', models.CharField(blank=True, db_index=True, default='',
                                           max_length=40)),
                ('triggered_by', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='awa_report_runs', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'db_table': 'awa_report_run',
                'ordering': ['-started_at', 'script'],
            },
        ),
        migrations.AddIndex(
            model_name='awareportrun',
            index=models.Index(fields=['script', '-started_at'],
                               name='awa_report__script_4efbd6_idx'),
        ),
    ]
