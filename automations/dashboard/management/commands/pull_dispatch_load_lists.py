"""Pull dispatch load lists the way Bruce's CargoWise grid views list them.

    python manage.py pull_dispatch_load_lists

Reproduces the saved grid view "DOR EXTERNAL CUTOFF TODAY":

  * CTO cut off date is today
  * Booking party has NONE of these EXACT words SCM
  * Last discharge port is blank

with the grid's columns: weight, packages, staged and loaded counts, vehicle.
Every active load list with a cut-off from 30 days back to 7 ahead is stored,
flagged in_external_view (the view above, less its date) and in_awa_view (its
counterpart, "DOR AWA CUTOFF TODAY"), and cutoff_today marks the ones whose
cut-off falls today. "Today" is counted in the time zone of the CargoWise
profile the views are read in, so the list matches that screen.

The booking party is not on the load list but on its dispatch consignments,
and the totals come from DispatchLoadListPropertiesViews - the same figures
the grid shows.
"""
import datetime as dt
import re
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from dashboard.cargowise import CargoWise, CargoWiseError
from dashboard.models import DispatchLoadList

DAYS_BACK = 30
DAYS_AHEAD = 7
DCN_EXTRA_DAYS = 30
PROPS_BATCH = 15
VIEW_BOOKING_WORD = re.compile(r'\bSCM\b', re.IGNORECASE)

SELECT = 'WDL_PK,WDL_JobID,WDL_ReferenceNumber,WDL_CTOCutOffTime,WDL_RL_NKLastDischargePort'
EXPAND = ("ReferenceNumbers($filter=CE_EntryType eq 'MAB';$select=CE_EntryNum),"
          "WhsItemDispatchLoadListDTUPivots($expand=TransitDispatchTransportationUnit("
          "$select=WDH_VehicleReference,WDH_UnitType))")
DCN_EXPAND = ("Addresses($filter=E2_AddressType eq 'BKD';$select=E2_AddressType;"
              "$expand=Address($select=OA_Code;$expand=OrgHeader($select=OH_FullName))),"
              "WhsItemPackageStates($select=WPS_WDL_LoadList)")


class Command(BaseCommand):
    help = 'Pull dispatch load lists as the CargoWise grid views list them.'

    def add_arguments(self, parser):
        parser.add_argument('--branches', default='DOR',
                            help='Comma-separated branch codes (default DOR).')
        parser.add_argument('--tz', default='Africa/Johannesburg',
                            help="Time zone the grid's 'today' is counted in.")
        parser.add_argument('--username', default=None)
        parser.add_argument('--password', default=None)
        parser.add_argument('--dry-run', action='store_true',
                            help='Fetch and report, but write nothing.')

    def handle(self, *args, **opts):
        branches = [b.strip().upper() for b in opts['branches'].split(',') if b.strip()]
        try:
            tz = ZoneInfo(opts['tz'])
        except Exception:
            raise CommandError(f'Unknown time zone {opts["tz"]}')
        try:
            cw = CargoWise(username=opts['username'], password=opts['password']).login()
        except CargoWiseError as e:
            raise CommandError(str(e))
        self.stdout.write(f'authenticated as {cw.display_name}')

        today = timezone.now().astimezone(tz).date()
        start = dt.datetime.combine(today - dt.timedelta(days=DAYS_BACK), dt.time(), tz)
        end = dt.datetime.combine(today + dt.timedelta(days=DAYS_AHEAD + 1), dt.time(), tz)
        filt = (f"WDL_IsActive eq true and WDL_CTOCutOffTime ge {_iso(start)}"
                f" and WDL_CTOCutOffTime lt {_iso(end)}")
        dcn_filt = f"WDC_SystemCreateTimeUtc ge {_iso(start - dt.timedelta(days=DCN_EXTRA_DAYS))}"

        now = timezone.now()
        built = []
        for code in branches:
            if code not in cw.branches:
                self.stdout.write(self.style.WARNING(f'  {code}: not available to this user, skipped'))
                continue
            try:
                cw.select_branch(code)
                rows = cw.page('WhsItemDispatchLoadLists',
                               {'$filter': filt, '$select': SELECT, '$expand': EXPAND,
                                '$orderby': 'WDL_JobID'})
                dcns = cw.page('WhsItemDispatchConsignments',
                               {'$filter': dcn_filt, '$select': 'WDC_ConsignmentID',
                                '$expand': DCN_EXPAND})
                props = {}
                pks = [r['WDL_PK'] for r in rows]
                for i in range(0, len(pks), PROPS_BATCH):
                    f = ' or '.join(f'WDL_PK eq {pk}' for pk in pks[i:i + PROPS_BATCH])
                    for p in cw.get('DispatchLoadListPropertiesViews', {'$filter': f}).get('value', []):
                        props[p['WDL_PK']] = p
            except CargoWiseError as e:
                raise CommandError(f'{code}: {e}')
            parties = booking_parties(dcns)
            for r in rows:
                built.append(build(code, r, props.get(r['WDL_PK'], {}),
                                   parties.get(r['WDL_PK'], set()), today, tz, now))
            self.stdout.write(f'  {code}: {len(rows)} load list(s)')

        today_ext = [b for b in built if b.cutoff_today and b.in_external_view]
        self.stdout.write(f'{len(built)} load list(s); {len(today_ext)} in DOR EXTERNAL CUTOFF TODAY')
        if opts['dry_run']:
            self.stdout.write(self.style.WARNING('dry run - nothing written'))
            for b in today_ext:
                self.stdout.write(f'    {b.load_list} {b.reference} {b.cto_cutoff_local}')
            return
        self._store(built)
        self.stdout.write(self.style.SUCCESS(f'{len(built)} row(s) stored.'))

    @transaction.atomic
    def _store(self, built):
        fields = [f.name for f in DispatchLoadList._meta.concrete_fields
                  if f.name not in ('id', 'load_list')]
        DispatchLoadList.objects.bulk_create(built, batch_size=500, update_conflicts=True,
                                             unique_fields=['load_list'], update_fields=fields)
        # "Today" moves on; a row this pull did not see is not today's any more.
        DispatchLoadList.objects.exclude(load_list__in=[b.load_list for b in built]) \
            .update(cutoff_today=False)


