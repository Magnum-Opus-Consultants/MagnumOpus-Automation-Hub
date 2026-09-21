"""AWA data services, run and reported from this platform.

Fifteen scripts pull CargoWise views into Excel workbooks and upload them to
SharePoint. They used to be a separate concern entirely: their own repository,
their own systemd timer, their own status JSON on disk and their own hand-built
status email. Nothing about them was visible from here, and the only way to
know whether a report had failed was to read an email or SSH in.

This module takes over the orchestration. The scripts stay exactly where they
are and keep running as subprocesses, which is deliberate:

* One of them crashing cannot take the scheduler - or the platform - down.
* Each finishes and its memory is returned, which matters on a box that also
  runs Postgres, gunicorn and twenty-one hourly syncs.
* They need no rewriting, so nothing that works today is put at risk.

What changes is that the platform decides when they run, records what happened
in the database, shows it on a page, and sends the status email through the
same branded shell as everything else it sends.
"""
import logging
import os
import re
import subprocess
import uuid
from datetime import timedelta

from django.conf import settings
from django.utils import timezone

from .models import AwaReportRun, AwaReportState

logger = logging.getLogger(__name__)

# Where the scripts and their credentials live on the server. Overridable so a
# workstation can point at a checkout without editing code.
AWA_ROOT = getattr(settings, 'AWA_ROOT', '/opt/awa-data-services')
AWA_ENV_FILE = getattr(settings, 'AWA_ENV_FILE',
                       '/etc/awa-data-services/transit_report.env')
# Left blank by default so it is discovered rather than assumed. The reports
# depend on openpyxl, which the system python3 does not have - they are built
# against a virtualenv beside them, and the systemd unit they replace passed
# that interpreter in explicitly. Guessing python3 here got as far as pulling
# the data and then failed writing the workbook.
_CONFIGURED_PYTHON = getattr(settings, 'AWA_PYTHON', '')


def python_bin():
    """The interpreter the report scripts expect."""
    if _CONFIGURED_PYTHON:
        return _CONFIGURED_PYTHON
    beside = os.path.join(AWA_ROOT, '.venv', 'bin', 'python')
    return beside if os.path.isfile(beside) else 'python3'


# Long enough for the biggest pull - RTU moves about thirty thousand rows - and
# short enough that a hung request cannot occupy the runner all day.
PER_REPORT_TIMEOUT = getattr(settings, 'AWA_REPORT_TIMEOUT', 25 * 60)

# script, friendly name, days it runs (Monday=0; empty means every day).
# Ordered as they should run: the transit report first because it is the one
# people ask about, then the rest.
REPORTS = [
    ('transit_report.py', 'External Customer Report (DOR+CON)', ''),
    ('cycle_count_report.py', 'Cycle Count (CON)', '0,4'),
    ('rtu_report.py', "KPIU / RTU (DOR+CON)", ''),
    ('open_rtu_report.py', "Open RTU's (DOR+CON)", ''),
    ('pkg_report.py', 'PKG - No Consignment (DOR+CON)', ''),
    ('rcn_report.py', 'RCN - No Booking Party (DOR+CON)', ''),
    ('condor_cleanup_report.py', 'Condor Booking Party Cleanup (CON)', ''),
    ('services_pending_report.py', 'Services Pending - Freight On Hand (DOR+CON)', ''),
    ('rcn_pending_services_report.py', 'Services Pending (DOR+CON)', ''),
    ('mikes_bonded_check_report.py', "Mike's Bonded Check (DOR)", ''),
    ('unknown_received_report.py', 'Unknown Received Report (CON)', '4'),
    ('dtu_report.py', 'DTU (CCC)', ''),
    ('open_dtu_report.py', "Open DTU's (CCC)", ''),
    ('mika_loadlist_report.py', 'Condor Weekly Load List (CCC)', '0'),
    ('k9_report.py', 'K9 Line Item Inventory (CON)', ''),
]

_ROWS = re.compile(r'\((\d[\d,]*)\s+rows\)')


