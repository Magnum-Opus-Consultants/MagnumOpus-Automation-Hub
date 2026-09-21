from django.apps import AppConfig
import os
import sys


class DashboardConfig(AppConfig):
    name = 'dashboard'

    def ready(self):
        # Start scheduler in the right process:
        # - In dev (runserver): only in the reloader child (RUN_MAIN=true), not the parent
        # - In production (gunicorn/uwsgi): always start (runserver is not in sys.argv)
        is_runserver = len(sys.argv) > 1 and sys.argv[1] == 'runserver'

        if not is_runserver or os.environ.get('RUN_MAIN') == 'true':
            from . import scheduler
            scheduler.start_scheduler()