def booking_parties(dcns):
    """Load list PK -> booking parties of the consignments its packages left on."""
    out = {}
    for c in dcns:
        names = {((a.get('Address') or {}).get('OrgHeader') or {}).get('OH_FullName') or ''
                 for a in c.get('Addresses', [])} - {''}
        for pk in {p.get('WPS_WDL_LoadList') for p in c.get('WhsItemPackageStates', [])}:
            if pk:
                out.setdefault(pk, set()).update(names)
    return out


def build(code, r, props, parties, today, tz, now):
    units = [p.get('TransitDispatchTransportationUnit') or {}
             for p in r.get('WhsItemDispatchLoadListDTUPivots', [])]
    port = r.get('WDL_RL_NKLastDischargePort') or ''
    scm = any(VIEW_BOOKING_WORD.search(p) for p in parties)
    cutoff = _parse(r.get('WDL_CTOCutOffTime'))
    local = cutoff.astimezone(tz) if cutoff else None
    return DispatchLoadList(
        branch=code,
        load_list=(r.get('WDL_JobID') or '')[:40],
        reference=(r.get('WDL_ReferenceNumber') or '')[:60],
        master_bill=next((n.get('CE_EntryNum') or '' for n in r.get('ReferenceNumbers', [])), '')[:120],
        booking_party=', '.join(sorted(parties))[:400],
        last_discharge_port=port[:10],
        in_external_view=not port and not scm,
        in_awa_view=bool(port) and scm,
        unit_types=', '.join(u.get('WDH_UnitType') or '' for u in units)[:100],
        vehicles=', '.join(u.get('WDH_VehicleReference') or '' for u in units)[:400],
        total_weight=_dec(props.get('TotalWeight')),
        weight_unit=(props.get('WeightUQ') or '')[:10],
        total_volume=_dec(props.get('TotalVolume')),
        volume_unit=(props.get('VolumeUQ') or '')[:10],
        packages=props.get('NumberOfPackagesNoHandlingUnits') or 0,
        staged_packages=props.get('NumberOfStagedPackages') or 0,
        loaded_packages=props.get('NumberOfLoadedPackages') or 0,
        cto_cutoff=cutoff,
        cto_cutoff_local=local.strftime('%Y-%m-%d %H:%M') if local else '',
        cto_cutoff_date=local.date() if local else None,
        cutoff_today=bool(local and local.date() == today),
        pulled_at=now,
    )


def _iso(d):
    return d.astimezone(dt.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def _dec(v):
    return None if v is None else Decimal(str(v)).quantize(Decimal('0.001'))


def _parse(value):
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
