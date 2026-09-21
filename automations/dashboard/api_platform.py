"""JSON API for the Sentinel platform modules: Domains, Repositories, Project Tracker.

Kept out of views.py (already ~6k lines) since these are self-contained CRUD
endpoints. Access control reuses `_require_module` so permissions behave exactly
like the existing servers/docs modules.
"""
import json
import os
import subprocess
from datetime import date, time

from django.http import JsonResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_time
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from django.contrib.auth.models import User

from .models import (Domain, Repository, ProjectTask, ProjectMeta, ProjectList,
                     Workspace, ServerRecord)
from .views import _require_module
from . import activity


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


def _github_fallback(rec):
    """Latest commit from the GitHub API, for a repo with no local checkout.

    Returns only the keys it can fill, so a caller can `update()` with it and
    leave the git-derived fields (dirty, ahead, behind) alone - those have no
    meaning without a working copy, and inventing zeroes would claim the repo
    is clean when nothing was checked.
    """
    from . import github_api as gh

    url = rec.remote_url or ''
    if 'github.com/' not in url or not gh.is_configured():
        return {}
    full_name = url.split('github.com/', 1)[1].strip('/')
    full_name = full_name[:-4] if full_name.endswith('.git') else full_name

    ok, commits = gh.list_commits(full_name, limit=1)
    if not ok or not commits:
        return {}
    c = commits[0]
    return {
        'available': True,
        'source': 'github',
        'error': None,
        'branch': rec.default_branch or 'main',
        'remote': url,
        'last_commit': {
            'sha': c['sha'], 'short_sha': c['short_sha'],
            'author': c['author'], 'email': c['email'],
            'date': c['date'], 'subject': c['subject'], 'refs': '',
        },
    }


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
            'source': 'git' if h['available'] else None,
        })
        # No local clone does not mean unreadable. If the repo is on the
        # connected GitHub account, its history is a request away - and saying
        # "unreadable" about something we can plainly read is just wrong.
        if not h['available']:
            d.update(_github_fallback(r))
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
def api_task_timer(request, pk):
    """Start or stop the running timer on a task.

    Starting stamps the moment; stopping adds the elapsed time to actual_hours
    and clears the stamp. The elapsed figure is worked out here rather than
    sent by the browser, so a wrong clock or a tampered request cannot inflate
    somebody's logged hours.

    Only one task runs at a time per person, which is what ClickUp does and
    what people expect: starting a second task stops the first.
    """
    err = _require_module(request, 'tasks')
    if err:
        return err
    rec = ProjectTask.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)

    action = (_body(request).get('action') or '').strip().lower()
    now = timezone.now()

    if action == 'start':
        if rec.timer_started_at:
            return JsonResponse(_task_dict(rec))       # already running
        # Stop whatever else is running first.
        for other in ProjectTask.objects.filter(timer_started_at__isnull=False):
            _stop_timer(other, now)
        rec.timer_started_at = now
        rec.save(update_fields=['timer_started_at', 'updated_at'])
    elif action == 'stop':
        _stop_timer(rec, now)
    else:
        return JsonResponse({'detail': "action must be 'start' or 'stop'."},
                            status=400)
    return JsonResponse(_task_dict(rec))


def _stop_timer(rec, now):
    """Fold a running timer into actual_hours and clear it."""
    if not rec.timer_started_at:
        return
    hours = (now - rec.timer_started_at).total_seconds() / 3600
    # Under half a minute is a mis-click, not work.
    if hours >= 0.008:
        rec.actual_hours = round(float(rec.actual_hours or 0) + hours, 2)
    rec.timer_started_at = None
    rec.save(update_fields=['actual_hours', 'timer_started_at', 'updated_at'])


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
# Project Tracker (ProjectTask) - tasks, subtasks and priorities
# ══════════════════════════════════════════════════════════════════════════════

