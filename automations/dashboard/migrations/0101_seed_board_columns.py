"""Seed the board's six columns from the constants they used to be.

Keys, order, which statuses each column holds and which of them hide when
empty all match what the frontend had hard-coded, so the board looks and
behaves exactly as it did the moment before this ran.
"""
from django.db import migrations

# key, label, colour, is_done, extra statuses, hide when empty
COLUMNS = [
    ('backlog', 'Backlog', 'slate', False, [], True),
    ('todo', 'To Do', 'blue', False, [], False),
    ('in_progress', 'In Progress', 'blue', False, ['in_progress_guidance'], False),
    ('review', 'Review', 'amber', False, ['review_pending', 'discrepancy'], False),
    ('on_hold', 'On Hold', 'red', False, [], True),
    ('done', 'Done', 'green', True, ['cancelled'], False),
]


def seed(apps, schema_editor):
    BoardColumn = apps.get_model('dashboard', 'BoardColumn')
    for i, (key, label, colour, is_done, extra, hide) in enumerate(COLUMNS):
        BoardColumn.objects.update_or_create(
            key=key,
            defaults={
                'label': label, 'order': i, 'colour': colour, 'is_done': is_done,
                'builtin': True, 'extra_statuses': extra, 'hide_when_empty': hide,
            },
        )


def unseed(apps, schema_editor):
    # Only the built-in six go. A column somebody added is their data, and
    # tasks may be sitting in it; reversing this migration must not take it.
    apps.get_model('dashboard', 'BoardColumn').objects.filter(builtin=True).delete()


class Migration(migrations.Migration):
    dependencies = [('dashboard', '0100_boardcolumn_alter_projecttask_status')]
    operations = [migrations.RunPython(seed, unseed)]
