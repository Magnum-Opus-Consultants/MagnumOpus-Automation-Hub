"""Seed dummy USEUContact rows so the Reporting page has something to show.

All emails use example.com / example.org / example.net (RFC 2606 reserved —
never routable, never resolves to a real inbox).

Usage:
    py manage.py seed_reporting_demo          # add demo rows (keeps existing data)
    py manage.py seed_reporting_demo --wipe   # delete existing contacts first
    py manage.py seed_reporting_demo --count 300
"""
import random
from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from dashboard.models import USEUContact, EmailSendLog


FIRST_NAMES = [
    "Alex", "Jordan", "Taylor", "Morgan", "Riley", "Casey", "Sam", "Avery",
    "Quinn", "Parker", "Hayden", "Rowan", "Dakota", "Sage", "Emerson", "Finley",
    "River", "Blair", "Drew", "Ellis", "Kai", "Noa", "Reese", "Skylar",
    "Harper", "Cameron", "Logan", "Jamie", "Micah", "Shay",
]
LAST_NAMES = [
    "Stone", "Rivers", "Hale", "Vance", "Reyes", "Archer", "Winters", "Bloom",
    "Cross", "Hart", "Lane", "Webb", "Fox", "Pierce", "Ward", "Brooks",
    "Hayes", "Kent", "Quinn", "Sparks", "Wells", "Knox", "Blake", "Locke",
    "North", "Dune", "Ashford", "Mercer", "Holt", "Finch",
]
ORG_PREFIX = [
    "Meridian", "Northwind", "Harborline", "Vertex", "Continental", "Atlas",
    "Summit", "Beacon", "Coastal", "Skyline", "Cascade", "Ironhill",
    "Stonebridge", "Trident", "Horizon", "Foundry", "Oakwave", "Granite",
    "Silverline", "Anchor", "Pinnacle", "Lantern", "Keystone", "Brightwater",
    "Falcon", "Seabridge", "Globalnet", "Polar", "Ridgepoint", "Edgewater",
]
ORG_SUFFIX = [
    "Logistics (demo)", "Freight (demo)", "Shipping (demo)", "Forwarding (demo)",
    "Global (demo)", "Cargo (demo)", "Express (demo)", "Transit (demo)",
    "Supply Chain (demo)", "Worldwide (demo)",
]
EMAIL_DOMAINS = ["example.com", "example.org", "example.net"]

LOST_REASONS = [
    "Not the right contact",
    "Already using a competitor",
    "Budget constraints",
    "No in-house freight team",
    "Asked to unsubscribe",
    "Company restructuring",
    "Out of scope region",
    "Duplicate contact",
]

# SES-style error strings: "{Type}/{SubType}: {diagnostic}"
HARD_BOUNCE_ERRORS = [
    "Permanent/General: smtp; 550 5.1.1 user unknown",
    "Permanent/NoEmail: smtp; 550 5.1.1 recipient address rejected",
    "Permanent/Suppressed: on SES suppression list",
]
SOFT_BOUNCE_ERRORS = [
    "Transient/General: smtp; 421 4.7.0 deferred",
    "Transient/MailboxFull: smtp; 452 4.2.2 mailbox full",
    "Transient/MessageTooLarge: smtp; 552 5.3.4 message size exceeds",
]


