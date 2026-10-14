from django.apps import AppConfig
import os
import sys


class DashboardConfig(AppConfig):
    name = 'dashboard'

    def ready(self):
        # Start the scheduler in exactly one process: the web server.
        # - Production: gunicorn.
        # - Dev (runserver): only the reloader child (RUN_MAIN=true), not the parent.
        # Every other process that loads the app - manage.py console_proxy (the
        # sentinel-console service), migrate, shell, one-off scripts - must not,
        # or each one runs every job a second time. Two schedulers wrote the same
        # report workbooks at the same moment and uploaded them half-written
        # (KPIU.xlsx, 14 Oct 2026: "Bad CRC-32"). SCHEDULER_ENABLED=1 forces it.
        argv0 = os.path.basename(sys.argv[0]) if sys.argv else ''
        is_runserver = len(sys.argv) > 1 and sys.argv[1] == 'runserver'
        start = ('gunicorn' in argv0
                 or (is_runserver and os.environ.get('RUN_MAIN') == 'true')
                 or os.environ.get('SCHEDULER_ENABLED') == '1')

        if start:
            from . import scheduler
            scheduler.start_scheduler()
