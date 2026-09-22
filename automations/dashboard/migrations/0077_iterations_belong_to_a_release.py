"""A release is a sheet: every pass now belongs to one.

Testing runs per build. Version 1 is tested, the issues that did not pass are
carried into version 2 when it ships, and each release keeps its own sheet and
its own readiness figure. That only works if every pass is attached to a
release, so this backfills the ones recorded before releases existed.

Areas with no release at all get one called "Initial" - they were tested against
something, it just was not written down. Areas that already have a chain get
their existing passes attached to the latest build in it: the verdicts in an
imported workbook are the final ones, recorded after the last build landed.
"""
from django.db import migrations


def forward(apps, schema_editor):
    TestArea = apps.get_model('dashboard', 'TestArea')
    TestVersion = apps.get_model('dashboard', 'TestVersion')
    TestIteration = apps.get_model('dashboard', 'TestIteration')

    for area in TestArea.objects.all():
        versions = list(area.versions.order_by('order', 'id'))
        if not versions:
            versions = [TestVersion.objects.create(
                area=area, label='Initial', order=0)]
        latest = versions[-1]
        TestIteration.objects.filter(
            item__area=area, version__isnull=True).update(version=latest)


def backward(apps, schema_editor):
    # Nothing to undo: the column simply becomes nullable again.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('dashboard', '0076_test_iterations'),
    ]

    operations = [
        migrations.RunPython(forward, backward),
    ]
