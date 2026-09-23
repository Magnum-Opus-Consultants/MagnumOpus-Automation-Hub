"""Pull unbooked receive consignments from CargoWise into the database.

    python manage.py pull_receive_consignments

Reproduces the saved grid view "AWA LAX UNBOOKED CARGO CLEANUP", whose three
filters are:

  * Booking party has ALL the exact words UNBOOKED CARGO
  * Has packages in warehouse
  * Receive gate in time on/after a fixed date

All three are applied server-side. Gate-in time is not a field on the
consignment - it belongs to the transportation unit the cargo arrived on, so the
filter travels WhsItemReceiveConsignmentRTUDivots -> TransitReceiveHeader to
reach it. Filtering on something closer to hand, like the consignment's own
create time, would answer a different question and look identical while doing it.

This replaces the spreadsheet round-trip: the same rows, taken from the system
of record rather than from whatever somebody last exported.
"""
import datetime as dt

from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from dashboard.cargowise import CargoWise, CargoWiseError, address
from dashboard.models import ReceiveConsignment, ReceiveConsignmentImport
from dashboard.management.commands.load_receive_consignments import (
    age_bucket, party_country, party_name, split_code,
)

# Package states count towards the columns the report shows. A package that has
# departed is no longer in the warehouse; everything else still is.
DEPARTED = 'DEP'
STATE_COLUMNS = ('BKD', 'ARV', 'CTT', 'PIC', 'PUT')

EXPAND = (
    "Addresses($select=E2_AddressType;"
    "$expand=Address($expand=OrgHeader($select=OH_FullName),Country($select=RN_Desc))),"
    "WhsItemPackageStates($select=WPS_Status),"
    "IntendedWarehouse($select=WW_WarehouseCode,WW_WarehouseName),"
    "ServiceLevel($select=RS_Code,RS_Description),"
    "NextDischargePort($select=RL_Code,RL_PortName)"
)
SELECT = ("WRC_ConsignmentID,WRC_JobID,WRC_CompleteTime,"
          "WRC_RS_NKServiceLevel,WRC_RL_NKNextDischargePort")


