import json
from datetime import time, timedelta
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from dashboard.models import ProjectTask


class Command(BaseCommand):
    help = "Create ProjectTask entries for upcoming recurring reports (from reports_schedule.json)"

    def add_arguments(self, parser):
        parser.add_argument(
            '--days', type=int, default=7,
            help='Number of days ahead to seed (default 7).'
        )

    def handle(self, *args, **options):
        cfg_path = Path(__file__).resolve().parents[3] / 'reports_schedule.json'
        with cfg_path.open() as f:
            cfg = json.load(f)

        hh, mm = cfg.get('default_time', '15:00').split(':')
        report_time = time(int(hh), int(mm))
        ehh, emm = cfg.get('default_end_time', '17:00').split(':')
        report_end_time = time(int(ehh), int(emm))
        project_name = cfg.get('project_name', 'Weekly Reports')
        priority = cfg.get('priority', 'high')
        company = cfg.get('company', '')
        schedule = cfg['schedule']

        today = timezone.localtime().date()
        days_ahead = options['days']
        total_created = 0
        total_skipped = 0

        total_removed = 0
        for offset in range(days_ahead + 1):
            day = today + timedelta(days=offset)
            weekday = day.strftime('%A').lower()
            titles = set(schedule.get(weekday, []))

            # Reconcile: drop any Weekly Reports tasks for this day that no longer
            # belong in the schedule — but never touch tasks already marked done.
            stale = ProjectTask.objects.filter(
                project_name=project_name,
                start_date=day,
            ).exclude(status='done').exclude(title__in=titles)
            total_removed += stale.count()
            stale.delete()

            for title in titles:
                existing = ProjectTask.objects.filter(
                    title=title,
                    project_name=project_name,
                    start_date=day,
                ).first()
                if existing:
                    # Keep completed tasks as-is; otherwise sync times to match config.
                    if existing.status != 'done' and (
                        existing.start_time != report_time or existing.end_time != report_end_time
                    ):
                        existing.start_time = report_time
                        existing.end_time = report_end_time
                        existing.save(update_fields=['start_time', 'end_time'])
                    total_skipped += 1
                    continue
                ProjectTask.objects.create(
                    title=title,
                    project_name=project_name,
                    status='todo',
                    priority=priority,
                    company=company,
                    start_date=day,
                    end_date=day,
                    start_time=report_time,
                    end_time=report_end_time,
                )
                total_created += 1

        self.stdout.write(
            f"Seeded next {days_ahead} days from {today}: "
            f"created {total_created}, skipped {total_skipped} (already existed), "
            f"removed {total_removed} stale."
        )
