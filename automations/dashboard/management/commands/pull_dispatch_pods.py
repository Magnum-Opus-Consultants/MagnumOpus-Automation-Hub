"""Pull dispatch load lists and their POD timings from CargoWise.

    python manage.py pull_dispatch_pods

The KPI is a proof of delivery on every dispatched load list within 24 hours
of the cargo leaving. Both ends of that clock are in the TransitWarehouse feed:

  * Start: the load list's dispatch transportation unit gating out
    (WhsItemDispatchLoadListDTUPivots -> WDH_GateOutTime). A load list on
    several units starts the clock when the first one leaves: ULDs and their
    truck leave together, and the few that go out over several trips get a
    POD for the first trip, which is the one the KPI measures.
  * Stop: the first POD document event on the load list's log - event DDI,
    reference "POD|<document>". A POD uploaded to the forwarding console's
    eDocs in CargoWise One is written to this same log, so the console never
    has to be read directly. Now and then a POD is filed against one of the
    dispatch consignments on the load list instead, so those logs count too.

Every dispatched load list is pulled. The team's saved grid views keep to
those with a last discharge port - the consol load lists going to an airline -
so the report can do the same on last_discharge_port, but house-level
dispatches carry PODs too and leaving them out here would hide that. A load
list that has not gated out yet is not on the clock, so it is left out until
it has.
"""
import datetime as dt
from decimal import Decimal
from zoneinfo import ZoneInfo

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from dashboard.cargowise import CargoWise, CargoWiseError
from dashboard.models import DispatchPod

KPI_HOURS = 24
POD_EVENT = 'DDI'
POD_PREFIX = 'POD|'

STATUS_ORDER = {DispatchPod.STATUS_OVERDUE: 1, DispatchPod.STATUS_DUE: 2,
                DispatchPod.STATUS_LATE: 3, DispatchPod.STATUS_ON_TIME: 4}

SELECT = ('WDL_PK,WDL_JobID,WDL_ReferenceNumber,WDL_IsActive,WDL_CTOCutOffTime,'
          'WDL_RL_NKLastDischargePort,WDL_TransportMode')
POD_LOGS = (f"Logs($filter=SL_SE_NKEvent eq '{POD_EVENT}';"
            "$select=SL_SE_NKEvent,SL_Reference,SL_EventTimeUtc,SL_GS_NKUser)")
EXPAND = (
    f"{POD_LOGS},"
    "WhsItemDispatchLoadListDTUPivots($expand=TransitDispatchTransportationUnit("
    "$select=WDH_ReferenceNumber,WDH_VehicleReference,WDH_GateOutTime)),"
    "UniversalJobLinks($select=UCL_SourceKey,UCL_SourceType),"
    "ReferenceNumbers($filter=CE_EntryType eq 'MAB';$select=CE_EntryNum),"
    "Addresses($filter=E2_AddressType eq 'CDT';$select=E2_AddressType;"
    "$expand=Address($select=OA_Code;$expand=OrgHeader($select=OH_Code,OH_FullName)))"
)
# Dispatch consignments carrying a POD of their own, and the load lists their
# packages went out on. A consignment is created before its load list, so it
# is looked for over a longer window.
DCN_FILTER = (f"Logs/any(e: e/SL_SE_NKEvent eq '{POD_EVENT}' "
              f"and startswith(e/SL_Reference,'{POD_PREFIX}'))")
DCN_EXPAND = f"{POD_LOGS},WhsItemPackageStates($select=WPS_WDL_LoadList)"
DCN_EXTRA_DAYS = 30