def _task_dict(t):
    return {
        'id': t.id,
        'title': t.title,
        'description': t.description,
        'status': t.status,
        'priority': t.priority,
        'project_name': t.project_name,
        'list_name': t.list_name,
        'company': t.company,
        'company_display': t.get_company_display() if t.company else '',
        'parent': t.parent_id,
        'start_date': t.start_date.isoformat() if t.start_date else None,
        'end_date': t.end_date.isoformat() if t.end_date else None,
        'start_time': t.start_time.strftime('%H:%M') if t.start_time else None,
        'end_time': t.end_time.strftime('%H:%M') if t.end_time else None,
        'estimated_hours': float(t.estimated_hours) if t.estimated_hours is not None else None,
        'actual_hours': float(t.actual_hours) if t.actual_hours is not None else None,
        # The browser needs the start instant, not an elapsed figure, or the
        # clock freezes between polls.
        'timer_started_at': (t.timer_started_at.isoformat()
                             if t.timer_started_at else None),
        # Who the work belongs to. The workload view groups on this, so it
        # ships with every task rather than being fetched per row.
        'assignees': [{'id': u.id,
                       'name': (u.get_full_name() or u.username).strip()}
                      for u in t.assigned_users.all()],
        'duration_days': t.duration_days,
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
    for f in ('title', 'description', 'project_name', 'list_name'):
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
    for f in ('estimated_hours', 'actual_hours'):
        if f in data:
            raw = data.get(f)
            if raw in (None, ''):
                setattr(rec, f, None)
                continue
            try:
                val = float(raw)
            except (TypeError, ValueError):
                errors.append(f'{f} must be a number of hours.')
                continue
            if val < 0 or val > 99999:
                errors.append(f'{f} must be between 0 and 99999.')
                continue
            setattr(rec, f, round(val, 2))
    if 'parent' in data:
        pid = data.get('parent')
        rec.parent = ProjectTask.objects.filter(id=pid).first() if pid else None
    return errors


def api_planner_tasks(request):
    err = _require_module(request, 'tasks')
    if err:
        return err
    qs = ProjectTask.objects.all().prefetch_related('assigned_users')
    project = (request.GET.get('project') or '').strip()
    if project:
        qs = qs.filter(project_name=project)
    rows = [_task_dict(t) for t in qs]
    counts = {s: 0 for s in _TASK_STATUSES}
    for r in rows:
        counts[r['status']] = counts.get(r['status'], 0) + 1
    projects = sorted({r['project_name'] for r in rows if r['project_name']})
    lists = {}
    for r in rows:
        lists.setdefault(r['project_name'] or '', set()).add(r['list_name'] or '')
    # A declared list has no tasks yet, so it would be invisible without this.
    # Workspace-level lists are not keyed by project, so they are excluded here.
    for pl in ProjectList.objects.filter(workspace__isnull=True):
        lists.setdefault(pl.project_name, set()).add(pl.name)
    lists = {k: sorted(v - {''}) for k, v in lists.items()}
    return JsonResponse({
        'tasks': rows,
        'counts': counts,
        'projects': projects,
        'lists': lists,
        # Everyone a task can be assigned to, so the picker needs no second
        # request and no loading state of its own.
        'people': [{'id': u.id,
                    'name': (u.get_full_name() or u.username).strip(),
                    'username': u.username}
                   for u in User.objects.filter(is_active=True)
                   .order_by('first_name', 'username')],
        'statuses': list(ProjectTask.STATUS_CHOICES),
        'priorities': list(ProjectTask.PRIORITY_CHOICES),
        'companies': list(ProjectTask.COMPANY_CHOICES),
        'total': len(rows),
    })


def api_task_projects(request):
    """Just the project names and open counts.

    The sidebar needs this on every page; returning the full task list for it
    would ship thousands of rows to render a handful of links.
    """
    err = _require_module(request, 'tasks')
    if err:
        return err
    rows = {}
    for name, status, lst in ProjectTask.objects.filter(parent__isnull=True).values_list(
            'project_name', 'status', 'list_name'):
        key = name or ''
        entry = rows.setdefault(key, {'name': key, 'open': 0, 'total': 0, 'lists': set()})
        entry['total'] += 1
        if status != 'done':
            entry['open'] += 1
        if lst:
            entry['lists'].add(lst)
    for pl in ProjectList.objects.filter(workspace__isnull=True):
        entry = rows.setdefault(
            pl.project_name, {'name': pl.project_name, 'open': 0, 'total': 0, 'lists': set()})
        entry['lists'].add(pl.name)
    default_ws = Workspace.default()
    meta = {
        m.name: m for m in ProjectMeta.objects.select_related('workspace')
    }
    # A project that has been declared but holds nothing yet is still a
    # project. Without this it would vanish the moment it was created and
    # reappear only once somebody put a task in it - which is not something
    # anybody could work out from the outside.
    for name in meta:
        if name:
            rows.setdefault(name,
                            {'name': name, 'open': 0, 'total': 0, 'lists': set()})
    out = []
    for v in rows.values():
        m = meta.get(v['name'])
        ws = (m.workspace if m and m.workspace else default_ws)
        out.append({
            **v,
            'lists': sorted(v['lists']),
            'color': m.color if m else '',
            'icon': m.icon if m else '',
            'logo_url': m.logo_url if m else '',
            'workspace': ws.name,
        })
    # Named projects first, alphabetically; unfiled work last.
    out.sort(key=lambda r: (r['name'] == '', r['name'].lower()))

    ws_lists = {}
    for pl in ProjectList.objects.filter(workspace__isnull=False).select_related('workspace'):
        ws_lists.setdefault(pl.workspace.name, []).append(pl.name)
    workspaces = [
        {'name': w.name, 'color': w.color, 'icon': w.icon, 'logo_url': w.logo_url,
         'is_default': w.is_default,
         'projects': [r['name'] for r in out if r['workspace'] == w.name],
         'lists': sorted(ws_lists.get(w.name, []))}
        for w in Workspace.objects.all()
    ]
    return JsonResponse({
        'projects': out,
        'workspaces': workspaces,
        'default_workspace': default_ws.name,
        'total': len(out),
    })


def _apply_assignees(rec, data):
    """Set who a task belongs to. Returns an error string, or None.

    A many-to-many cannot be set before the row exists, so this runs after
    save rather than inside _apply_task_fields with the ordinary columns.

    Omitting the key leaves the assignees alone; sending an empty list
    unassigns. Those have to be different, or no request could ever clear the
    field.
    """
    if 'assignees' not in data:
        return None
    raw = data.get('assignees') or []
    if not isinstance(raw, list):
        return 'assignees must be a list of user ids.'
    try:
        ids = [int(x) for x in raw]
    except (TypeError, ValueError):
        return 'assignees must be a list of user ids.'
    users = list(User.objects.filter(id__in=ids, is_active=True))
    missing = set(ids) - {u.id for u in users}
    if missing:
        return ('No active user with id '
                + ', '.join(str(m) for m in sorted(missing)) + '.')
    rec.assigned_users.set(users)
    return None


@csrf_exempt
@require_http_methods(["POST"])
def api_planner_task_create(request):
    err = _require_module(request, 'tasks')
    if err:
        return err
    rec = ProjectTask()
    errors = _apply_task_fields(rec, _body(request))
    if not rec.title:
        return JsonResponse({'detail': 'A task title is required.'}, status=400)
    if errors:
        return JsonResponse({'detail': ' '.join(errors)}, status=400)
    rec.save()
    problem = _apply_assignees(rec, _body(request))
    if problem:
        return JsonResponse({'detail': problem}, status=400)
    activity.record(request, 'created', 'task', obj=rec, label=rec.title,
                    project=rec.project_name or '')
    return JsonResponse(_task_dict(rec), status=201)


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_planner_task_update(request, pk):
    err = _require_module(request, 'tasks')
    if err:
        return err
    rec = ProjectTask.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    was_status = rec.status
    errors = _apply_task_fields(rec, _body(request))
    if not rec.title:
        return JsonResponse({'detail': 'A task title is required.'}, status=400)
    if errors:
        return JsonResponse({'detail': ' '.join(errors)}, status=400)
    rec.save()
    problem = _apply_assignees(rec, _body(request))
    if problem:
        return JsonResponse({'detail': problem}, status=400)

    # A status change is the interesting event; everything else is "updated".
    # Dragging a card across the board should read as "completed", not as one
    # more edit among many.
    if rec.status != was_status:
        verb = ('completed' if rec.status == 'done'
                else 'reopened' if was_status == 'done' else 'updated')
        detail = '' if verb != 'updated' else f'moved to {rec.get_status_display()}'
    else:
        verb, detail = 'updated', ''
    activity.record(request, verb, 'task', obj=rec, label=rec.title,
                    detail=detail, project=rec.project_name or '')
    return JsonResponse(_task_dict(rec))


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_planner_task_delete(request, pk):
    err = _require_module(request, 'tasks')
    if err:
        return err
    rec = ProjectTask.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    # Read the label before deleting: afterwards there is nothing to read it
    # from, and "deleted task" with no name is not worth recording.
    title, project = rec.title, rec.project_name or ''
    rec.delete()
    activity.record(request, 'deleted', 'task', object_id=pk, label=title,
                    project=project)
    return JsonResponse({'ok': True})


# ══════════════════════════════════════════════════════════════════════════════
# Project-level actions (rename / recolour / delete)
# ══════════════════════════════════════════════════════════════════════════════

def _clean_icon(raw):
    """An icon is a glyph, not a sentence. Returns (value, error)."""
    icon = (raw or '').strip()
    if len(icon) > 8:
        return None, 'icon must be a single emoji or a couple of characters.'
    return icon, None


def _clean_logo(raw):
    """Only http(s) image URLs - a data: or javascript: URL would be rendered."""
    url = (raw or '').strip()
    if not url:
        return '', None
    if not url.lower().startswith(('http://', 'https://')):
        return None, 'logo_url must start with http:// or https://.'
    if len(url) > 500:
        return None, 'logo_url is too long (max 500).'
    return url, None


_PROJECT_COLORS = {
    '', 'blue', 'green', 'amber', 'red', 'purple', 'teal', 'pink', 'slate',
}


@csrf_exempt
@require_http_methods(["POST"])
def api_project_create(request):
    """Declare a project, before anything is in it.

    Until now a project came into being as a side effect of naming one on a
    task, so there was no way to set one up in advance - which is what
    somebody wants when they are about to file work under it.
    """
    err = _require_module(request, 'tasks')
    if err:
        return err
    data = _body(request)
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'detail': 'name is required.'}, status=400)
    if len(name) > 100:
        return JsonResponse({'detail': 'name is too long (max 100).'}, status=400)
    if ProjectTask.objects.filter(project_name=name).exists()             or ProjectMeta.objects.filter(name=name).exists():
        return JsonResponse({'detail': f'A project named "{name}" already exists.'},
                            status=409)

    ws = None
    ws_name = (data.get('workspace') or '').strip()
    if ws_name:
        ws = Workspace.objects.filter(name=ws_name).first()
        if ws is None:
            return JsonResponse({'detail': f'No workspace named "{ws_name}".'},
                                status=404)
    rec = ProjectMeta.objects.create(
        name=name, workspace=ws or Workspace.default(),
        color=(data.get('color') or '').strip(),
        icon=(data.get('icon') or '').strip(),
    )
    return JsonResponse({
        'name': rec.name,
        'workspace': rec.workspace.name if rec.workspace else '',
        'color': rec.color, 'icon': rec.icon,
        'open': 0, 'total': 0, 'lists': [],
    }, status=201)


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_project_update(request):
    """Rename a project and/or set its colour.

    Renaming rewrites `project_name` on every task in it - that string *is* the
    project, so there is nothing else to update.
    """
    err = _require_module(request, 'tasks')
    if err:
        return err
    data = _body(request)
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'detail': 'name is required.'}, status=400)

    qs = ProjectTask.objects.filter(project_name=name)
    if not qs.exists():
        return JsonResponse({'detail': f'No project named "{name}".'}, status=404)

    renamed = 0
    new_name = (data.get('new_name') or '').strip()
    if new_name and new_name != name:
        if len(new_name) > 100:
            return JsonResponse({'detail': 'new_name is too long (max 100).'}, status=400)
        if ProjectTask.objects.filter(project_name=new_name).exists():
            return JsonResponse(
                {'detail': f'A project named "{new_name}" already exists.'}, status=409)
        renamed = qs.update(project_name=new_name)
        ProjectMeta.objects.filter(name=name).update(name=new_name)
        name = new_name

    updates = {}
    if 'color' in data:
        color = (data.get('color') or '').strip().lower()
        if color not in _PROJECT_COLORS:
            return JsonResponse(
                {'detail': 'color must be one of: ' + ', '.join(sorted(c for c in _PROJECT_COLORS if c)) + '.'},
                status=400)
        updates['color'] = color
    if 'icon' in data:
        icon, e = _clean_icon(data.get('icon'))
        if e:
            return JsonResponse({'detail': e}, status=400)
        updates['icon'] = icon
    if 'logo_url' in data:
        logo, e = _clean_logo(data.get('logo_url'))
        if e:
            return JsonResponse({'detail': e}, status=400)
        updates['logo_url'] = logo
    if updates:
        ProjectMeta.objects.update_or_create(name=name, defaults=updates)

    meta = ProjectMeta.objects.filter(name=name).first()
    return JsonResponse({
        'name': name,
        'color': meta.color if meta else '',
        'icon': meta.icon if meta else '',
        'logo_url': meta.logo_url if meta else '',
        'tasks_renamed': renamed,
    })


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_project_delete(request):
    """Delete a project and every task in it.

    Irreversible, so it refuses unless the caller echoes back the exact task
    count it expects to remove - a stale UI cannot delete more than it showed.
    """
    err = _require_module(request, 'tasks')
    if err:
        return err
    data = _body(request)
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'detail': 'name is required.'}, status=400)

    qs = ProjectTask.objects.filter(project_name=name)
    total = qs.count()
    if total == 0:
        return JsonResponse({'detail': f'No project named "{name}".'}, status=404)

    expected = data.get('expected_tasks')
    if expected is not None and int(expected) != total:
        return JsonResponse(
            {'detail': f'This project now holds {total} tasks, not {expected}. Refresh and try again.'},
            status=409)

    deleted, _ = qs.delete()
    ProjectMeta.objects.filter(name=name).delete()
    return JsonResponse({'ok': True, 'deleted': deleted, 'name': name})


