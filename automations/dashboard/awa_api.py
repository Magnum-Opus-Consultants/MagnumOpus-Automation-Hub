"""The reporting page's API: what the CargoWise reports are doing.

Read endpoints answer from AwaReportState, which is one row per report, so the
page loads without touching the run history. Running a batch happens on a
background thread: fifteen reports pulling tens of thousands of rows takes
minutes, and an HTTP request is the wrong place to wait for it.
"""
import json
import logging
import threading

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import awa_reports as awa
from .models import AwaReportRun, AwaReportState
from .views import _require_module

logger = logging.getLogger(__name__)

# Only one batch at a time. Two runs of the same report would fight over the
# same SharePoint file and the same CargoWise session.
_running = threading.Lock()
_current = {'batch': '', 'started': None, 'scripts': []}


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _state_dict(s):
    return {
        'script': s.script,
        'name': s.name,
        'enabled': s.is_enabled,
        'run_days': [int(d) for d in s.run_days.split(',') if d != ''],
        'runs_today': s.runs_today,
        'last_outcome': s.last_outcome,
        'last_run_at': s.last_run_at.isoformat() if s.last_run_at else None,
        'last_success_at': (s.last_success_at.isoformat()
                            if s.last_success_at else None),
        'last_rows': s.last_rows,
        'last_error': s.last_error,
        'consecutive_failures': s.consecutive_failures,
        # How stale the data on SharePoint is. The reports are daily, so
        # anything past about a day and a half has missed a run.
        'hours_since_success': (
            round((timezone.now() - s.last_success_at).total_seconds() / 3600, 1)
            if s.last_success_at else None),
    }


def _run_dict(r):
    return {
        'id': r.id, 'script': r.script, 'name': r.name,
        'outcome': r.outcome, 'outcome_label': r.get_outcome_display(),
        'rows': r.rows, 'error': r.error,
        'duration_seconds': (round(r.duration_seconds, 1)
                             if r.duration_seconds is not None else None),
        'started_at': r.started_at.isoformat() if r.started_at else None,
        'batch': r.batch,
        'triggered_by': (r.triggered_by.get_full_name() or r.triggered_by.username
                         if r.triggered_by else ''),
    }


def api_awa_reports(request):
    """Every report, its current position, and the last batch."""
    err = _require_module(request, 'data')
    if err:
        return err

    awa.sync_catalogue()
    states = list(AwaReportState.objects.all())
    # First load on a fresh database would otherwise claim nothing has ever
    # run, when these have been running daily for months.
    if not any(s.last_success_at for s in states):
        awa.import_legacy_state()
        states = list(AwaReportState.objects.all())

    latest_batch = (AwaReportRun.objects.exclude(batch='')
                    .order_by('-started_at').values_list('batch', flat=True).first())
    batch_runs = (list(AwaReportRun.objects.filter(batch=latest_batch)
                       .order_by('started_at')) if latest_batch else [])

    rows = [_state_dict(s) for s in states]
    stale = [r for r in rows
             if r['hours_since_success'] is None or r['hours_since_success'] > 36]

    with _running:
        busy = dict(_current)
    return JsonResponse({
        'reports': rows,
        'total': len(rows),
        'failing': sum(1 for r in rows if r['last_outcome'] == 'failed'),
        'stale': len(stale),
        'rows_last_pull': sum(r['last_rows'] or 0 for r in rows),
        'last_batch': [_run_dict(r) for r in batch_runs],
        'running': {
            'batch': busy['batch'],
            'started': busy['started'].isoformat() if busy['started'] else None,
            'scripts': busy['scripts'],
        },
        'schedule': 'Every day at 10:00 UTC (12:00 South African time)',
        'source': {'root': awa.AWA_ROOT, 'env_file': awa.AWA_ENV_FILE},
    })


@require_http_methods(["GET"])
def api_awa_runs(request):
    """Run history, newest first. `script` narrows it to one report."""
    err = _require_module(request, 'data')
    if err:
        return err
    qs = AwaReportRun.objects.all()
    script = request.GET.get('script')
    if script:
        qs = qs.filter(script=script)
    try:
        limit = min(int(request.GET.get('limit', 60)), 400)
    except ValueError:
        limit = 60
    return JsonResponse({'runs': [_run_dict(r) for r in qs[:limit]]})


@require_http_methods(["GET"])
def api_awa_run_detail(request, pk):
    """One run including its log tail, for when the sentence is not enough."""
    err = _require_module(request, 'data')
    if err:
        return err
    r = AwaReportRun.objects.filter(pk=pk).first()
    if r is None:
        return JsonResponse({'detail': 'Run not found.'}, status=404)
    return JsonResponse({**_run_dict(r), 'log_tail': r.log_tail})


@csrf_exempt
@require_http_methods(["POST"])
def api_awa_run(request):
    """Start a run in the background.

    `scripts` runs only those; omitted runs every scheduled report. `force`
    runs a report even on a day it is not scheduled for, which is what someone
    pressing "Run now" on a Monday-only report means.
    """
    err = _require_module(request, 'data')
    if err:
        return err
    data = _body(request)
    scripts = data.get('scripts') or None
    if scripts is not None:
        if not isinstance(scripts, list):
            return JsonResponse({'detail': 'scripts must be a list.'}, status=400)
        known = {s for s, _n, _d in awa.REPORTS}
        unknown = [s for s in scripts if s not in known]
        if unknown:
            return JsonResponse(
                {'detail': f'Not a known report: {", ".join(unknown)}'}, status=400)
    force = bool(data.get('force'))

    if not _running.acquire(blocking=False):
        with_current = dict(_current)
        return JsonResponse(
            {'detail': 'A run is already in progress.',
             'batch': with_current['batch']}, status=409)

    user = request.user if request.user.is_authenticated else None
    _current.update({'batch': 'starting', 'started': timezone.now(),
                     'scripts': scripts or [s for s, _n, _d in awa.REPORTS]})

    def _work():
        from django.db import connection
        connection.close()
        try:
            batch, runs = awa.run_batch(user=user, only=scripts, force=force)
            _current['batch'] = batch
            logger.info('[awa] api run finished: batch %s, %s report(s)',
                        batch, len(runs))
        except Exception:                                        # noqa: BLE001
            logger.exception('[awa] api run failed')
        finally:
            _current.update({'batch': '', 'started': None, 'scripts': []})
            connection.close()
            _running.release()

    threading.Thread(target=_work, name='awa-batch', daemon=True).start()
    return JsonResponse({
        'ok': True, 'started': True,
        'scripts': scripts or [s for s, _n, _d in awa.REPORTS],
        'note': 'Running in the background. The page updates as each report '
                'finishes.'}, status=202)