class Command(BaseCommand):
    help = 'Pull unbooked receive consignments from CargoWise into the database.'

    def add_arguments(self, parser):
        parser.add_argument('--branches', default='DOR,CON',
                            help='Comma-separated branch codes (default DOR,CON).')
        parser.add_argument('--gate-from', default='2026-08-03',
                            help='Gate-in floor, YYYY-MM-DD, matching the saved view.')
        parser.add_argument('--username', default=None)
        parser.add_argument('--password', default=None)
        parser.add_argument('--dry-run', action='store_true',
                            help='Fetch and report, but write nothing.')

    def handle(self, *args, **opts):
        branches = [b.strip().upper() for b in opts['branches'].split(',') if b.strip()]
        try:
            gate_from = dt.date.fromisoformat(opts['gate_from'])
        except ValueError:
            raise CommandError('--gate-from must be YYYY-MM-DD')

        try:
            cw = CargoWise(username=opts['username'], password=opts['password']).login()
        except CargoWiseError as e:
            raise CommandError(str(e))
        self.stdout.write(f'authenticated as {cw.display_name}')

        # The grid's date is a day; the filter needs an instant. Midnight UTC is
        # the floor, which can only ever include a little more, never less.
        gate_iso = f'{gate_from.isoformat()}T00:00:00Z'
        filt = (
            "Addresses/any(a: a/E2_AddressType eq 'BKD' and "
            "contains(tolower(a/Address/OrgHeader/OH_FullName),'unbooked'))"
            f" and WhsItemPackageStates/any(p: p/WPS_Status ne '{DEPARTED}')"
            " and WhsItemReceiveConsignmentRTUDivots/any("
            f"d: d/TransitReceiveHeader/WRH_GateInTime ge {gate_iso})"
        )

        records = []
        for code in branches:
            if code not in cw.branches:
                self.stdout.write(self.style.WARNING(
                    f'  {code}: not available to this user, skipped'))
                continue
            try:
                cw.select_branch(code)
                rows = cw.page('WhsItemReceiveConsignments',
                               {'$filter': filt, '$select': SELECT, '$expand': EXPAND,
                                '$orderby': 'WRC_ConsignmentID'})
            except CargoWiseError as e:
                raise CommandError(f'{code}: {e}')
            self.stdout.write(f'  {code}: {len(rows)} consignment(s)')
            for r in rows:
                records.append((code, r))

        if opts['dry_run']:
            self.stdout.write(self.style.WARNING(
                f'dry run - {len(records)} row(s) fetched, nothing written'))
            for code, r in records[:10]:
                self.stdout.write(f'    {code} {r.get("WRC_ConsignmentID")} '
                                  f'{address(r, "BKD")[:60]}')
            return

        n = self._store(records, gate_from, branches)
        awaiting = ReceiveConsignment.objects.filter(
            is_unbooked=True, is_latest_snapshot=True, in_warehouse__gt=0).count()
        self.stdout.write('')
        if n == 0:
            self.stdout.write(self.style.SUCCESS(
                'ALL CLEAR - no unbooked cargo awaiting action.'))
        else:
            self.stdout.write(self.style.SUCCESS(
                f'{n} row(s) stored; {awaiting} unbooked awaiting action.'))

    @transaction.atomic
    def _store(self, records, gate_from, branches):
        now = timezone.now()
        label = (f'CargoWise live pull ({",".join(branches)}, '
                 f'gate-in from {gate_from.isoformat()})')
        imp = ReceiveConsignmentImport.objects.create(
            filename=label, file_size=0, file_modified=now, export_timestamp=now,
            notes='Pulled directly from CargoWise OData; no spreadsheet involved.')

        today = timezone.localdate()
        batch = []
        for code, r in records:
            states = [(p.get('WPS_Status') or '').upper()
                      for p in r.get('WhsItemPackageStates', [])]
            counts = {s: states.count(s) for s in STATE_COLUMNS}
            in_warehouse = sum(1 for s in states if s != DEPARTED)

            consignor = address(r, 'CRG')
            consignee = address(r, 'CED')
            booking = address(r, 'BKD')

            wh = r.get('IntendedWarehouse') or {}
            wh_code = wh.get('WW_WarehouseCode') or ''
            wh_name = wh.get('WW_WarehouseName') or ''
            sl = r.get('ServiceLevel') or {}
            sl_code = sl.get('RS_Code') or (r.get('WRC_RS_NKServiceLevel') or '')
            sl_name = sl.get('RS_Description') or ''
            port = r.get('NextDischargePort') or {}

            completion = _parse(r.get('WRC_CompleteTime'))
            days = ((today - timezone.localtime(completion).date()).days
                    if completion else None)
            bucket, order = age_bucket(days)
            cid = r.get('WRC_ConsignmentID') or ''

            batch.append(ReceiveConsignment(
                source=imp,
                receive_consignment_id=cid[:60],
                rcn_reference=(r.get('WRC_JobID') or '')[:60],
                next_open_service='',
                consignor=consignor, consignee=consignee, booking_party=booking,
                consignor_name=party_name(consignor)[:200],
                consignor_country=party_country(consignor)[:80],
                consignee_name=party_name(consignee)[:200],
                consignee_country=party_country(consignee)[:80],
                booking_party_name=party_name(booking)[:200],
                booking_party_country=party_country(booking)[:80],
                number_of_packages=len(states),
                bkd=counts['BKD'], arv=counts['ARV'], ctt=counts['CTT'],
                pic=counts['PIC'], put=counts['PUT'],
                in_warehouse=in_warehouse,
                overs=0,
                warehouse=f'{wh_code} - {wh_name}'.strip(' -')[:120],
                warehouse_code=wh_code[:40], warehouse_name=wh_name[:120],
                service_level=f'{sl_code} - {sl_name}'.strip(' -')[:120],
                service_level_code=sl_code[:40], service_level_name=sl_name[:120],
                next_discharge_port=(port.get('RL_Code')
                                     or r.get('WRC_RL_NKNextDischargePort') or '')[:120],
                completion_date=completion,
                completion_date_only=(timezone.localtime(completion).date()
                                      if completion else None),
                # Everything here matched the booking-party filter by definition.
                is_unbooked=True,
                has_overs=False,
                has_consignee=bool(consignee),
                has_discharge_port=bool(port.get('RL_Code')
                                        or r.get('WRC_RL_NKNextDischargePort')),
                has_next_open_service=False,
                age_days=days, age_bucket=bucket, age_bucket_order=order,
                source_file=label[:400], export_timestamp=now, file_modified=now,
                row_key=f'{label}|{code}|{cid}'[:480],
            ))

        ReceiveConsignment.objects.bulk_create(batch, batch_size=500)
        imp.row_count = len(batch)
        imp.save(update_fields=['row_count'])

        # A live pull is the current state, so it supersedes everything before
        # it. Anything older stays for history but stops counting.
        ReceiveConsignment.objects.exclude(source=imp).update(is_latest_snapshot=False)
        ReceiveConsignment.objects.filter(source=imp).update(is_latest_snapshot=True)
        return len(batch)


def _parse(value):
    """CargoWise DateTimeOffset -> an aware datetime, or None."""
    if not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed)