# ══════════════════════════════════════════════════════════════════════════════
# Workspaces (the level above projects)
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_workspace_save(request):
    """Create a workspace, or rename / recolour an existing one."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    data = _body(request)
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'detail': 'name is required.'}, status=400)
    if len(name) > 100:
        return JsonResponse({'detail': 'name is too long (max 100).'}, status=400)

    ws = Workspace.objects.filter(name=name).first()
    if ws is None:
        # Creating.
        icon, e = _clean_icon(data.get('icon'))
        if e:
            return JsonResponse({'detail': e}, status=400)
        logo, e = _clean_logo(data.get('logo_url'))
        if e:
            return JsonResponse({'detail': e}, status=400)
        ws = Workspace.objects.create(
            name=name,
            color=(data.get('color') or '').strip().lower(),
            icon=icon,
            logo_url=logo,
            order=Workspace.objects.count(),
        )
        return JsonResponse({'name': ws.name, 'color': ws.color, 'icon': ws.icon,
                             'logo_url': ws.logo_url, 'created': True}, status=201)

    new_name = (data.get('new_name') or '').strip()
    fields = []
    if new_name and new_name != name:
        if Workspace.objects.filter(name=new_name).exists():
            return JsonResponse(
                {'detail': f'A workspace named "{new_name}" already exists.'}, status=409)
        ws.name = new_name
        fields.append('name')
    if 'color' in data:
        color = (data.get('color') or '').strip().lower()
        if color not in _PROJECT_COLORS:
            return JsonResponse({'detail': 'Unknown colour.'}, status=400)
        ws.color = color
        fields.append('color')
    if 'icon' in data:
        icon, e = _clean_icon(data.get('icon'))
        if e:
            return JsonResponse({'detail': e}, status=400)
        ws.icon = icon
        fields.append('icon')
    if 'logo_url' in data:
        logo, e = _clean_logo(data.get('logo_url'))
        if e:
            return JsonResponse({'detail': e}, status=400)
        ws.logo_url = logo
        fields.append('logo_url')
    if not fields:
        return JsonResponse({'detail': 'Nothing to update.'}, status=400)
    ws.save(update_fields=fields)
    return JsonResponse({'name': ws.name, 'color': ws.color, 'icon': ws.icon,
                         'logo_url': ws.logo_url, 'created': False})


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_workspace_delete(request):
    """Delete a workspace. Its projects move to the default one - never deleted."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    data = _body(request)
    name = (data.get('name') or '').strip()
    ws = Workspace.objects.filter(name=name).first()
    if ws is None:
        return JsonResponse({'detail': f'No workspace named "{name}".'}, status=404)
    if ws.is_default:
        return JsonResponse(
            {'detail': 'The default workspace cannot be deleted - it is where projects fall back to.'},
            status=409)

    fallback = Workspace.default()
    moved = ProjectMeta.objects.filter(workspace=ws).update(workspace=fallback)
    ws.delete()
    return JsonResponse({'ok': True, 'deleted': name, 'projects_moved': moved,
                         'moved_to': fallback.name})