class Command(BaseCommand):
    help = 'Pull dispatch load lists and their POD timings from CargoWise.'

    def add_arguments(self, parser):
        parser.add_argument('--branches', default='DOR',
                            help='Comma-separated branch codes (default DOR).')
        parser.add_argument('--days', type=int, default=45,
                            help='Load lists created in the last N days (default 45).')
        parser.add_argument('--tz', default='America/Los_Angeles',
                            help='Warehouse time zone for dates and display times.')
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

        since = timezone.now() - dt.timedelta(days=opts['days'])
        filt = f"WDL_SystemCreateTimeUtc ge {since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
        dcn_since = since - dt.timedelta(days=DCN_EXTRA_DAYS)
        dcn_filt = (f"WDC_SystemCreateTimeUtc ge {dcn_since.strftime('%Y-%m-%dT%H:%M:%SZ')}"
                    f" and {DCN_FILTER}")

        records = []
        for code in branches:
            if code not in cw.branches:
                self.stdout.write(self.style.WARNING(
                    f'  {code}: not available to this user, skipped'))
                continue
            try:
                cw.select_branch(code)
                rows = cw.page('WhsItemDispatchLoadLists',
                               {'$filter': filt, '$select': SELECT, '$expand': EXPAND,
                                '$orderby': 'WDL_JobID'})
                dcns = cw.page('WhsItemDispatchConsignments',
                               {'$filter': dcn_filt, '$select': 'WDC_ConsignmentID',
                                '$expand': DCN_EXPAND})
            except CargoWiseError as e:
                raise CommandError(f'{code}: {e}')
            attach_consignment_pods(rows, dcns)
            self.stdout.write(f'  {code}: {len(rows)} load list(s), '
                              f'{len(dcns)} consignment(s) with a POD of their own')
            records.extend((code, r) for r in rows)

        now = timezone.now()
        built, gone = [], []
        for code, r in records:
            row = build(code, r, now, tz)
            (built if row else gone).append(row or r.get('WDL_JobID'))

        counts = {}
        for row in built:
            counts[row.status] = counts.get(row.status, 0) + 1
        summary = ', '.join(f'{counts.get(s, 0)} {s.lower()}' for s in STATUS_ORDER)
        self.stdout.write(f'{len(built)} dispatched ({summary}); '
                          f'{len(gone)} not dispatched or inactive')

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING('dry run - nothing written'))
            for row in [b for b in built if b.needs_action][:15]:
                self.stdout.write(f'    {row.load_list} {row.reference:14} '
                                  f'out {row.dispatched_local}  {row.status} '
                                  f'({row.hours_waiting}h)')
            return

        self._store(built, gone)
        self.stdout.write(self.style.SUCCESS(
            f'{len(built)} row(s) stored; '
            f'{counts.get(DispatchPod.STATUS_OVERDUE, 0)} POD(s) overdue.'))

    @transaction.atomic
    def _store(self, built, gone):
        fields = [f.name for f in DispatchPod._meta.concrete_fields
                  if f.name not in ('id', 'load_list')]
        DispatchPod.objects.bulk_create(built, batch_size=500, update_conflicts=True,
                                        unique_fields=['load_list'], update_fields=fields)
        # A load list that was cancelled, or whose units were taken back off,
        # is no longer dispatched. Leaving its row would keep a POD "overdue"
        # that nobody can ever upload.
        if gone:
            DispatchPod.objects.filter(load_list__in=gone).delete()


def attach_consignment_pods(rows, dcns):
    """Hang each consignment's POD events on the load lists its packages left on."""
    by_pk = {r.get('WDL_PK'): r for r in rows}
    for c in dcns:
        for pk in {p.get('WPS_WDL_LoadList') for p in c.get('WhsItemPackageStates', [])}:
            if pk in by_pk:
                by_pk[pk].setdefault('ConsignmentPodLogs', []).extend(c.get('Logs', []))


