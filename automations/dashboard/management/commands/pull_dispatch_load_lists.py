"""Pull dispatch load lists the way Bruce's CargoWise grid views list them.

    python manage.py pull_dispatch_load_lists

Reproduces the saved grid view "DOR EXTERNAL CUTOFF TODAY":

  * CTO cut off date is today
  * Booking party has NONE of these EXACT words SCM
  * Last discharge port is blank

with the grid's columns: weight, volume, packages, in warehouse, FLO, DEP,
load list type and the transport units' references.
Every active load list with a cut-off from 30 days back to 7 ahead is stored,
flagged in_external_view (the view above, less its date) and in_awa_view (its
counterpart, "DOR AWA CUTOFF TODAY"), and cutoff_today marks the ones whose
cut-off falls today. "Today" is counted in the time zone of the CargoWise
profile the views are read in, so the list matches that screen.

The booking party is not on the load list but on its dispatch consignments,
and the totals come from DispatchLoadListPropertiesViews - the same figures
the grid shows. The AWA view also counts the booking party of the receive
consignments the packages came in on.
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
# Package states are read on their own, not expanded on the load list: an
# expanded collection stops at 50 rows, so a load list of 63 packages counted
# only 50 of them in the warehouse.
STATE_SELECT = ('WPS_WDL_LoadList,WPS_Status,WPS_WDC_TransitDispatchConsignment,'
                'WPS_WRC_TransitReceiveConsignment')
# Package states the grid counts as in the warehouse: arrived and still here.
# BKD is booked but not arrived; DEP and FLO have their own columns.
NOT_IN_WAREHOUSE = {'BKD', 'DEP', 'FLO'}
UNIT_TYPE_NAMES = {'VEH': 'Vehicle', 'ULD': 'ULD'}
BKD_EXPAND = ("Addresses($filter=E2_AddressType eq 'BKD';$select=E2_AddressType;"
              "$expand=Address($select=OA_Code;$expand=OrgHeader($select=OH_FullName)))")


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
                               {'$filter': dcn_filt, '$select': 'WDC_PK',
                                '$expand': BKD_EXPAND})
                props, states = {}, {}
                pks = [r['WDL_PK'] for r in rows]
                for i in range(0, len(pks), PROPS_BATCH):
                    batch = pks[i:i + PROPS_BATCH]
                    f = ' or '.join(f'WDL_PK eq {pk}' for pk in batch)
                    for p in cw.get('DispatchLoadListPropertiesViews', {'$filter': f}).get('value', []):
                        props[p['WDL_PK']] = p
                    f = ' or '.join(f'WPS_WDL_LoadList eq {pk}' for pk in batch)
                    for s in cw.page('WhsItemPackageStates', {'$filter': f, '$select': STATE_SELECT}):
                        states.setdefault(s.get('WPS_WDL_LoadList'), []).append(s)
                # The AWA view also takes a booking party from the receive side:
                # cargo booked in by Intelligent SCM can leave on a consignment
                # booked by someone else (DLL00031940: CEVA out, SCM in). Only
                # load lists with a discharge port can be in that view.
                rcn_pks = sorted({s.get('WPS_WRC_TransitReceiveConsignment')
                                  for r in rows if r.get('WDL_RL_NKLastDischargePort')
                                  for s in states.get(r['WDL_PK'], [])} - {None})
                rcns = []
                for i in range(0, len(rcn_pks), PROPS_BATCH):
                    f = ' or '.join(f'WRC_PK eq {pk}' for pk in rcn_pks[i:i + PROPS_BATCH])
                    rcns += cw.page('WhsItemReceiveConsignments',
                                    {'$filter': f, '$select': 'WRC_PK', '$expand': BKD_EXPAND})
            except CargoWiseError as e:
                raise CommandError(f'{code}: {e}')
            dcn_names = {c['WDC_PK']: party_names(c) for c in dcns}
            rcn_names = {c['WRC_PK']: party_names(c) for c in rcns}
            for r in rows:
                own = states.get(r['WDL_PK'], [])
                parties = set().union(*(dcn_names.get(s.get('WPS_WDC_TransitDispatchConsignment'), set())
                                        for s in own))
                received = set().union(*(rcn_names.get(s.get('WPS_WRC_TransitReceiveConsignment'), set())
                                         for s in own))
                built.append(build(code, r, props.get(r['WDL_PK'], {}), own,
                                   parties, received, today, tz, now))
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


def party_names(consignment):
    """Booking party names on a dispatch or receive consignment."""
    return {((a.get('Address') or {}).get('OrgHeader') or {}).get('OH_FullName') or ''
            for a in consignment.get('Addresses', [])} - {''}


def build(code, r, props, package_states, parties, received, today, tz, now):
    units = [p.get('TransitDispatchTransportationUnit') or {}
             for p in r.get('WhsItemDispatchLoadListDTUPivots', [])]
    port = r.get('WDL_RL_NKLastDischargePort') or ''
    scm = any(VIEW_BOOKING_WORD.search(p) for p in parties)
    scm_received = any(VIEW_BOOKING_WORD.search(p) for p in received)
    states = [(p.get('WPS_Status') or '').upper() for p in package_states]
    kinds = sorted({UNIT_TYPE_NAMES.get(u.get('WDH_UnitType') or '', u.get('WDH_UnitType') or '')
                    for u in units} - {''})
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
        in_awa_view=bool(port) and (scm or scm_received),
        unit_types=', '.join(u.get('WDH_UnitType') or '' for u in units)[:100],
        vehicles=', '.join(u.get('WDH_VehicleReference') or '' for u in units)[:400],
        total_weight=_dec(props.get('TotalWeight')),
        weight_unit=(props.get('WeightUQ') or '')[:10],
        total_volume=_dec(props.get('TotalVolume')),
        volume_unit=(props.get('VolumeUQ') or '')[:10],
        packages=props.get('NumberOfPackagesNoHandlingUnits') or 0,
        staged_packages=props.get('NumberOfStagedPackages') or 0,
        loaded_packages=props.get('NumberOfLoadedPackages') or 0,
        in_warehouse=sum(1 for s in states if s and s not in NOT_IN_WAREHOUSE),
        flo_packages=states.count('FLO'),
        dep_packages=states.count('DEP'),
        load_list_type=', '.join(kinds) or 'None',
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
