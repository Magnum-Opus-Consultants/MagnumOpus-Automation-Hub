"""Turn workspace-level lists into projects.

Work used to be filed as lists inside a workspace (Food Safety Agency >
"Debitor System"), with no project. Sentinel is built around projects - each
has its own overview, tasks, feedback, website, server and so on - and the
sidebar lists projects, so a list on its own has none of that and does not
show up. This makes each workspace list a project of the same name in the
same workspace, with the workspace as its client, and moves the list's tasks
(and their subtasks) into it. Inside the project those tasks sit in the
default "General" list rather than a list repeating the project's name.

Dry run by default - it prints what it would do. Pass --apply to do it, in
one transaction. Back up the database first.

    python manage.py convert_workspace_lists            # preview
    python manage.py convert_workspace_lists --apply
"""
from collections import Counter

from django.core.management.base import BaseCommand
from django.db import transaction
from django.db.models import Q

from dashboard.models import ProjectList, ProjectMeta, ProjectTask


class Command(BaseCommand):
    help = 'Turn workspace-level lists into projects (dry run unless --apply).'

    def add_arguments(self, parser):
        parser.add_argument('--apply', action='store_true', help='Make the changes.')

    def handle(self, *args, apply=False, **options):
        lists = list(ProjectList.objects.filter(workspace__isnull=False, project_name='')
                     .select_related('workspace').order_by('workspace__name', 'name'))
        if not lists:
            self.stdout.write('No workspace lists - nothing to do.')
            return

        # A list name used in two workspaces can't become one project name
        # without guessing which tasks are whose, so those are left alone.
        dupes = {n for n, c in Counter(pl.name for pl in lists).items() if c > 1}

        with transaction.atomic():
            for pl in lists:
                ws, name = pl.workspace, pl.name
                if name in dupes:
                    self.stdout.write(self.style.WARNING(
                        f'  skip "{name}" ({ws.name}): the same list name is in more than one workspace'))
                    continue
                existing = ProjectMeta.objects.filter(name=name).first()
                if existing and existing.workspace_id not in (None, ws.pk):
                    self.stdout.write(self.style.WARNING(
                        f'  skip "{name}" ({ws.name}): a project of that name is in another workspace'))
                    continue
                tasks = ProjectTask.objects.filter(project_name='', list_name=name).filter(
                    Q(workspace=ws) | Q(workspace__isnull=True))
                n = tasks.count()
                self.stdout.write(f'  {ws.name} / {name}: project {"exists" if existing else "new"}, '
                                  f'{n} task{"" if n == 1 else "s"} to move')
                if not apply:
                    continue
                if existing is None:
                    ProjectMeta.objects.create(name=name, workspace=ws, client=ws.name)
                elif existing.workspace_id is None or not existing.client:
                    existing.workspace = ws
                    existing.client = existing.client or ws.name
                    existing.save(update_fields=['workspace', 'client'])
                tasks.update(project_name=name, list_name='')
                pl.delete()

            if not apply:
                self.stdout.write(self.style.NOTICE('Dry run - nothing changed. Run again with --apply.'))
                transaction.set_rollback(True)
            else:
                self.stdout.write(self.style.SUCCESS('Done.'))