def build(code, r, now, tz):
    """One load list -> a DispatchPod, or None when it is not on the clock."""
    if not r.get('WDL_IsActive'):
        return None
    units = [p.get('TransitDispatchTransportationUnit') or {}
             for p in r.get('WhsItemDispatchLoadListDTUPivots', [])]
    gate_outs = [t for t in (_parse(u.get('WDH_GateOutTime')) for u in units) if t]
    if not gate_outs:
        return None
    dispatched = min(gate_outs)

    events = sorted(((t, e) for e in r.get('Logs', []) + r.get('ConsignmentPodLogs', [])
                     if e.get('SL_SE_NKEvent') == POD_EVENT
                     and (e.get('SL_Reference') or '').upper().startswith(POD_PREFIX)
                     for t in [_parse(e.get('SL_EventTimeUtc'))] if t),
                    key=lambda te: te[0])
    # The POD for this departure is the first one after it. One logged before
    # the gate-out was recorded is still a POD in hand, so it counts at 0 hours
    # rather than as a negative time or a missing document.
    after = [te for te in events if te[0] >= dispatched]
    chosen = after[0] if after else (events[0] if events else None)
    first_pod = chosen[0] if chosen else None
    uploader = (chosen[1].get('SL_GS_NKUser') or '') if chosen else ''

    if first_pod:
        hours = max(_hours(first_pod - dispatched), Decimal('0.0'))
        waiting = None
        status = (DispatchPod.STATUS_ON_TIME if hours <= KPI_HOURS
                  else DispatchPod.STATUS_LATE)
        met = status == DispatchPod.STATUS_ON_TIME
    else:
        hours = None
        waiting = _hours(now - dispatched)
        status = (DispatchPod.STATUS_OVERDUE if waiting > KPI_HOURS
                  else DispatchPod.STATUS_DUE)
        met = False if status == DispatchPod.STATUS_OVERDUE else None

    consol = next((l.get('UCL_SourceKey') or '' for l in r.get('UniversalJobLinks', [])
                   if l.get('UCL_SourceType') == 'ForwardingConsol'), '')
    mab = next((n.get('CE_EntryNum') or '' for n in r.get('ReferenceNumbers', [])), '')
    carrier = next((((a.get('Address') or {}).get('OrgHeader') or {})
                    for a in r.get('Addresses', [])), {})
    local = dispatched.astimezone(tz)

    return DispatchPod(
        branch=code,
        load_list=(r.get('WDL_JobID') or '')[:40],
        reference=(r.get('WDL_ReferenceNumber') or '')[:60],
        consol=consol[:40],
        master_bill=mab[:60],
        carrier_code=(carrier.get('OH_Code') or '')[:40],
        carrier_name=(carrier.get('OH_FullName') or '')[:200],
        last_discharge_port=(r.get('WDL_RL_NKLastDischargePort') or '')[:10],
        transport_mode=(r.get('WDL_TransportMode') or '')[:10],
        cto_cutoff=_parse(r.get('WDL_CTOCutOffTime')),
        dtu_count=len(units),
        dtus=', '.join(u.get('WDH_ReferenceNumber') or '' for u in units)[:400],
        vehicles=', '.join(u.get('WDH_VehicleReference') or '' for u in units)[:400],
        dispatched_at=dispatched,
        pod_uploaded_at=first_pod,
        pod_uploaded_by=uploader[:20],
        # One document can be logged on the load list and on a consignment.
        pod_count=len({(e.get('SL_Reference') or '').upper() for _, e in events}),
        hours_to_pod=hours,
        hours_waiting=waiting,
        status=status,
        status_order=STATUS_ORDER[status],
        kpi_met=met,
        needs_action=first_pod is None,
        dispatched_date=local.date(),
        dispatched_local=local.strftime('%Y-%m-%d %H:%M'),
        pod_uploaded_local=(first_pod.astimezone(tz).strftime('%Y-%m-%d %H:%M')
                            if first_pod else ''),
        pulled_at=now,
    )


def _hours(delta):
    return Decimal(delta.total_seconds() / 3600).quantize(Decimal('0.1'))


def _parse(value):
    """CargoWise DateTimeOffset -> an aware datetime, or None."""
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