class Command(BaseCommand):
    help = "Seed demo contacts (RFC-reserved fake emails) with a year+ of HubSpot migration data."

    def add_arguments(self, parser):
        parser.add_argument('--wipe', action='store_true', help='Delete all existing USEUContact rows first')
        parser.add_argument('--count', type=int, default=250, help='Total demo contacts to create (default 250)')

    def handle(self, *args, **opts):
        if opts['wipe']:
            deleted, _ = USEUContact.objects.all().delete()
            EmailSendLog.objects.all().delete()
            self.stdout.write(self.style.WARNING(f"Wiped {deleted} existing contacts (and demo email logs)."))

        count = opts['count']
        now = timezone.now()
        rng = random.Random(42)

        # Distribution (proportions, rounded to count):
        #   Active 55%, Moved to HubSpot 22%, Undeliverable 15%, Lost 8%
        n_hs = round(count * 0.22)
        n_und = round(count * 0.15)
        n_lost = round(count * 0.08)
        n_active = count - n_hs - n_und - n_lost

        plan = (
            ['Active'] * n_active
            + ['Moved to HubSpot'] * n_hs
            + ['Undeliverable'] * n_und
            + ['Lost'] * n_lost
        )
        rng.shuffle(plan)

        # Spread HubSpot moves over ~450 days so both monthly (13+ buckets)
        # and yearly (2+ buckets) charts have meaningful data.
        hubspot_offsets = []
        for _ in range(n_hs):
            # Slight bias toward more recent months (ramp-up curve)
            r = rng.random() ** 0.75  # skewed toward 0 → recent days
            hubspot_offsets.append(int(r * 450) + rng.randint(0, 5))
        hubspot_offsets.sort(reverse=True)
        hs_iter = iter(hubspot_offsets)

        created = 0
        for i, status in enumerate(plan):
            first = rng.choice(FIRST_NAMES)
            last = rng.choice(LAST_NAMES)
            org = f"{rng.choice(ORG_PREFIX)} {rng.choice(ORG_SUFFIX)}"
            # RFC-2606 reserved domain → guaranteed not a real mailbox
            email = f"{first.lower()}.{last.lower()}{rng.randint(10, 999)}@{rng.choice(EMAIL_DOMAINS)}"

            moved_at = None
            if status == 'Moved to HubSpot':
                offset = next(hs_iter, rng.randint(30, 400))
                moved_at = now - timedelta(days=offset, hours=rng.randint(0, 23), minutes=rng.randint(0, 59))

            # Touchpoint coverage: simulate a funnel where later TPs have fewer sends.
            # Active contacts tend to progress further; Lost/Undeliverable drop off earlier.
            if status == 'Active':
                max_tp_reached = rng.choices(range(0, 11), weights=[2, 3, 5, 7, 9, 11, 10, 8, 7, 6, 5])[0]
            elif status == 'Moved to HubSpot':
                max_tp_reached = rng.choices(range(1, 11), weights=[1, 3, 6, 8, 9, 9, 8, 7, 6, 5])[0]
            elif status == 'Undeliverable':
                max_tp_reached = rng.choices(range(0, 4), weights=[3, 10, 6, 3])[0]
            else:  # Lost
                max_tp_reached = rng.choices(range(0, 8), weights=[2, 4, 6, 7, 6, 4, 3, 2])[0]

            tp_fields = {}
            last_touch = ''
            if max_tp_reached > 0:
                base_days = rng.randint(200, 400)
                for n in range(1, max_tp_reached + 1):
                    d = now - timedelta(days=max(1, base_days - (n - 1) * 14 - rng.randint(0, 6)))
                    tp_fields[f'touchpoint_{n}'] = 'Sent'
                    tp_fields[f'tp{n}_sent_on'] = d.strftime('%d/%m/%Y')
                last_touch = str(max_tp_reached)

            # Deal lost reason: most Lost contacts get one, some other statuses sometimes.
            deal_lost_reason = ''
            if status == 'Lost' and rng.random() < 0.85:
                deal_lost_reason = rng.choice(LOST_REASONS)
            elif status in ('Undeliverable', 'Moved to HubSpot') and rng.random() < 0.15:
                deal_lost_reason = rng.choice(LOST_REASONS)

            contact = USEUContact.objects.create(
                org_name=org,
                contact_name=f"{first} {last}",
                email=email,
                phone=f"+1{rng.randint(2000000000, 9999999999)}",
                status=status,
                last_touch=last_touch,
                deal_lost_reason=deal_lost_reason,
                moved_to_hubspot_at=moved_at,
                **tp_fields,
            )

            # For Undeliverable contacts, create a bounce log entry (hard or soft)
            if status == 'Undeliverable':
                # 70% hard, 25% soft, 5% undetermined — mirrors typical SES mix
                r = rng.random()
                if r < 0.70:
                    err = rng.choice(HARD_BOUNCE_ERRORS)
                elif r < 0.95:
                    err = rng.choice(SOFT_BOUNCE_ERRORS)
                else:
                    err = "Undetermined/Undetermined: reason unknown"
                tp_for_log = max(1, max_tp_reached)
                bounce_when = now - timedelta(days=rng.randint(1, 300), hours=rng.randint(0, 23))
                log = EmailSendLog.objects.create(
                    contact=contact,
                    to_address=email,
                    from_address='demo@example.com',
                    touchpoint_number=tp_for_log,
                    subject=f'Touchpoint {tp_for_log} (demo)',
                    provider='ses',
                    status='bounced',
                    error_message=err,
                )
                # bypass auto_now_add by updating directly
                EmailSendLog.objects.filter(id=log.id).update(sent_at=bounce_when, status_updated_at=bounce_when)

            created += 1

        self.stdout.write(self.style.SUCCESS(f"Created {created} demo contacts."))

        from django.db.models import Count
        self.stdout.write("\nCurrent status breakdown:")
        for row in USEUContact.objects.values('status').annotate(c=Count('id')).order_by('-c'):
            self.stdout.write(f"  {row['status']}: {row['c']}")

        hs = USEUContact.objects.filter(moved_to_hubspot_at__isnull=False)
        self.stdout.write(f"\nContacts with HubSpot timestamp: {hs.count()}")
        if hs.exists():
            earliest = hs.order_by('moved_to_hubspot_at').first().moved_to_hubspot_at
            latest = hs.order_by('-moved_to_hubspot_at').first().moved_to_hubspot_at
            self.stdout.write(f"  Range: {earliest.strftime('%Y-%m-%d')} → {latest.strftime('%Y-%m-%d')}")
