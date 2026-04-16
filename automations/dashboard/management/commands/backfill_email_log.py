"""Backfill EmailSendLog from USEUContact.tp{N}_sent_on fields.

Run on each env (local/server): python manage.py backfill_email_log
Safe to re-run — skips rows already logged.
"""
from datetime import datetime
from django.core.management.base import BaseCommand
from dashboard.models import USEUContact, EmailSendLog


class Command(BaseCommand):
    help = 'Seed EmailSendLog with historical sends tracked on USEUContact.tp{N}_sent_on'

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true', help='Report counts without writing')
        parser.add_argument('--provider', default='ses', help='Provider tag for historical entries')

    def handle(self, *args, **opts):
        dry = opts['dry_run']
        provider = opts['provider']
        existing = set(
            EmailSendLog.objects.values_list('contact_id', 'touchpoint_number')
        )
        to_create = []
        skipped = 0
        for c in USEUContact.objects.all().iterator():
            for tp in range(1, 11):
                raw = (getattr(c, f'tp{tp}_sent_on', '') or '').strip()
                if not raw:
                    continue
                if (c.id, tp) in existing:
                    skipped += 1
                    continue
                dt = self._parse(raw)
                status = 'delivered'
                if (c.status or '').lower() == 'undeliverable':
                    status = 'bounced'
                to_create.append(EmailSendLog(
                    contact=c,
                    to_address=c.email or '',
                    from_address='waldogaybba@moc-pty.com',
                    touchpoint_number=tp,
                    subject=f'TP{tp} (historical backfill)',
                    provider=provider,
                    status=status,
                    message_id=f'backfill-{c.id}-tp{tp}',
                    sent_at=dt or datetime.utcnow(),
                ))
        self.stdout.write(f'To insert: {len(to_create)} | already logged: {skipped}')
        if dry:
            self.stdout.write(self.style.WARNING('Dry run — nothing written'))
            return
        BATCH = 2000
        for i in range(0, len(to_create), BATCH):
            EmailSendLog.objects.bulk_create(to_create[i:i+BATCH], ignore_conflicts=True)
        # Fix sent_at since auto_now_add overrides it on bulk_create — requery and update
        for row in to_create:
            if row.sent_at and row.id is None:
                EmailSendLog.objects.filter(message_id=row.message_id).update(sent_at=row.sent_at)
        self.stdout.write(self.style.SUCCESS(f'Inserted {len(to_create)} rows'))

    @staticmethod
    def _parse(s):
        for fmt in ('%d-%m-%Y %H:%M', '%d-%m-%Y', '%Y-%m-%d %H:%M', '%Y-%m-%d',
                    '%d/%m/%Y %H:%M', '%d/%m/%Y', '%m/%d/%Y'):
            try:
                return datetime.strptime(s, fmt)
            except ValueError:
                continue
        return None
