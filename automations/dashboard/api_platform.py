"""JSON API for the Sentinel platform modules: Domains, Repositories, Planner.

Kept out of views.py (already ~6k lines) since these are self-contained CRUD
endpoints. Access control reuses `_require_module` so permissions behave exactly
like the existing servers/docs modules.
"""
import json
import os
import subprocess
from datetime import date, time

from django.http import JsonResponse
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import Domain, Repository, ProjectTask, ServerRecord
from .views import _require_module


# ══════════════════════════════════════════════════════════════════════════════
# Domains
# ══════════════════════════════════════════════════════════════════════════════

def _domain_dict(d):
    return {
        'id': d.id,
        'name': d.name,
        'company': d.company,
        'environment': d.environment,
        'status': d.status,
        'registrar': d.registrar,
        'dns_provider': d.dns_provider,
        'nameservers': d.nameservers,
        'primary_url': d.primary_url,
        'server': d.server_id,
        'server_name': d.server.name if d.server else '',
        'registered_on': d.registered_on.isoformat() if d.registered_on else None,
        'expires_on': d.expires_on.isoformat() if d.expires_on else None,
        'ssl_expires_on': d.ssl_expires_on.isoformat() if d.ssl_expires_on else None,
        'days_to_expiry': d.days_until('expires_on'),
        'days_to_ssl_expiry': d.days_until('ssl_expires_on'),
        'auto_renew': d.auto_renew,
        'notes': d.notes,
        'order': d.order,
    }


_DOMAIN_TEXT_FIELDS = (
    'name', 'company', 'environment', 'status', 'registrar', 'dns_provider',
    'nameservers', 'primary_url', 'notes',
)
_DOMAIN_DATE_FIELDS = ('registered_on', 'expires_on', 'ssl_expires_on')


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _coerce_date(raw):
    """Normalise an incoming date value to a `date` (or None).

    JSON gives us strings, and assigning a string straight onto a DateField
    leaves it a string on the in-memory instance — which then breaks any
    `.isoformat()`/date arithmetic done before the row is re-read. Parsing here
    keeps the instance correctly typed and rejects malformed input up front.

    Returns (value, ok).
    """
    if raw is None:
        return None, True
    if isinstance(raw, date):
        return raw, True
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None, True
        try:
            # parse_date returns None for the wrong shape but *raises* for a
            # well-shaped impossible date such as 2026-13-45.
            parsed = parse_date(raw)
        except ValueError:
            return None, False
        return (parsed, True) if parsed else (None, False)
    return None, False


def _apply_domain_fields(rec, data):
    """Copy request fields onto `rec`. Returns a list of validation errors."""
    errors = []
    for f in _DOMAIN_TEXT_FIELDS:
        if f in data:
            value = data.get(f)
            setattr(rec, f, (value or '').strip() if isinstance(value, str) else (value or ''))
    for f in _DOMAIN_DATE_FIELDS:
        if f in data:
            value, ok = _coerce_date(data.get(f))
            if not ok:
                errors.append(f'{f} must be a date in YYYY-MM-DD format.')
                continue
            setattr(rec, f, value)
    if 'auto_renew' in data:
        rec.auto_renew = bool(data.get('auto_renew'))
    if 'order' in data:
        try:
            rec.order = int(data.get('order') or 0)
        except (TypeError, ValueError):
            pass
    if 'server' in data:
        sid = data.get('server')
        rec.server = ServerRecord.objects.filter(id=sid).first() if sid else None
    return errors