def sync_catalogue():
    """Make sure every report has a state row, and none are left behind.

    Runs before a batch and on demand, so adding a script to REPORTS is the
    only edit needed to bring a new report onto the platform.

    Does nothing on a machine without the scripts. Otherwise a dev box shows
    fifteen reports that have never run and never will, every one of them
    permanently stale - noise that looks exactly like a real outage.
    """
    if not is_installed():
        logger.debug('[awa] %s is not on this machine; catalogue left alone',
                     AWA_ROOT)
        return
    known = set()
    for script, name, days in REPORTS:
        known.add(script)
        state, created = AwaReportState.objects.get_or_create(
            script=script, defaults={'name': name, 'run_days': days})
        if not created and (state.name != name or state.run_days != days):
            state.name, state.run_days = name, days
            state.save(update_fields=['name', 'run_days'])
    # A report dropped from the catalogue keeps its history but stops being
    # offered - deleting it would lose the record of what it used to pull.
    AwaReportState.objects.exclude(script__in=known).update(is_enabled=False)
    return len(known)


def _read_env_file(path):
    """The credentials the scripts expect, read from their EnvironmentFile.

    systemd's EnvironmentFile format: KEY=value, one per line, with comments
    and blanks allowed. Values are used as written - the scripts have always
    received them this way.
    """
    env = {}
    try:
        with open(path, encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith('#') or '=' not in line:
                    continue
                key, val = line.split('=', 1)
                env[key.strip()] = val.strip().strip('"').strip("'")
    except OSError as e:
        logger.warning('[awa] could not read %s: %s', path, e)
    return env


def plain_error(out):
    """The tail of a failed run, as one sentence someone can act on.

    Carried over from the original orchestrator because it is the part that
    made the status email useful: "Could not log in to CargoWise" is actionable
    where a traceback is not.
    """
    low = (out or '').lower()
    if 'login failed' in low or 'claim/staff' in low:
        return 'Could not log in to CargoWise (check the username and password).'
    if 'required environment variable' in low:
        m = re.search(r'required environment variable (\w+)', out)
        return f'A setting is missing: {m.group(1) if m else "see the log"}.'
    if 'branch code' in low and 'not found' in low:
        return "A CargoWise branch in the config was not found for this login."
    if 'department' in low and 'not found' in low:
        return 'The CargoWise department in the config was not found.'
    if '401' in (out or ''):
        return 'CargoWise rejected the session (the login expired and could not renew).'
    if 'graph' in low and ('403' in out or '401' in out):
        return 'The SharePoint upload was refused (permissions or credentials).'
    if 'timed out' in low or 'timeout' in low:
        return 'A request timed out (CargoWise or SharePoint was slow or unreachable).'
    lines = [ln.strip() for ln in (out or '').strip().splitlines() if ln.strip()]
    return f'Unexpected error: {lines[-1][:300]}' if lines else 'Failed with no output.'


def _rows_from(out):
    found = _ROWS.findall(out or '')
    return int(found[-1].replace(',', '')) if found else None


def run_report(script, batch='', user=None, force=False):
    """Run one report and record what happened. Never raises.

    `force` runs it even on a day it is not scheduled for, which is what the
    "Run now" button on the page needs.
    """
    state = AwaReportState.objects.filter(script=script).first()
    if state is None:
        sync_catalogue()
        state = AwaReportState.objects.filter(script=script).first()
    if state is None:
        logger.error('[awa] %s is not in the catalogue', script)
        return None

    started = timezone.now()

    if not force and not state.runs_today:
        run = AwaReportRun.objects.create(
            script=script, name=state.name, outcome='skipped',
            rows=None, started_at=started, finished_at=started,
            duration_seconds=0, batch=batch, triggered_by=user)
        state.last_outcome = 'skipped'
        state.last_run_at = started
        state.save(update_fields=['last_outcome', 'last_run_at'])
        return run

    path = os.path.join(AWA_ROOT, script)
    if not os.path.isfile(path):
        detail = f'{script} is not on this server at {AWA_ROOT}.'
        return _record_failure(state, script, started, detail, detail, batch, user)

    env = dict(os.environ)
    env.update(_read_env_file(AWA_ENV_FILE))

    try:
        proc = subprocess.run(
            [python_bin(), path], capture_output=True, text=True,
            cwd=AWA_ROOT, env=env, timeout=PER_REPORT_TIMEOUT)
        out = (proc.stdout or '') + (('\n' + proc.stderr) if proc.stderr else '')
        ok = proc.returncode == 0
    except subprocess.TimeoutExpired:
        out = f'The report was still running after {PER_REPORT_TIMEOUT // 60} minutes.'
        ok = False
    except OSError as e:
        out = f'Could not start the report: {e}'
        ok = False

    finished = timezone.now()
    duration = (finished - started).total_seconds()
    rows = _rows_from(out)
    tail = '\n'.join((out or '').strip().splitlines()[-40:])

    if not ok:
        return _record_failure(state, script, started, plain_error(out), tail,
                               batch, user, finished=finished, rows=rows)

    run = AwaReportRun.objects.create(
        script=script, name=state.name, outcome='ok', rows=rows,
        log_tail=tail, duration_seconds=duration,
        started_at=started, finished_at=finished, batch=batch, triggered_by=user)
    state.last_outcome = 'ok'
    state.last_run_at = finished
    state.last_success_at = finished
    if rows is not None:
        state.last_rows = rows
    state.last_error = ''
    state.consecutive_failures = 0
    state.save()
    logger.info('[awa] %s ok in %.0fs (%s rows)', script, duration,
                f'{rows:,}' if rows is not None else '?')
    return run


def _record_failure(state, script, started, message, tail, batch, user,
                    finished=None, rows=None):
    finished = finished or timezone.now()
    run = AwaReportRun.objects.create(
        script=script, name=state.name, outcome='failed', rows=rows,
        error=message[:2000], log_tail=tail,
        duration_seconds=(finished - started).total_seconds(),
        started_at=started, finished_at=finished, batch=batch, triggered_by=user)
    state.last_outcome = 'failed'
    state.last_run_at = finished
    state.last_error = message[:2000]
    state.consecutive_failures = (state.consecutive_failures or 0) + 1
    state.save()
    logger.error('[awa] %s failed: %s', script, message)
    return run


def is_installed():
    """Whether the report scripts are on this machine at all."""
    return os.path.isdir(AWA_ROOT)


def run_batch(user=None, only=None, force=False, notify=True):
    """Run every scheduled report, then send the status email.

    One failing report does not stop the rest - that was true of the original
    orchestrator and it matters more here, because this now runs inside the
    process that serves the platform.
    """
    # A machine without the scripts has nothing to say about them. Without this
    # a development instance running the same scheduler reported all fifteen as
    # failed and emailed that to the people who watch the real ones - which is
    # worse than silence, because it makes a healthy run look broken.
    if not is_installed():
        logger.info('[awa] %s is not on this machine; skipping the batch', AWA_ROOT)
        return '', []

    sync_catalogue()
    batch = uuid.uuid4().hex[:12]
    scripts = [s for s, _n, _d in REPORTS
               if not only or s in set(only)]
    runs = []
    for script in scripts:
        state = AwaReportState.objects.filter(script=script).first()
        if state and not state.is_enabled:
            continue
        run = run_report(script, batch=batch, user=user, force=force)
        if run is not None:
            runs.append(run)

    failed = [r for r in runs if r.outcome == 'failed']
    logger.info('[awa] batch %s finished: %s ok, %s failed, %s skipped',
                batch, sum(1 for r in runs if r.outcome == 'ok'),
                len(failed), sum(1 for r in runs if r.outcome == 'skipped'))

    if notify and runs:
        try:
            from .awa_email import send_status
            send_status(batch, runs)
        except Exception:                                        # noqa: BLE001
            # The runs are recorded and visible on the page; a failed email
            # must not turn a good batch into a bad one.
            logger.exception('[awa] could not send the status email')
    return batch, runs


def import_legacy_state():
    """Adopt the run history the scripts kept in their own JSON file.

    One-off, idempotent: without it the platform's first page load would claim
    every report had never run, when in fact they have been running daily for
    months.
    """
    import json

    path = os.path.join(AWA_ROOT, 'output', '_status.json')
    try:
        with open(path, encoding='utf-8') as fh:
            legacy = json.load(fh)
    except (OSError, ValueError) as e:
        logger.info('[awa] no legacy state to import (%s)', e)
        return 0

    sync_catalogue()
    adopted = 0
    for script, row in (legacy or {}).items():
        state = AwaReportState.objects.filter(script=script).first()
        if state is None or state.last_success_at:
            continue
        when = row.get('last_success')
        if not when:
            continue
        try:
            from django.utils.dateparse import parse_datetime
            dt = parse_datetime(when)
        except (TypeError, ValueError):
            continue
        if dt is None:
            continue
        state.last_success_at = dt
        state.last_run_at = dt
        state.last_outcome = 'ok'
        state.last_rows = row.get('rows')
        state.save()
        adopted += 1
    logger.info('[awa] adopted %s report(s) from the legacy status file', adopted)
    return adopted


def prune(days=120):
    """Keep the run table from growing for ever."""
    cutoff = timezone.now() - timedelta(days=days)
    n, _ = AwaReportRun.objects.filter(started_at__lt=cutoff).delete()
    if n:
        logger.info('[awa] pruned %s run record(s) older than %s days', n, days)
    return n
