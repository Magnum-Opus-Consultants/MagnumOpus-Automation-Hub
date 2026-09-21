"""
One-time cleanup of USEUContact records before go-live:
  1. Remove duplicate emails (keep the first, delete the rest)
  2. Clear TP2-TP10 data from all contacts (touchpoint_N, tpN_sent_on)
  3. Preserve TP1 sent data so those contacts are NOT re-sent
  4. Reset last_touch to '1' for contacts who received TP1, '' for others

Usage:
    python manage.py clean_contacts --dry-run   # preview changes
    python manage.py clean_contacts              # apply changes
"""
from django.core.management.base import BaseCommand
from django.db.models import Count
from dashboard.models import USEUContact


class Command(BaseCommand):
    help = 'Clean contact records: remove duplicates, clear TP2-10 data, preserve TP1'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help='Preview changes without applying them')

    def handle(self, *args, **options):
        dry = options['dry_run']
        tag = '[DRY-RUN] ' if dry else ''

        # ── 1. Remove duplicate emails ──────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n{tag}Step 1: Remove duplicate emails'))

        dupes = (
            USEUContact.objects
            .exclude(email='').exclude(email__isnull=True)
            .values('email')
            .annotate(cnt=Count('id'))
            .filter(cnt__gt=1)
        )
        total_deleted = 0
        for entry in dupes:
            email = entry['email']
            contacts = list(
                USEUContact.objects.filter(email__iexact=email).order_by('id')
            )
            keep = contacts[0]
            to_delete = contacts[1:]
            self.stdout.write(f'  {email}: keeping id={keep.id}, deleting {len(to_delete)} duplicate(s)')
            if not dry:
                USEUContact.objects.filter(id__in=[c.id for c in to_delete]).delete()
            total_deleted += len(to_delete)

        self.stdout.write(self.style.SUCCESS(f'  {tag}Removed {total_deleted} duplicate contacts'))

        # ── 2. Clear TP2-TP10 data ──────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n{tag}Step 2: Clear TP2-TP10 data from all contacts'))

        update_fields = {}
        for n in range(2, 11):
            update_fields[f'touchpoint_{n}'] = ''
            update_fields[f'tp{n}_sent_on'] = ''

        total_contacts = USEUContact.objects.count()
        if not dry:
            USEUContact.objects.all().update(**update_fields)
        self.stdout.write(self.style.SUCCESS(f'  {tag}Cleared TP2-TP10 fields on {total_contacts} contacts'))

        # ── 3. Fix last_touch ────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n{tag}Step 3: Fix last_touch column'))

        tp1_sent = USEUContact.objects.exclude(tp1_sent_on='').exclude(tp1_sent_on__isnull=True)
        tp1_not_sent = USEUContact.objects.filter(tp1_sent_on='') | USEUContact.objects.filter(tp1_sent_on__isnull=True)

        tp1_count = tp1_sent.count()
        other_count = tp1_not_sent.count()

        if not dry:
            tp1_sent.update(last_touch='1')
            tp1_not_sent.update(last_touch='')

        self.stdout.write(self.style.SUCCESS(
            f'  {tag}Set last_touch="1" for {tp1_count} contacts (TP1 sent), '
            f'cleared last_touch for {other_count} contacts'
        ))

        # ── Summary ──────────────────────────────────────────────────────
        self.stdout.write(self.style.MIGRATE_HEADING(f'\n{tag}Summary:'))
        self.stdout.write(f'  Duplicates removed: {total_deleted}')
        self.stdout.write(f'  TP2-10 data cleared on: {total_contacts} contacts')
        self.stdout.write(f'  TP1 preserved for: {tp1_count} contacts')
        if dry:
            self.stdout.write(self.style.WARNING('\n  Run without --dry-run to apply changes.'))
        else:
            self.stdout.write(self.style.SUCCESS('\n  All changes applied successfully.'))