def api_domains(request):
    err = _require_module(request, 'domains')
    if err:
        return err
    rows = [_domain_dict(d) for d in Domain.objects.select_related('server').all()]
    # Renewal buckets drive the summary tiles on the Domains page.
    expiring = [r for r in rows if r['days_to_expiry'] is not None and 0 <= r['days_to_expiry'] <= 30]
    expired = [r for r in rows if r['days_to_expiry'] is not None and r['days_to_expiry'] < 0]
    ssl_soon = [r for r in rows if r['days_to_ssl_expiry'] is not None and 0 <= r['days_to_ssl_expiry'] <= 30]
    return JsonResponse({
        'domains': rows,
        'total': len(rows),
        'expiring_soon': len(expiring),
        'expired': len(expired),
        'ssl_expiring_soon': len(ssl_soon),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_domain_create(request):
    err = _require_module(request, 'domains')
    if err:
        return err
    rec = Domain(order=Domain.objects.count())
    errors = _apply_domain_fields(rec, _body(request))
    if not rec.name:
        return JsonResponse({'detail': 'A domain name is required.'}, status=400)
    if errors:
        return JsonResponse({'detail': ' '.join(errors)}, status=400)
    if Domain.objects.filter(name=rec.name).exists():
        return JsonResponse({'detail': rec.name + ' already exists.'}, status=409)
    rec.save()
    return JsonResponse(_domain_dict(rec), status=201)


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_domain_update(request, pk):
    err = _require_module(request, 'domains')
    if err:
        return err
    rec = Domain.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    errors = _apply_domain_fields(rec, _body(request))
    if not rec.name:
        return JsonResponse({'detail': 'A domain name is required.'}, status=400)
    if errors:
        return JsonResponse({'detail': ' '.join(errors)}, status=400)
    if Domain.objects.filter(name=rec.name).exclude(id=rec.id).exists():
        return JsonResponse({'detail': rec.name + ' already exists.'}, status=409)
    rec.save()
    return JsonResponse(_domain_dict(rec))


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_domain_delete(request, pk):
    err = _require_module(request, 'domains')
    if err:
        return err
    rec = Domain.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    rec.delete()
    return JsonResponse({'ok': True})


# ══════════════════════════════════════════════════════════════════════════════
# Repositories + live git history
# ══════════════════════════════════════════════════════════════════════════════

def _repo_dict(r):
    return {
        'id': r.id,
        'name': r.name,
        'company': r.company,
        'description': r.description,
        'local_path': r.local_path,
        'remote_url': r.remote_url,
        'provider': r.provider,
        'default_branch': r.default_branch,
        'server': r.server_id,
        'server_name': r.server.name if r.server else '',
        'notes': r.notes,
        'order': r.order,
    }


def _git(path, *args, timeout=15):
    """Run a read-only git command in `path`. Returns (ok, stdout_or_error)."""
    try:
        proc = subprocess.run(
            ['git', '-C', path, *args],
            capture_output=True, text=True, timeout=timeout,
        )
    except FileNotFoundError:
        return False, 'git is not installed on this host.'
    except subprocess.TimeoutExpired:
        return False, 'git command timed out.'
    except Exception as e:
        return False, str(e)
    if proc.returncode != 0:
        return False, (proc.stderr or proc.stdout or 'git command failed').strip()
    return True, proc.stdout


# Unit-separator delimited so commit subjects containing commas or pipes survive.
_LOG_FMT = '%H%x1f%h%x1f%an%x1f%ae%x1f%aI%x1f%s%x1f%D'


def _repo_history(repo, limit=25):
    """Read live git state for a repo. Never raises — returns `error` instead."""
    path = (repo.local_path or '').strip()
    out = {
        'available': False, 'error': None, 'branch': None, 'commits': [],
        'ahead': None, 'behind': None, 'dirty': None, 'remote': None,
        'last_activity': None,
    }
    if not path:
        out['error'] = 'No local path recorded for this repository.'
        return out
    if not os.path.isdir(path):
        out['error'] = 'Path not found on this host: ' + path
        return out

    ok, _ = _git(path, 'rev-parse', '--is-inside-work-tree')
    if not ok:
        out['error'] = 'Not a git repository: ' + path
        return out
    out['available'] = True

    ok, branch = _git(path, 'rev-parse', '--abbrev-ref', 'HEAD')
    if ok:
        out['branch'] = branch.strip()

    ok, remote = _git(path, 'remote', 'get-url', 'origin')
    if ok:
        out['remote'] = remote.strip()

    ok, log = _git(path, 'log', '-' + str(int(limit)), '--pretty=format:' + _LOG_FMT)
    if ok:
        for line in log.splitlines():
            parts = line.split('\x1f')
            if len(parts) < 6:
                continue
            out['commits'].append({
                'sha': parts[0],
                'short_sha': parts[1],
                'author': parts[2],
                'email': parts[3],
                'date': parts[4],
                'subject': parts[5],
                'refs': parts[6] if len(parts) > 6 else '',
            })
        if out['commits']:
            out['last_activity'] = out['commits'][0]['date']

    ok, status = _git(path, 'status', '--porcelain')
    if ok:
        out['dirty'] = len([ln for ln in status.splitlines() if ln.strip()])

    # Ahead/behind vs the tracked upstream, when one exists. No network access:
    # this compares against the last-fetched remote ref, not the live remote.
    ok, upstream = _git(path, 'rev-parse', '--abbrev-ref', '--symbolic-full-name', '@{u}')
    if ok and upstream.strip():
        ok2, counts = _git(path, 'rev-list', '--left-right', '--count',
                           upstream.strip() + '...HEAD')
        if ok2:
            bits = counts.split()
            if len(bits) == 2:
                try:
                    out['behind'], out['ahead'] = int(bits[0]), int(bits[1])
                except ValueError:
                    pass
    return out


def api_repos(request):
    err = _require_module(request, 'repos')
    if err:
        return err
    rows = []
    for r in Repository.objects.select_related('server').all():
        d = _repo_dict(r)
        h = _repo_history(r, limit=1)
        d.update({
            'available': h['available'],
            'error': h['error'],
            'branch': h['branch'],
            'dirty': h['dirty'],
            'ahead': h['ahead'],
            'behind': h['behind'],
            'remote': h['remote'],
            'last_commit': h['commits'][0] if h['commits'] else None,
        })
        rows.append(d)
    return JsonResponse({
        'repos': rows,
        'total': len(rows),
        'linked': sum(1 for r in rows if r['available']),
        'dirty': sum(1 for r in rows if (r['dirty'] or 0) > 0),
    })


def api_repo_history(request, pk):
    err = _require_module(request, 'repos')
    if err:
        return err
    repo = Repository.objects.filter(id=pk).first()
    if not repo:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    try:
        limit = min(200, max(1, int(request.GET.get('limit', 30))))
    except (TypeError, ValueError):
        limit = 30
    payload = {'repo': _repo_dict(repo)}
    payload.update(_repo_history(repo, limit=limit))
    return JsonResponse(payload)


_REPO_TEXT_FIELDS = (
    'name', 'company', 'description', 'local_path', 'remote_url',
    'provider', 'default_branch', 'notes',
)


def _apply_repo_fields(rec, data):
    for f in _REPO_TEXT_FIELDS:
        if f in data:
            value = data.get(f)
            setattr(rec, f, (value or '').strip() if isinstance(value, str) else (value or ''))
    if 'order' in data:
        try:
            rec.order = int(data.get('order') or 0)
        except (TypeError, ValueError):
            pass
    if 'server' in data:
        sid = data.get('server')
        rec.server = ServerRecord.objects.filter(id=sid).first() if sid else None


@csrf_exempt
@require_http_methods(["POST"])
def api_repo_create(request):
    err = _require_module(request, 'repos')
    if err:
        return err
    rec = Repository(order=Repository.objects.count())
    _apply_repo_fields(rec, _body(request))
    if not rec.name:
        return JsonResponse({'detail': 'A repository name is required.'}, status=400)
    rec.save()
    return JsonResponse(_repo_dict(rec), status=201)


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_repo_update(request, pk):
    err = _require_module(request, 'repos')
    if err:
        return err
    rec = Repository.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    _apply_repo_fields(rec, _body(request))
    if not rec.name:
        return JsonResponse({'detail': 'A repository name is required.'}, status=400)
    rec.save()
    return JsonResponse(_repo_dict(rec))


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_repo_delete(request, pk):
    err = _require_module(request, 'repos')
    if err:
        return err
    rec = Repository.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    rec.delete()
    return JsonResponse({'ok': True})


# ══════════════════════════════════════════════════════════════════════════════
# Planner (ProjectTask)
# ══════════════════════════════════════════════════════════════════════════════

def _task_dict(t):
    return {
        'id': t.id,
        'title': t.title,
        'description': t.description,
        'status': t.status,
        'priority': t.priority,
        'project_name': t.project_name,
        'company': t.company,
        'company_display': t.get_company_display() if t.company else '',
        'parent': t.parent_id,
        'start_date': t.start_date.isoformat() if t.start_date else None,
        'end_date': t.end_date.isoformat() if t.end_date else None,
        'start_time': t.start_time.strftime('%H:%M') if t.start_time else None,
        'end_time': t.end_time.strftime('%H:%M') if t.end_time else None,
        'created_at': t.created_at.isoformat() if t.created_at else None,
        'updated_at': t.updated_at.isoformat() if t.updated_at else None,
    }


_TASK_STATUSES = [c[0] for c in ProjectTask.STATUS_CHOICES]
_TASK_PRIORITIES = [c[0] for c in ProjectTask.PRIORITY_CHOICES]
_TASK_COMPANIES = [c[0] for c in ProjectTask.COMPANY_CHOICES]


def _coerce_time(raw):
    """Normalise an incoming 'HH:MM' value to a `time` (or None). Returns (value, ok)."""
    if raw is None:
        return None, True
    if isinstance(raw, time):
        return raw, True
    if isinstance(raw, str):
        raw = raw.strip()
        if not raw:
            return None, True
        try:
            # Same as _coerce_date: parse_time raises on values like 99:99.
            parsed = parse_time(raw)
        except ValueError:
            return None, False
        return (parsed, True) if parsed else (None, False)
    return None, False


def _apply_task_fields(rec, data):
    """Copy request fields onto `rec`. Returns a list of validation errors."""
    errors = []
    for f in ('title', 'description', 'project_name'):
        if f in data:
            value = data.get(f)
            setattr(rec, f, (value or '').strip() if isinstance(value, str) else (value or ''))
    if data.get('status') in _TASK_STATUSES:
        rec.status = data['status']
    if data.get('priority') in _TASK_PRIORITIES:
        rec.priority = data['priority']
    if 'company' in data:
        value = (data.get('company') or '').strip()
        if value and value not in _TASK_COMPANIES:
            errors.append('company must be one of: ' + ', '.join(_TASK_COMPANIES) + '.')
        else:
            rec.company = value
    for f in ('start_date', 'end_date'):
        if f in data:
            value, ok = _coerce_date(data.get(f))
            if not ok:
                errors.append(f'{f} must be a date in YYYY-MM-DD format.')
                continue
            setattr(rec, f, value)
    for f in ('start_time', 'end_time'):
        if f in data:
            value, ok = _coerce_time(data.get(f))
            if not ok:
                errors.append(f'{f} must be a time in HH:MM format.')
                continue
            setattr(rec, f, value)
    if 'parent' in data:
        pid = data.get('parent')
        rec.parent = ProjectTask.objects.filter(id=pid).first() if pid else None
    return errors


def api_planner_tasks(request):
    err = _require_module(request, 'planner')
    if err:
        return err
    qs = ProjectTask.objects.all()
    project = (request.GET.get('project') or '').strip()
    if project:
        qs = qs.filter(project_name=project)
    rows = [_task_dict(t) for t in qs]
    counts = {s: 0 for s in _TASK_STATUSES}
    for r in rows:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    projects = sorted({r['project_name'] for r in rows if r['project_name']})
    return JsonResponse({
        'tasks': rows,
        'counts': counts,
        'projects': projects,
        'statuses': list(ProjectTask.STATUS_CHOICES),
        'priorities': list(ProjectTask.PRIORITY_CHOICES),
        'companies': list(ProjectTask.COMPANY_CHOICES),
        'total': len(rows),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_planner_task_create(request):
    err = _require_module(request, 'planner')
    if err:
        return err
    rec = ProjectTask()
    errors = _apply_task_fields(rec, _body(request))
    if not rec.title:
        return JsonResponse({'detail': 'A task title is required.'}, status=400)
    if errors:
        return JsonResponse({'detail': ' '.join(errors)}, status=400)
    rec.save()
    return JsonResponse(_task_dict(rec), status=201)


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_planner_task_update(request, pk):
    err = _require_module(request, 'planner')
    if err:
        return err
    rec = ProjectTask.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    errors = _apply_task_fields(rec, _body(request))
    if not rec.title:
        return JsonResponse({'detail': 'A task title is required.'}, status=400)
    if errors:
        return JsonResponse({'detail': ' '.join(errors)}, status=400)
    rec.save()
    return JsonResponse(_task_dict(rec))


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_planner_task_delete(request, pk):
    err = _require_module(request, 'planner')
    if err:
        return err
    rec = ProjectTask.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    rec.delete()
    return JsonResponse({'ok': True})