@csrf_exempt
@require_http_methods(["POST"])
def api_project_move(request):
    """Put a project in a workspace."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    data = _body(request)
    project = (data.get('project') or '').strip()
    ws_name = (data.get('workspace') or '').strip()
    if not project:
        return JsonResponse({'detail': 'project is required.'}, status=400)
    if not ProjectTask.objects.filter(project_name=project).exists():
        return JsonResponse({'detail': f'No project named "{project}".'}, status=404)
    ws = Workspace.objects.filter(name=ws_name).first()
    if ws is None:
        return JsonResponse({'detail': f'No workspace named "{ws_name}".'}, status=404)
    ProjectMeta.objects.update_or_create(name=project, defaults={'workspace': ws})
    return JsonResponse({'ok': True, 'project': project, 'workspace': ws.name})


@csrf_exempt
@require_http_methods(["POST"])
def api_list_create(request):
    """Declare a list inside a project - no first task required."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    data = _body(request)
    project = (data.get('project') or '').strip()
    ws_name = (data.get('workspace') or '').strip()
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'detail': 'name is required.'}, status=400)
    if len(name) > 100:
        return JsonResponse({'detail': 'name is too long (max 100).'}, status=400)

    # A list belongs to a project, or - when none is given - straight to a
    # workspace. Both at once would make it ambiguous where it lives.
    ws = None
    if ws_name and not project:
        ws = Workspace.objects.filter(name=ws_name).first()
        if ws is None:
            return JsonResponse({'detail': f'No workspace named "{ws_name}".'}, status=404)
    if not project and ws is None:
        return JsonResponse(
            {'detail': 'Give either a project or a workspace for the list to live in.'},
            status=400)

    # An existing list is a no-op rather than an error: the user asked for a
    # list with this name and now there is one.
    already_in_use = bool(project) and ProjectTask.objects.filter(
        project_name=project, list_name=name).exists()
    obj, created = ProjectList.objects.get_or_create(
        project_name=project, workspace=ws, name=name,
        defaults={'order': ProjectList.objects.filter(
            project_name=project, workspace=ws).count()},
    )
    return JsonResponse({
        'project': project or '',
        'workspace': ws.name if ws else '',
        'name': obj.name,
        'created': created and not already_in_use,
    }, status=201 if created else 200)


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_list_delete(request):
    """Stop declaring a list. Tasks already in it keep their label and their work."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    data = _body(request)
    project = (data.get('project') or '').strip()
    ws_name = (data.get('workspace') or '').strip()
    name = (data.get('name') or '').strip()
    qs = ProjectList.objects.filter(name=name)
    if project:
        qs = qs.filter(project_name=project)
    elif ws_name:
        qs = qs.filter(workspace__name=ws_name)
    n, _ = qs.delete()
    in_use = ProjectTask.objects.filter(project_name=project, list_name=name).count() if project else 0
    return JsonResponse({'ok': True, 'removed_declaration': n, 'tasks_still_in_list': in_use})
