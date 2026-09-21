import os
from dotenv import load_dotenv
load_dotenv()
from django.shortcuts import render, redirect
from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from functools import wraps


def page_access(*keys):
    """Require the user to have at least one of the given page access flags
    (superusers always pass). Apply AFTER @login_required."""
    def decorator(view):
        @wraps(view)
        def _wrapped(request, *args, **kwargs):
            u = request.user
            if u.is_superuser:
                return view(request, *args, **kwargs)
            try:
                p = u.profile
            except Exception:
                raise PermissionDenied('No profile')
            if any(getattr(p, f'can_{k}', False) for k in keys):
                return view(request, *args, **kwargs)
            raise PermissionDenied('You do not have access to this page.')
        return _wrapped
    return decorator


def admin_required(view):
    """Only superusers may access. Apply AFTER @login_required."""
    @wraps(view)
    def _wrapped(request, *args, **kwargs):
        if not request.user.is_superuser:
            raise PermissionDenied('Admin only.')
        return view(request, *args, **kwargs)
    return _wrapped
from django.views.decorators.http import require_http_methods
from django.db.models import Sum, Count
from django.db.models.functions import ExtractYear
from django.db import OperationalError, ProgrammingError, connection
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.conf import settings as django_settings
from django.utils import timezone as django_timezone
from django.core import signing
from .models import TurnoverData, ProjectTask, UserProfile, USEUContact, TouchpointTemplate
from .models import DocCompany, DocSystem, DocDocument, DocFolder, ServerRecord
from .models import Domain, Repository
from django.contrib.auth.models import User, Group
from .google_drive import sync_google_drive_data, get_progress, update_progress, get_last_sync
from . import onedrive_sync
import threading
import json
import msal
import requests as http_requests
import base64
import os
import boto3
from botocore.exceptions import ClientError
import re
import time
from datetime import datetime
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo


def login_view(request):
    if request.user.is_authenticated:
        return redirect('home')

    error = None
    if request.method == 'POST':
        username = request.POST.get('username')
        password = request.POST.get('password')
        user = authenticate(request, username=username, password=password)
        if user is not None:
            login(request, user)
            return redirect('home')
        else:
            error = 'Invalid username or password'

    return render(request, 'login.html', {'error': error})


def logout_view(request):
    logout(request)
    return redirect('login')


# ── JSON auth API (for the Sentinel Next.js frontend) ───────────────────────────
@csrf_exempt
@require_http_methods(["POST"])
def api_login(request):
    """JSON login. Authenticates and sets the Django session cookie."""
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({'detail': 'Invalid request body.'}, status=400)
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return JsonResponse({'detail': 'Username and password are required.'}, status=400)
    user = authenticate(request, username=username, password=password)
    if user is None:
        return JsonResponse({'detail': 'Invalid username or password.'}, status=401)
    login(request, user)
    return JsonResponse({
        'ok': True,
        'user': {
            'username': user.username,
            'is_staff': user.is_staff,
            'is_superuser': user.is_superuser,
        },
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_logout(request):
    logout(request)
    return JsonResponse({'ok': True})


def api_me(request):
    """Return the current session user, or 401 if not signed in."""
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    u = request.user
    return JsonResponse({
        'id': u.id,
        'username': u.username,
        'full_name': u.get_full_name() or u.username,
        'is_staff': u.is_staff,
        'is_superuser': u.is_superuser,
        'is_admin': u.is_superuser,
        'modules': _user_modules(u),
    })


# ── User management + module access (for the Sentinel frontend) ─────────────────
# Module access is stored via Django Groups named "mod_<key>" so no schema
# migration is needed. Superusers implicitly have every module.
SENTINEL_MODULES = [
    {'key': 'data', 'label': 'Data Analysis', 'desc': 'Automated reports, station syncs and sync logs.'},
    {'key': 'tasks', 'label': 'Project Tracker', 'desc': 'Tasks, subtasks and priorities.'},
    {'key': 'client_requests', 'label': 'Client Requests', 'desc': 'Send clients questions and collect their answers.'},
    {'key': 'handbook', 'label': 'Handbook', 'desc': 'How we work, and how to get access to what we run.'},
    {'key': 'sites', 'label': 'Client Sites', 'desc': 'Generate and publish websites from client briefs.'},
    {'key': 'servers', 'label': 'Servers', 'desc': 'Server inventory, live monitoring, access and credentials.'},
    {'key': 'documentation', 'label': 'Documentation', 'desc': 'Company systems, folders and documents.'},
    {'key': 'domains', 'label': 'Domains', 'desc': 'Domain registrations, DNS, SSL and renewal dates.'},
    {'key': 'repos', 'label': 'Repositories', 'desc': 'Code repositories and their recent commit history.'},
]
_MODULE_KEYS = [m['key'] for m in SENTINEL_MODULES]


def _user_modules(user):
    """Return the list of module keys this user can access."""
    if user.is_superuser:
        return list(_MODULE_KEYS)
    names = set(user.groups.values_list('name', flat=True))
    return [k for k in _MODULE_KEYS if f'mod_{k}' in names]


def _set_user_modules(user, keys):
    """Replace the user's module groups with the given keys."""
    wanted = {k for k in (keys or []) if k in _MODULE_KEYS}
    # Drop every module group, then add back the wanted ones.
    for g in list(user.groups.filter(name__startswith='mod_')):
        user.groups.remove(g)
    for k in wanted:
        g, _ = Group.objects.get_or_create(name=f'mod_{k}')
        user.groups.add(g)


def _set_full_name(user, full_name):
    parts = (full_name or '').strip().split(' ', 1)
    user.first_name = parts[0] if parts and parts[0] else ''
    user.last_name = parts[1] if len(parts) > 1 else ''


def _user_dict(user):
    return {
        'id': user.id,
        'username': user.username,
        'full_name': user.get_full_name() or user.username,
        'email': user.email or '',
        'is_admin': user.is_superuser,
        'is_active': user.is_active,
        'modules': _user_modules(user),
        'last_login': user.last_login.isoformat() if user.last_login else None,
        'date_joined': user.date_joined.isoformat() if user.date_joined else None,
    }


def _require_admin(request):
    """Return an error JsonResponse if the caller isn't an authenticated admin, else None."""
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    if not request.user.is_superuser:
        return JsonResponse({'detail': 'Administrator access required.'}, status=403)
    return None


def _require_module(request, key):
    """Return an error JsonResponse if the caller can't access the module, else None."""
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    if request.user.is_superuser or f'mod_{key}' in set(request.user.groups.values_list('name', flat=True)):
        return None
    return JsonResponse({'detail': 'You do not have access to this module.'}, status=403)


@csrf_exempt
@require_http_methods(["GET"])
def api_users(request):
    """Users with their module access and workspace allocations (admin only)."""
    err = _require_admin(request)
    if err:
        return err

    # Imported here rather than at module scope: workspace_access imports from
    # this module, and a top-level import would be circular.
    from .models import Workspace, WorkspaceMember

    users = User.objects.order_by('-is_superuser', 'username')
    grants = {}
    for m in WorkspaceMember.objects.select_related('workspace', 'user'):
        grants.setdefault(m.user_id, []).append({
            'workspace': m.workspace.name,
            'role': m.role,
            'role_display': m.get_role_display(),
            'notified': m.notified_at is not None,
        })

    rows = []
    for u in users:
        row = _user_dict(u)
        row['workspaces'] = sorted(grants.get(u.id, []), key=lambda g: g['workspace'])
        # A superuser reaches every workspace without a grant, so the count on
        # its own would read as "no access" for the people who have the most.
        row['sees_all_workspaces'] = u.is_superuser
        rows.append(row)

    return JsonResponse({
        'users': rows,
        'modules': SENTINEL_MODULES,
        'workspaces': [
            {'name': w.name, 'is_default': w.is_default}
            for w in Workspace.objects.all()
        ],
        'roles': list(WorkspaceMember.ROLE_CHOICES),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_user_create(request):
    """Create a user and allocate modules (admin only)."""
    err = _require_admin(request)
    if err:
        return err
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({'detail': 'Invalid request body.'}, status=400)
    username = (data.get('username') or '').strip()
    password = data.get('password') or ''
    if not username or not password:
        return JsonResponse({'detail': 'Username and password are required.'}, status=400)
    if User.objects.filter(username__iexact=username).exists():
        return JsonResponse({'detail': 'A user with that username already exists.'}, status=400)
    user = User.objects.create_user(username=username, password=password, email=(data.get('email') or '').strip())
    _set_full_name(user, data.get('full_name'))
    is_admin = bool(data.get('is_admin'))
    user.is_superuser = is_admin
    user.is_staff = is_admin
    user.is_active = bool(data.get('is_active', True))
    user.save()
    _set_user_modules(user, data.get('modules'))
    return JsonResponse({'ok': True, 'user': _user_dict(user)})


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_user_update(request, pk):
    """Update a user's details, module access, or password (admin only)."""
    err = _require_admin(request)
    if err:
        return err
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return JsonResponse({'detail': 'User not found.'}, status=404)
    try:
        data = json.loads(request.body or b"{}")
    except json.JSONDecodeError:
        return JsonResponse({'detail': 'Invalid request body.'}, status=400)

    if 'full_name' in data:
        _set_full_name(user, data.get('full_name'))
    if 'email' in data:
        user.email = (data.get('email') or '').strip()
    if 'username' in data:
        new_username = (data.get('username') or '').strip()
        if new_username and new_username != user.username:
            if User.objects.filter(username__iexact=new_username).exclude(pk=user.pk).exists():
                return JsonResponse({'detail': 'A user with that username already exists.'}, status=400)
            user.username = new_username
    if 'is_admin' in data:
        # Don't let the last admin demote themselves out of admin.
        making_non_admin = not bool(data.get('is_admin'))
        if making_non_admin and user.is_superuser and User.objects.filter(is_superuser=True, is_active=True).count() <= 1:
            return JsonResponse({'detail': 'Cannot remove the last administrator.'}, status=400)
        is_admin = bool(data.get('is_admin'))
        user.is_superuser = is_admin
        user.is_staff = is_admin
    if 'is_active' in data:
        if not bool(data.get('is_active')) and user.pk == request.user.pk:
            return JsonResponse({'detail': 'You cannot deactivate your own account.'}, status=400)
        user.is_active = bool(data.get('is_active'))
    if data.get('password'):
        user.set_password(data['password'])
    user.save()
    if 'modules' in data:
        _set_user_modules(user, data.get('modules'))
    return JsonResponse({'ok': True, 'user': _user_dict(user)})


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_user_delete(request, pk):
    """Delete a user (admin only)."""
    err = _require_admin(request)
    if err:
        return err
    if request.user.pk == pk:
        return JsonResponse({'detail': 'You cannot delete your own account.'}, status=400)
    try:
        user = User.objects.get(pk=pk)
    except User.DoesNotExist:
        return JsonResponse({'detail': 'User not found.'}, status=404)
    if user.is_superuser and User.objects.filter(is_superuser=True, is_active=True).count() <= 1:
        return JsonResponse({'detail': 'Cannot delete the last administrator.'}, status=400)
    user.delete()
    return JsonResponse({'ok': True})


def api_dashboard_summary(request):
    """JSON dashboard summary for the Sentinel frontend (mirrors the home view)."""
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)

    all_tables = {
        'turnover_data': 'Turnover', 'ppg_pnl': 'PPG', 'dor_pnl': 'DOR',
        'con_pnl': 'CON', 'atl_pnl': 'ATL', 'ccc_pnl': 'CCC',
        'ccd_pnl': 'CCD', 'fax_pnl': 'FAX', 'hnl_pnl': 'HNL',
        'hou_pnl': 'HOU', 'ics_pnl': 'ICS', 'imp_pnl': 'IMP',
        'jfk_pnl': 'JFK', 'lax_pnl': 'LAX', 'lcl_pnl': 'LCL',
        'ord_pnl': 'ORD', 'dfw_pnl': 'DFW', 'condor_dor_pnl': 'Condor+DOR',
        'import_ops': 'Import Ops', 'wip_accrual': 'WIP & Accrual',
        'creditor_transactions': 'Creditor',
    }
    total_records = 0
    station_count = 0
    top_stations = []
    for table, label in all_tables.items():
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                total_records += count
                station_count += 1
                top_stations.append({'label': label, 'count': count})
        except Exception:
            pass
    top_stations.sort(key=lambda x: -x['count'])
    top_stations = top_stations[:6]

    task_total = ProjectTask.objects.count()
    task_done = ProjectTask.objects.filter(status='done').count()
    task_in_progress = ProjectTask.objects.filter(status='in_progress').count()
    task_todo = ProjectTask.objects.filter(status='todo').count()

    health_data = {}
    try:
        health_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sync_health.json')
        with open(health_path) as f:
            health_data = json.load(f)
    except Exception:
        pass
    synced_count = sum(1 for v in health_data.values() if v.get('status') == 'success')

    return JsonResponse({
        'total_records': total_records,
        'station_count': station_count,
        'top_stations': top_stations,
        'task_total': task_total,
        'task_done': task_done,
        'task_in_progress': task_in_progress,
        'task_todo': task_todo,
        'synced_count': synced_count,
        'health_total': len(health_data),
    })


def api_data_analysis_stations(request):
    """JSON list of every station automation (name, description, records, sync status)."""
    err = _require_module(request, 'data')
    if err:
        return err

    special = {
        'turnover': ('Turnover', 'Turnover data synced from OneDrive to PostgreSQL for Power BI.'),
        'creditor': ('Creditor Report', 'Creditor payables by group and branch for Power BI.'),
        'condor_dor': ('Condor+DOR PNL', 'Condor & DOR P&L across CON, FEA, TRX, BRK departments.'),
        'bravo_tran': ('TFS Weekly Data', 'Weekly revenue, fleet utilization & YoY performance for Power BI.'),
        'wip_accrual': ('WIP & Accrual Report', 'WIP and Accrual data synced from OneDrive for Power BI.'),
        'import_ops': ('Import Operations', 'Import Operational Report data synced from OneDrive for Power BI.'),
    }

    stations, healthy, stale, error = _get_station_statuses()
    out = []
    for s in stations:
        code_lower = s.get('code_lower', '')
        if code_lower in special:
            name, desc = special[code_lower]
        else:
            name = f"{s['code']} Financial Analysis"
            desc = f"{s['code']} Budget vs Actual P&L for Power BI."
        out.append({
            'key': code_lower,
            'code': s['code'],
            'name': name,
            'description': desc,
            'records': s.get('records'),
            'last_sync': s.get('last_sync'),
            'time_ago': s.get('time_ago'),
            'status': s.get('status'),
        })

    # The Pricing Report is not a OneDrive station - it is a workbook somebody
    # downloads - but it is the same kind of thing to the reader: a source with
    # a row count and a last-loaded time. So it is listed alongside them, with
    # its own status worked out from the load rather than the health file.
    pricing = _pricing_source_card()
    out.append(pricing)
    if pricing['status'] == 'healthy':
        healthy += 1
    elif pricing['status'] == 'stale':
        stale += 1

    return JsonResponse({
        'stations': out,
        'healthy': healthy,
        'stale': stale,
        'error': error,
        'total': len(out),
    })


def _pricing_source_card():
    """The Pricing Report as one of the Data Analysis source cards."""
    from .models import PricingImport

    imp = PricingImport.objects.filter(is_active=True).first()
    if not imp:
        return {
            'key': 'pricing', 'code': 'PRICING', 'name': 'Pricing Report',
            'description': 'CargoWise pricing quotes with the turnover '
                           'analysis appended. No workbook loaded yet.',
            'records': 0, 'last_sync': None, 'time_ago': 'Not yet loaded',
            'status': 'unknown',
        }

    age = django_timezone.now() - imp.loaded_at
    days = age.days
    # The workbook is a monthly-ish export, not a nightly feed, so it only
    # counts as stale after a month rather than the stations' six hours.
    if days >= 30:
        status, ago = 'stale', f'{days}d ago'
    elif days >= 1:
        status, ago = 'healthy', f'{days}d ago'
    else:
        hours = age.seconds // 3600
        status = 'healthy'
        ago = f'{hours}h ago' if hours else 'Just now'
    return {
        'key': 'pricing', 'code': 'PRICING', 'name': 'Pricing Report',
        'description': f'{imp.quote_rows:,} pricing quotes with '
                       f'{imp.turnover_rows:,} turnover rows appended, '
                       f'from {imp.filename}.',
        'records': imp.total_rows,
        'last_sync': imp.loaded_at.isoformat(),
        'time_ago': ago,
        'status': status,
    }


# Maps a station key to the existing per-station sync view (report sending excluded).
STATION_SYNC_VIEWS = {
    'turnover': 'sync_data', 'ppg': 'sync_ppg', 'dor': 'sync_dor', 'con': 'sync_con',
    'atl': 'sync_atl', 'hnl': 'sync_hnl', 'ccc': 'sync_ccc', 'ccd': 'sync_ccd',
    'fax': 'sync_fax', 'hou': 'sync_hou', 'ics': 'sync_ics', 'imp': 'sync_imp',
    'jfk': 'sync_jfk', 'lax': 'sync_lax', 'lcl': 'sync_lcl', 'ord': 'sync_ord',
    'dfw': 'sync_dfw', 'condor_dor': 'sync_condor_dor', 'bravo_tran': 'sync_tfs',
    'import_ops': 'sync_import_ops', 'wip_accrual': 'sync_wip_accrual',
    'pricing': 'sync_pricing',
}


@csrf_exempt
@require_http_methods(["POST"])
def api_station_sync(request):
    """Trigger a station's existing sync job (reuses the per-station sync views)."""
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = {}
    station = (data.get('station') or '').strip().lower()

    fn_name = STATION_SYNC_VIEWS.get(station)
    if not fn_name:
        return JsonResponse({'ok': False, 'detail': 'This station syncs automatically — no manual trigger.'}, status=200)

    fn = globals().get(fn_name)
    if not callable(fn):
        return JsonResponse({'ok': False, 'detail': 'Sync unavailable.'}, status=500)

    # The per-station views require POST and return a JSON status. Calling directly
    # reuses their exact logic (starts a background thread, or reports "not connected").
    try:
        return fn(request)
    except Exception as e:
        msg = str(e)
        if 'Extra data' in msg or 'JSON' in msg.upper() or 'token' in msg.lower():
            msg = 'OneDrive not connected in this environment'
        return JsonResponse({'ok': False, 'detail': msg}, status=200)


@csrf_exempt
@require_http_methods(["POST"])
def sync_pricing(request):
    """Re-read the newest pricing workbook and make it the report's source.

    Unlike the OneDrive stations there is no API to pull from: the pricing
    export is a file somebody downloads. So the sync looks for the most recent
    workbook with "pricing" in its name across the folders it could plausibly
    be in, and loads that. If it cannot find one it says where it looked
    instead of failing quietly - the fix is to drop the file in one of them.
    """
    import logging

    from . import pricing_report

    log = logging.getLogger(__name__)
    path, searched = _newest_pricing_workbook()
    if not path:
        return JsonResponse({
            'status': 'error',
            'message': 'No pricing workbook found. Looked in: '
                       + '; '.join(searched),
        })

    def run_sync():
        try:
            imp = pricing_report.load(path)
            log.info('[pricing] synced %s: %s + %s rows', imp.filename,
                     imp.quote_rows, imp.turnover_rows)
        except Exception:
            log.exception('[pricing] sync failed for %s', path)

    threading.Thread(target=run_sync, daemon=True).start()
    return JsonResponse({
        'status': 'started',
        'message': f'Reading {os.path.basename(path)} - a full workbook takes '
                   'about a minute.',
    })


def _newest_pricing_workbook():
    """The most recently modified pricing workbook, and where we looked.

    Ordered by how canonical the location is, but the newest file wins across
    all of them - somebody who just downloaded a fresh export should not have
    to move it first.
    """
    candidates = []
    roots = [getattr(django_settings, 'PRICING_SOURCE_DIR', None),
             os.path.join(os.path.expanduser('~'), 'Downloads'),
             os.path.join(os.path.expanduser('~'), 'OneDrive', 'AWA Data Analysis',
                          'Pricing Report'),
             '/opt/awa-data-services/pricing']
    searched = []
    for root in roots:
        if not root:
            continue
        searched.append(root)
        if not os.path.isdir(root):
            continue
        try:
            for name in os.listdir(root):
                if (name.lower().endswith(('.xlsx', '.xlsm'))
                        and 'pricing' in name.lower()
                        and not name.startswith('~$')):
                    full = os.path.join(root, name)
                    candidates.append((os.path.getmtime(full), full))
        except OSError:
            continue
    if not candidates:
        return None, searched
    return max(candidates)[1], searched


@login_required
def home(request):
    """Dashboard home page"""
    # Aggregate total records across all station tables
    all_tables = {
        'turnover_data': 'Turnover', 'ppg_pnl': 'PPG', 'dor_pnl': 'DOR',
        'con_pnl': 'CON', 'atl_pnl': 'ATL', 'ccc_pnl': 'CCC',
        'ccd_pnl': 'CCD', 'fax_pnl': 'FAX', 'hnl_pnl': 'HNL',
        'hou_pnl': 'HOU', 'ics_pnl': 'ICS', 'imp_pnl': 'IMP',
        'jfk_pnl': 'JFK', 'lax_pnl': 'LAX', 'lcl_pnl': 'LCL',
        'ord_pnl': 'ORD', 'dfw_pnl': 'DFW', 'condor_dor_pnl': 'Condor+DOR',
        'import_ops': 'Import Ops', 'wip_accrual': 'WIP & Accrual',
        'creditor_transactions': 'Creditor',
    }
    total_records = 0
    station_count = 0
    top_stations = []
    for table, label in all_tables.items():
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                count = cursor.fetchone()[0]
                total_records += count
                station_count += 1
                top_stations.append((label, count))
        except:
            pass

    top_stations.sort(key=lambda x: -x[1])
    top_stations = top_stations[:6]

    # Planner task counts
    task_total = ProjectTask.objects.count()
    task_done = ProjectTask.objects.filter(status='done').count()
    task_in_progress = ProjectTask.objects.filter(status='in_progress').count()
    task_todo = ProjectTask.objects.filter(status='todo').count()
    projects = ProjectTask.objects.values_list('project_name', flat=True).distinct()
    project_count = len([p for p in projects if p])

    # Sync health
    health_data = {}
    try:
        import json as _json
        health_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'sync_health.json')
        with open(health_path) as f:
            health_data = _json.load(f)
    except:
        pass
    synced_count = sum(1 for v in health_data.values() if v.get('status') == 'success')

    context = {
        'total_records': total_records,
        'station_count': station_count,
        'top_stations': top_stations,
        'task_total': task_total,
        'task_done': task_done,
        'task_in_progress': task_in_progress,
        'task_todo': task_todo,
        'project_count': project_count,
        'synced_count': synced_count,
        'health_total': len(health_data),
    }
    return render(request, 'home.html', context)


@login_required
@page_access('data_analysis')
def data_analysis(request):
    """Data Analysis page with all stations"""
    try:
        total_rows = TurnoverData.objects.count()
        branch_count = TurnoverData.objects.values('branch').distinct().count()
    except (OperationalError, ProgrammingError):
        total_rows = 0
        branch_count = 0

    # PNL station stats
    station_tables = {
        'turnover': 'turnover_data',
        'ppg': 'ppg_pnl', 'dor': 'dor_pnl', 'con': 'con_pnl',
        'atl': 'atl_pnl', 'ccc': 'ccc_pnl', 'ccd': 'ccd_pnl',
        'fax': 'fax_pnl', 'hnl': 'hnl_pnl', 'hou': 'hou_pnl',
        'ics': 'ics_pnl', 'imp': 'imp_pnl', 'jfk': 'jfk_pnl',
        'lax': 'lax_pnl', 'lcl': 'lcl_pnl', 'ord': 'ord_pnl',
        'dfw': 'dfw_pnl', 'bravo_tran': 'bravo_tran',
        'condor_dor': 'condor_dor_pnl',
        'import_ops': 'import_ops', 'wip_accrual': 'wip_accrual',
        'creditor': 'creditor_transactions',
        'tfs': 'tfs_weekly',
        'updown_trader_cs': 'customer_spend',
        'updown_trader_cso': 'customer_spend_operational',
    }
    station_rows = {}
    for key, table in station_tables.items():
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"SELECT COUNT(*) FROM {table}")
                station_rows[f'{key}_rows'] = cursor.fetchone()[0]
        except:
            station_rows[f'{key}_rows'] = 0

    # Creditor groups
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(DISTINCT creditor_group) FROM creditor_transactions")
            creditor_groups = cursor.fetchone()[0]
    except:
        creditor_groups = 0

    # Condor depts
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(DISTINCT department) FROM condor_dor_pnl")
            condor_depts = cursor.fetchone()[0]
    except:
        condor_depts = 0

    # Up-Down Trader debtors
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(DISTINCT debtor) FROM customer_spend")
            updown_debtors = cursor.fetchone()[0]
    except:
        updown_debtors = 0

    # Load last sync times
    sync_files = {
        'turnover': 'last_sync.json',
        'atl': 'atl_last_sync.json', 'ccc': 'ccc_last_sync.json',
        'ccd': 'ccd_last_sync.json', 'con': 'con_last_sync.json',
        'dor': 'dor_last_sync.json', 'fax': 'fax_last_sync.json',
        'hnl': 'hnl_last_sync.json', 'hou': 'hou_last_sync.json',
        'ics': 'ics_last_sync.json', 'imp': 'imp_last_sync.json',
        'jfk': 'jfk_last_sync.json', 'lax': 'lax_last_sync.json',
        'lcl': 'lcl_last_sync.json', 'ord': 'ord_last_sync.json',
        'dfw': 'dfw_last_sync.json', 'ppg': 'ppg_last_sync.json',
        'condor_dor': 'condor_dor_last_sync.json',
        'import_ops': 'import_ops_last_sync.json',
        'wip_accrual': 'wip_accrual_last_sync.json',
        'tfs': 'tfs_last_sync.json',
        'updown_trader': 'updown_trader_last_sync.json',
    }
    last_syncs = {}
    base_dir = os.path.dirname(os.path.dirname(__file__))
    for key, fname in sync_files.items():
        try:
            with open(os.path.join(base_dir, fname)) as f:
                data = json.load(f)
                ts = data.get('last_sync', '')
                if ts:
                    from datetime import datetime as _dt
                    dt = _dt.fromisoformat(ts)
                    last_syncs[f'{key}_last_sync'] = dt.strftime('%d %b %Y, %H:%M')
        except:
            pass

    context = {
        'branch_count': branch_count,
        'creditor_groups': creditor_groups,
        'condor_depts': condor_depts,
        'updown_debtors': updown_debtors,
        **station_rows,
        **last_syncs,
    }
    return render(request, 'data_analysis.html', context)


@login_required
def turnover(request):
    """Turnover Automation project page"""
    try:
        total_records = TurnoverData.objects.count()
        total_value = TurnoverData.objects.aggregate(total=Sum('value'))['total'] or 0
        branches = list(TurnoverData.objects.values_list('branch', flat=True).distinct())
        year_count = TurnoverData.objects.annotate(
            year=ExtractYear('date')
        ).values('year').distinct().count()
    except (OperationalError, ProgrammingError):
        total_records = 0
        total_value = 0
        branches = []
        year_count = 0

    context = {
        'total_records': total_records,
        'total_value': total_value,
        'branches': branches,
        'year_count': year_count,
        'last_sync': get_last_sync(),
    }
    return render(request, 'turnover.html', context)


@login_required
def pnl(request):
    """PNL Automation project page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM pnl_data")
            total_records = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT division) FROM pnl_data")
            division_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT date) FROM pnl_data")
            period_count = cursor.fetchone()[0]
            cursor.execute("SELECT DISTINCT division FROM pnl_data ORDER BY division")
            divisions = [row[0] for row in cursor.fetchall()]
    except:
        total_records = 0
        division_count = 0
        period_count = 0
        divisions = []

    context = {
        'total_records': total_records,
        'division_count': division_count,
        'period_count': period_count,
        'divisions': divisions,
    }
    return render(request, 'pnl.html', context)


@login_required
def ppg(request):
    """PPG Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM ppg_pnl")
            total_records = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM ppg_pnl WHERE budget_actual = 'Budget'")
            budget_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM ppg_pnl WHERE budget_actual = 'Actual'")
            actual_count = cursor.fetchone()[0]
            cursor.execute("SELECT MIN(date), MAX(date) FROM ppg_pnl")
            min_date, max_date = cursor.fetchone()
    except:
        total_records = 0
        budget_count = 0
        actual_count = 0
        min_date = None
        max_date = None

    context = {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'min_date': min_date,
        'max_date': max_date,
        'last_sync': onedrive_sync.get_ppg_last_sync(),
    }
    return render(request, 'ppg.html', context)


@login_required
def sync_data(request):
    if request.method == 'POST':
        # Check if OneDrive is authenticated
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_progress('starting', 'Starting OneDrive sync...', 0, 100)

        def run_sync():
            try:
                update_progress('syncing', 'Checking OneDrive for new files...', 10, 100)
                count = onedrive_sync.sync_turnover_data()
                if count > 0:
                    update_progress('complete', f'Synced {count} new records', 100, 100)
                else:
                    update_progress('complete', 'No new files to sync — all up to date', 100, 100)
            except Exception as e:
                update_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started'})
    return redirect('turnover')


@login_required
def sync_progress(request):
    return JsonResponse(get_progress())


def onedrive_auth(request):
    """Redirect to OneDrive authorization"""
    auth_url = onedrive_sync.get_auth_url()
    return redirect(auth_url)


@login_required
def onedrive_callback(request):
    """Handle OneDrive OAuth callback"""
    code = request.GET.get('code')
    if code:
        token = onedrive_sync.acquire_token_by_auth_code(code)
        if token:
            messages.success(request, 'OneDrive connected successfully!')
        else:
            messages.error(request, 'Failed to connect to OneDrive')
    return redirect('turnover')


@login_required
def onedrive_check(request):
    """Check if OneDrive is authenticated"""
    token = onedrive_sync.get_access_token()
    return JsonResponse({'authenticated': token is not None})


# PPG sync progress storage
ppg_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_ppg_progress(status, message, current=0, total=0):
    global ppg_sync_progress
    ppg_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_ppg(request):
    """Sync PPG data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_ppg_progress('starting', 'Starting PPG sync...', 0, 100)

        def run_sync():
            try:
                update_ppg_progress('syncing', 'Checking OneDrive for PPG files...', 10, 100)
                count = onedrive_sync.sync_ppg_data()
                if count > 0:
                    update_ppg_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_ppg_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_ppg_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started'})
    return redirect('ppg')


@login_required
def sync_ppg_progress(request):
    """Get PPG sync progress"""
    return JsonResponse(ppg_sync_progress)


# DOR views and sync
@login_required
def dor(request):
    """DOR Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM dor_pnl")
            total_records = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM dor_pnl WHERE budget_actual = 'Budget'")
            budget_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM dor_pnl WHERE budget_actual = 'Actual'")
            actual_count = cursor.fetchone()[0]
            cursor.execute("SELECT MIN(date), MAX(date) FROM dor_pnl")
            min_date, max_date = cursor.fetchone()
    except:
        total_records = 0
        budget_count = 0
        actual_count = 0
        min_date = None
        max_date = None

    context = {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'min_date': min_date,
        'max_date': max_date,
        'last_sync': onedrive_sync.get_dor_last_sync(),
    }
    return render(request, 'dor.html', context)


# DOR sync progress storage
dor_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_dor_progress(status, message, current=0, total=0):
    global dor_sync_progress
    dor_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_dor(request):
    """Sync DOR data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_dor_progress('starting', 'Starting DOR sync...', 0, 100)

        def run_sync():
            try:
                update_dor_progress('syncing', 'Checking OneDrive for DOR files...', 10, 100)
                count = onedrive_sync.sync_dor_data()
                if count > 0:
                    update_dor_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_dor_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_dor_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started'})
    return redirect('dor')


@login_required
def sync_dor_progress(request):
    """Get DOR sync progress"""
    return JsonResponse(dor_sync_progress)


# CON Views
con_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}
atl_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_con_progress(status, message, current=0, total=0):
    global con_sync_progress
    con_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


def update_atl_progress(status, message, current=0, total=0):
    global atl_sync_progress
    atl_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_con(request):
    """Sync CON data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_con_progress('starting', 'Starting CON sync...', 0, 100)

        def run_sync():
            try:
                update_con_progress('syncing', 'Checking OneDrive for CON files...', 10, 100)
                count = onedrive_sync.sync_con_data()
                if count > 0:
                    update_con_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_con_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_con_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started'})
    return redirect('con')


@login_required
def sync_con_progress(request):
    """Get CON sync progress"""
    return JsonResponse(con_sync_progress)


@login_required
def con(request):
    """CON Financial Analysis page"""
    with connection.cursor() as cursor:
        # Get total records
        cursor.execute("SELECT COUNT(*) FROM con_pnl")
        total_records = cursor.fetchone()[0] or 0

        # Get distinct months
        cursor.execute("SELECT COUNT(DISTINCT date) FROM con_pnl")
        month_count = cursor.fetchone()[0] or 0

        # Get distinct accounts
        cursor.execute("SELECT COUNT(DISTINCT account_name) FROM con_pnl")
        account_count = cursor.fetchone()[0] or 0

    last_sync = onedrive_sync.get_con_last_sync()

    return render(request, 'con.html', {
        'total_records': total_records,
        'month_count': month_count,
        'account_count': account_count,
        'last_sync': last_sync
    })

# ATL view
@login_required
def atl(request):
    """ATL Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM atl_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM atl_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM atl_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM atl_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0

    last_sync = onedrive_sync.get_atl_last_sync()

    return render(request, 'atl.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


@login_required
def sync_atl(request):
    """Sync ATL data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_atl_progress('starting', 'Starting ATL sync...', 0, 100)

        def run_sync():
            try:
                update_atl_progress('syncing', 'Checking OneDrive for ATL files...', 10, 100)
                count = onedrive_sync.sync_atl_data()
                if count > 0:
                    update_atl_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_atl_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_atl_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_atl_progress(request):
    """Get ATL sync progress"""
    return JsonResponse(atl_sync_progress)


# HNL views
@login_required
def hnl(request):
    """HNL Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM hnl_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM hnl_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM hnl_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM hnl_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0

    last_sync = onedrive_sync.get_hnl_last_sync()

    return render(request, 'hnl.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# HNL sync progress tracking
hnl_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_hnl_progress(status, message, current=0, total=0):
    global hnl_sync_progress
    hnl_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_hnl(request):
    """Sync HNL data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_hnl_progress('starting', 'Starting HNL sync...', 0, 100)

        def run_sync():
            try:
                update_hnl_progress('syncing', 'Checking OneDrive for HNL files...', 10, 100)
                count = onedrive_sync.sync_hnl_data()
                if count > 0:
                    update_hnl_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_hnl_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_hnl_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()
        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request'})


def sync_hnl_progress(request):
    """Get HNL sync progress"""
    return JsonResponse(hnl_sync_progress)


# CCC views
@login_required
def ccc(request):
    """CCC Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM ccc_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM ccc_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM ccc_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM ccc_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0

    last_sync = onedrive_sync.get_ccc_last_sync()

    return render(request, 'ccc.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# CCC sync progress tracking
ccc_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_ccc_progress(status, message, current=0, total=0):
    global ccc_sync_progress
    ccc_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_ccc(request):
    """Sync CCC data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_ccc_progress('starting', 'Starting CCC sync...', 0, 100)

        def run_sync():
            try:
                update_ccc_progress('syncing', 'Checking OneDrive for CCC files...', 10, 100)
                count = onedrive_sync.sync_ccc_data()
                if count > 0:
                    update_ccc_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_ccc_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_ccc_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_ccc_progress(request):
    """Get CCC sync progress"""
    return JsonResponse(ccc_sync_progress)


# CCD view
@login_required
def bravo_tran(request):
    """Bravo Trans / AWA Payables Waiting — table holds only the latest report."""
    total_records = vendor_count = branch_count = open_invoices = 0
    latest_report = None
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM bravo_tran")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT vendor) FROM bravo_tran")
            vendor_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT job_branches) FROM bravo_tran")
            branch_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM bravo_tran WHERE invoice_total IS NOT NULL AND invoice_total > 0")
            open_invoices = cursor.fetchone()[0] or 0
            cursor.execute("SELECT MAX(report_date) FROM bravo_tran")
            latest_report = cursor.fetchone()[0]
    except Exception:
        pass

    # Fetch email→branch allocations from useu_contacts (only rows with non-empty email & branch)
    allocations = list(
        USEUContact.objects.exclude(email='').exclude(branch='')
        .values_list('id', 'email', 'branch', 'contact_name')
        .order_by('branch', 'email')
    )
    allocated_emails = {a[1].lower() for a in allocations}

    # Find emails in bravo_tran that have no allocation yet
    unallocated = []
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT DISTINCT request_sent_to FROM bravo_tran "
                "WHERE request_sent_to IS NOT NULL AND request_sent_to <> '' "
                "ORDER BY request_sent_to"
            )
            for row in cursor.fetchall():
                raw = row[0].strip()
                # Some rows have comma-separated emails — split them
                for part in raw.split(','):
                    email = part.strip().lower()
                    if email and email not in allocated_emails:
                        unallocated.append(email)
                        allocated_emails.add(email)  # deduplicate
    except Exception:
        pass

    return render(request, 'bravo_tran.html', {
        'total_records': total_records,
        'vendor_count': vendor_count,
        'branch_count': branch_count,
        'open_invoices': open_invoices,
        'latest_report': latest_report,
        'allocations_json': json.dumps([list(a) for a in allocations]),
        'unallocated_json': json.dumps(sorted(unallocated)),
    })


@login_required
@require_http_methods(["POST"])
def bravo_tran_allocate(request):
    """Add or update an email→branch allocation in useu_contacts."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    email = (data.get('email') or '').strip().lower()
    branch = (data.get('branch') or '').strip()
    contact_name = (data.get('contact_name') or '').strip()
    if not email or not branch:
        return JsonResponse({'ok': False, 'error': 'Email and branch are required'}, status=400)
    contact_id = data.get('id')
    if contact_id:
        try:
            c = USEUContact.objects.get(id=contact_id)
            c.email = email
            c.branch = branch
            c.contact_name = contact_name
            c.save(update_fields=['email', 'branch', 'contact_name'])
            return JsonResponse({'ok': True, 'id': c.id})
        except USEUContact.DoesNotExist:
            return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)
    else:
        c = USEUContact.objects.create(
            email=email, branch=branch, contact_name=contact_name,
            org_name='', default='', attach='', phone='',
            touchpoint_1='', tp1_sent_on='', touchpoint_2='',
            last_touch='', status='Active', tp1_processing_id='',
        )
        return JsonResponse({'ok': True, 'id': c.id})


@login_required
@require_http_methods(["POST"])
def bravo_tran_deallocate(request):
    """Remove an email→branch allocation (clears the branch field)."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)
    contact_id = data.get('id')
    if not contact_id:
        return JsonResponse({'ok': False, 'error': 'ID required'}, status=400)
    try:
        c = USEUContact.objects.get(id=contact_id)
        c.branch = ''
        c.save(update_fields=['branch'])
        return JsonResponse({'ok': True})
    except USEUContact.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)


@login_required
def ccd(request):
    """CCD Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM ccd_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM ccd_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM ccd_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM ccd_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0
    
    last_sync = onedrive_sync.get_ccd_last_sync()

    return render(request, 'ccd.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# FAX view
@login_required
def fax(request):
    """FAX Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM fax_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM fax_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM fax_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM fax_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0
    
    last_sync = onedrive_sync.get_fax_last_sync()

    return render(request, 'fax.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# HEC view
@login_required
def hec(request):
    """HEC Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM pnl_data WHERE division = 'HEC'")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM pnl_data WHERE division = 'HEC' AND account_name LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM pnl_data WHERE division = 'HEC' AND account_name LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM pnl_data WHERE division = 'HEC'")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0
    
    return render(request, 'hec.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count
    })


# HOU view
@login_required
def hou(request):
    """HOU Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM hou_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM hou_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM hou_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM hou_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0
    
    last_sync = onedrive_sync.get_hou_last_sync()

    return render(request, 'hou.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# ICS view
@login_required
def ics(request):
    """ICS Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM ics_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM ics_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM ics_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM ics_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0
    
    last_sync = onedrive_sync.get_ics_last_sync()

    return render(request, 'ics.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# IMP view
@login_required
def imp(request):
    """IMP Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM imp_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM imp_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM imp_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM imp_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0
    
    last_sync = onedrive_sync.get_imp_last_sync()

    return render(request, 'imp.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# JFK view
@login_required
def jfk(request):
    """JFK Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM jfk_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM jfk_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM jfk_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM jfk_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0
    
    last_sync = onedrive_sync.get_jfk_last_sync()

    return render(request, 'jfk.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# LAX view
@login_required
def lax(request):
    """LAX Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM lax_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM lax_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM lax_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM lax_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0
    
    last_sync = onedrive_sync.get_lax_last_sync()

    return render(request, 'lax.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# LCL view
@login_required
def lcl(request):
    """LCL Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM lcl_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM lcl_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM lcl_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM lcl_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0
    
    last_sync = onedrive_sync.get_lcl_last_sync()

    return render(request, 'lcl.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# ORD view
@login_required
def ord(request):
    """ORD Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM ord_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM ord_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM ord_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM ord_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0
    
    last_sync = onedrive_sync.get_ord_last_sync()

    return render(request, 'ord.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# CCD sync progress tracking
ccd_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_ccd_progress(status, message, current=0, total=0):
    global ccd_sync_progress
    ccd_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_ccd(request):
    """Sync CCD data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_ccd_progress('starting', 'Starting CCD sync...', 0, 100)

        def run_sync():
            try:
                update_ccd_progress('syncing', 'Checking OneDrive for CCD files...', 10, 100)
                count = onedrive_sync.sync_ccd_data()
                if count > 0:
                    update_ccd_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_ccd_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_ccd_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_ccd_progress(request):
    """Get CCD sync progress"""
    return JsonResponse(ccd_sync_progress)


# FAX sync progress tracking
fax_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_fax_progress(status, message, current=0, total=0):
    global fax_sync_progress
    fax_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_fax(request):
    """Sync FAX data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_fax_progress('starting', 'Starting FAX sync...', 0, 100)

        def run_sync():
            try:
                update_fax_progress('syncing', 'Checking OneDrive for FAX files...', 10, 100)
                count = onedrive_sync.sync_fax_data()
                if count > 0:
                    update_fax_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_fax_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_fax_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_fax_progress(request):
    """Get FAX sync progress"""
    return JsonResponse(fax_sync_progress)


# HOU sync progress tracking
hou_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_hou_progress(status, message, current=0, total=0):
    global hou_sync_progress
    hou_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_hou(request):
    """Sync HOU data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_hou_progress('starting', 'Starting HOU sync...', 0, 100)

        def run_sync():
            try:
                update_hou_progress('syncing', 'Checking OneDrive for HOU files...', 10, 100)
                count = onedrive_sync.sync_hou_data()
                if count > 0:
                    update_hou_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_hou_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_hou_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_hou_progress(request):
    """Get HOU sync progress"""
    return JsonResponse(hou_sync_progress)


# ICS sync progress tracking
ics_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_ics_progress(status, message, current=0, total=0):
    global ics_sync_progress
    ics_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_ics(request):
    """Sync ICS data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_ics_progress('starting', 'Starting ICS sync...', 0, 100)

        def run_sync():
            try:
                update_ics_progress('syncing', 'Checking OneDrive for ICS files...', 10, 100)
                count = onedrive_sync.sync_ics_data()
                if count > 0:
                    update_ics_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_ics_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_ics_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_ics_progress(request):
    """Get ICS sync progress"""
    return JsonResponse(ics_sync_progress)


# IMP sync progress tracking
imp_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_imp_progress(status, message, current=0, total=0):
    global imp_sync_progress
    imp_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_imp(request):
    """Sync IMP data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_imp_progress('starting', 'Starting IMP sync...', 0, 100)

        def run_sync():
            try:
                update_imp_progress('syncing', 'Checking OneDrive for IMP files...', 10, 100)
                count = onedrive_sync.sync_imp_data()
                if count > 0:
                    update_imp_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_imp_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_imp_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_imp_progress(request):
    """Get IMP sync progress"""
    return JsonResponse(imp_sync_progress)


# JFK sync progress tracking
jfk_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_jfk_progress(status, message, current=0, total=0):
    global jfk_sync_progress
    jfk_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_jfk(request):
    """Sync JFK data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_jfk_progress('starting', 'Starting JFK sync...', 0, 100)

        def run_sync():
            try:
                update_jfk_progress('syncing', 'Checking OneDrive for JFK files...', 10, 100)
                count = onedrive_sync.sync_jfk_data()
                if count > 0:
                    update_jfk_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_jfk_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_jfk_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_jfk_progress(request):
    """Get JFK sync progress"""
    return JsonResponse(jfk_sync_progress)


# LAX sync progress tracking
lax_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_lax_progress(status, message, current=0, total=0):
    global lax_sync_progress
    lax_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_lax(request):
    """Sync LAX data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_lax_progress('starting', 'Starting LAX sync...', 0, 100)

        def run_sync():
            try:
                update_lax_progress('syncing', 'Checking OneDrive for LAX files...', 10, 100)
                count = onedrive_sync.sync_lax_data()
                if count > 0:
                    update_lax_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_lax_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_lax_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_lax_progress(request):
    """Get LAX sync progress"""
    return JsonResponse(lax_sync_progress)


# LCL sync progress tracking
lcl_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_lcl_progress(status, message, current=0, total=0):
    global lcl_sync_progress
    lcl_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_lcl(request):
    """Sync LCL data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_lcl_progress('starting', 'Starting LCL sync...', 0, 100)

        def run_sync():
            try:
                update_lcl_progress('syncing', 'Checking OneDrive for LCL files...', 10, 100)
                count = onedrive_sync.sync_lcl_data()
                if count > 0:
                    update_lcl_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_lcl_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_lcl_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_lcl_progress(request):
    """Get LCL sync progress"""
    return JsonResponse(lcl_sync_progress)


# ORD sync progress tracking
ord_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_ord_progress(status, message, current=0, total=0):
    global ord_sync_progress
    ord_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_ord(request):
    """Sync ORD data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_ord_progress('starting', 'Starting ORD sync...', 0, 100)

        def run_sync():
            try:
                update_ord_progress('syncing', 'Checking OneDrive for ORD files...', 10, 100)
                count = onedrive_sync.sync_ord_data()
                if count > 0:
                    update_ord_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_ord_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_ord_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_ord_progress(request):
    """Get ORD sync progress"""
    return JsonResponse(ord_sync_progress)


@login_required
def dfw(request):
    """DFW Financial Analysis page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM dfw_pnl")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM dfw_pnl WHERE budget_actual LIKE '%Budget%'")
            budget_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM dfw_pnl WHERE budget_actual LIKE '%Actual%'")
            actual_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM dfw_pnl")
            account_count = cursor.fetchone()[0] or 0
    except:
        total_records = budget_count = actual_count = account_count = 0

    last_sync = onedrive_sync.get_dfw_last_sync()

    return render(request, 'dfw.html', {
        'total_records': total_records,
        'budget_count': budget_count,
        'actual_count': actual_count,
        'account_count': account_count,
        'last_sync': last_sync
    })


# DFW sync progress tracking
dfw_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_dfw_progress(status, message, current=0, total=0):
    global dfw_sync_progress
    dfw_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_dfw(request):
    """Sync DFW data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_dfw_progress('starting', 'Starting DFW sync...', 0, 100)

        def run_sync():
            try:
                update_dfw_progress('syncing', 'Checking OneDrive for DFW files...', 10, 100)
                count = onedrive_sync.sync_dfw_data()
                if count > 0:
                    update_dfw_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_dfw_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_dfw_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_dfw_progress(request):
    """Get DFW sync progress"""
    return JsonResponse(dfw_sync_progress)


@login_required
def creditor(request):
    """Creditor Transaction Report page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM creditor_transactions")
            total_records = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT creditor) FROM creditor_transactions")
            creditor_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT creditor_group) FROM creditor_transactions")
            group_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT branch) FROM creditor_transactions WHERE branch != ''")
            branch_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT period) FROM creditor_transactions")
            period_count = cursor.fetchone()[0]
    except:
        total_records = 0
        creditor_count = 0
        group_count = 0
        branch_count = 0
        period_count = 0

    context = {
        'total_records': total_records,
        'creditor_count': creditor_count,
        'group_count': group_count,
        'branch_count': branch_count,
        'period_count': period_count,
    }
    return render(request, 'creditor.html', context)


@login_required
def condor_dor(request):
    """Condor+DOR PNL page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM condor_dor_pnl")
            total_records = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT department) FROM condor_dor_pnl")
            dept_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT branch) FROM condor_dor_pnl")
            branch_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT account_name) FROM condor_dor_pnl")
            account_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(DISTINCT date) FROM condor_dor_pnl")
            period_count = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM condor_dor_pnl WHERE budget_actual = 'Budget'")
            budget_rows = cursor.fetchone()[0]
            cursor.execute("SELECT COUNT(*) FROM condor_dor_pnl WHERE budget_actual = 'Actual'")
            actual_rows = cursor.fetchone()[0]
    except:
        total_records = 0
        dept_count = 0
        branch_count = 0
        account_count = 0
        period_count = 0
        budget_rows = 0
        actual_rows = 0

    context = {
        'total_records': total_records,
        'dept_count': dept_count,
        'branch_count': branch_count,
        'account_count': account_count,
        'period_count': period_count,
        'budget_rows': budget_rows,
        'actual_rows': actual_rows,
    }
    context['last_sync'] = onedrive_sync.get_condor_dor_last_sync()
    return render(request, 'condor_dor.html', context)


condor_dor_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_condor_dor_progress(status, message, current=0, total=0):
    global condor_dor_sync_progress
    condor_dor_sync_progress = {'status': status, 'message': message, 'current': current, 'total': total}


@login_required
def sync_condor_dor(request):
    """Manually sync Condor+DOR PNL data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_condor_dor_progress('starting', 'Starting Condor+DOR sync...', 0, 100)

        def run_sync():
            try:
                update_condor_dor_progress('syncing', 'Checking OneDrive for Condor+DOR files...', 10, 100)
                count = onedrive_sync.sync_condor_dor_data()
                if count > 0:
                    update_condor_dor_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_condor_dor_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_condor_dor_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()
        return JsonResponse({'status': 'started'})
    return redirect('condor_dor')


@login_required
def sync_condor_dor_progress(request):
    """Get Condor+DOR sync progress"""
    return JsonResponse(condor_dor_sync_progress)


# --- Sync Monitor ---

STATIONS = [
    'turnover', 'creditor', 'condor_dor', 'bravo_tran',
    'wip_accrual', 'import_ops',
    'atl', 'ccc', 'ccd', 'con', 'dfw', 'dor', 'fax',
    'hnl', 'hou', 'ics', 'imp', 'jfk', 'lax',
    'lcl', 'ord', 'ppg',
]

STATION_TABLES = {
    'turnover': 'turnover_data',
    'creditor': 'creditor_transactions',
    'condor_dor': 'condor_dor_pnl',
    'bravo_tran': 'bravo_tran',
    'wip_accrual': 'wip_accrual',
    'import_ops': 'import_ops',
    'atl': 'atl_pnl', 'ccc': 'ccc_pnl', 'ccd': 'ccd_pnl',
    'con': 'con_pnl', 'dor': 'dor_pnl', 'fax': 'fax_pnl',
    'hnl': 'hnl_pnl', 'hou': 'hou_pnl', 'ics': 'ics_pnl',
    'imp': 'imp_pnl', 'jfk': 'jfk_pnl', 'lax': 'lax_pnl',
    'lcl': 'lcl_pnl', 'ord': 'ord_pnl', 'dfw': 'dfw_pnl',
    'ppg': 'ppg_pnl',
}


def _get_station_statuses():
    """Build station status list for the monitor page."""
    now = datetime.now(ZoneInfo('Africa/Johannesburg'))
    stale_threshold = now - timedelta(hours=6)  # Email syncs run every 3h, stale after 6h

    # Load health data
    health_data = {}
    try:
        health_file = django_settings.SYNC_HEALTH_FILE
        if os.path.exists(health_file):
            with open(health_file, 'r') as f:
                health_data = json.load(f)
    except Exception:
        pass

    stations = []
    healthy_count = 0
    stale_count = 0
    error_count = 0

    for station in STATIONS:
        # Read last sync timestamp - prefer email_last.json, fall back to last_sync.json
        last_sync_dt = None
        last_sync_display = None
        email_info = None

        # Read health info up-front so we can use its last_check as a
        # candidate for "last sync time" alongside the state-file mtime.
        health = health_data.get(station, {})
        health_status = health.get('status', 'unknown')
        health_last_check_dt = None
        if health.get('last_check'):
            try:
                health_last_check_dt = datetime.fromisoformat(health['last_check'])
            except Exception:
                health_last_check_dt = None

        # Check email sync state first (the primary sync method)
        email_file = os.path.join(os.path.dirname(__file__), '..', f'{station}_email_last.json')
        email_state_dt = None
        if os.path.exists(email_file):
            try:
                with open(email_file, 'r') as f:
                    edata = json.load(f)
                if edata.get('received') or edata.get('message_ids') or edata.get('branches') or edata.get('groups') or edata.get('rows'):
                    mtime = os.path.getmtime(email_file)
                    email_state_dt = datetime.fromtimestamp(mtime, tz=ZoneInfo('Africa/Johannesburg'))
                    email_info = edata
            except Exception:
                pass

        # Fall back to old last_sync file
        legacy_sync_dt = None
        sync_file = getattr(django_settings, f'{station.upper()}_LAST_SYNC_FILE', None)
        if sync_file and os.path.exists(sync_file):
            try:
                with open(sync_file, 'r') as f:
                    data = json.load(f)
                if 'last_sync' in data:
                    legacy_sync_dt = datetime.fromisoformat(data['last_sync'])
            except Exception:
                pass

        # Pick the most recent timestamp across all three sources. A sync that
        # re-processed an already-seen email still bumps sync_health.last_check
        # even if the state file's mtime doesn't change — so using max(...)
        # means pressing "Sync All" reliably updates the monitor.
        candidates = [t for t in (email_state_dt, legacy_sync_dt, health_last_check_dt) if t is not None]
        if candidates:
            last_sync_dt = max(candidates)
            last_sync_display = {
                'time': last_sync_dt.strftime('%H:%M'),
                'date': last_sync_dt.strftime('%b %d, %Y'),
            }

        # Query actual record count from DB
        records = None
        table = STATION_TABLES.get(station)
        if table:
            try:
                with connection.cursor() as cursor:
                    cursor.execute(f"SELECT COUNT(*) FROM {table}")
                    records = cursor.fetchone()[0]
            except Exception:
                records = None

        # A recorded error only counts while it is still the latest thing that
        # happened. sync_health entries are never cleared, so without this an
        # error from months ago pins a station to "error" forever — even after a
        # sync has since succeeded and loaded new rows.
        health_error_is_current = health_status == 'error' and not (
            last_sync_dt is not None
            and health_last_check_dt is not None
            and health_last_check_dt < last_sync_dt
        )

        # Determine overall status — a later successful sync overrides a stale
        # health error, as does any email sync result.
        if health_error_is_current and email_info is None:
            status = 'error'
            error_count += 1
        elif last_sync_dt is None:
            status = 'unknown'
            stale_count += 1
        elif last_sync_dt < stale_threshold:
            status = 'stale'
            stale_count += 1
        else:
            status = 'healthy'
            healthy_count += 1

        # Build a meaningful message from available data
        if health_error_is_current and email_info is None:
            message = health.get('message', 'Sync error')
        elif email_info and email_info.get('rows'):
            message = f'{email_info["rows"]:,} rows from email'
        elif records is not None and records > 0:
            message = f'{records:,} records'
        elif email_info is not None:
            message = 'Email processed (idempotent)'
        else:
            message = 'Waiting for data'

        # Time ago string
        time_ago = None
        if last_sync_dt:
            delta = now - last_sync_dt
            minutes = int(delta.total_seconds() / 60)
            if minutes < 1:
                time_ago = 'Just now'
            elif minutes < 60:
                time_ago = f'{minutes}m ago'
            elif minutes < 1440:
                time_ago = f'{minutes // 60}h {minutes % 60}m ago'
            else:
                time_ago = f'{minutes // 1440}d ago'

        stations.append({
            'code': station.upper(),
            'code_lower': station,
            'last_sync': last_sync_display,
            'time_ago': time_ago,
            'status': status,
            'health_status': health_status,
            'message': message,
            'records': records,
        })

    return stations, healthy_count, stale_count, error_count


@login_required
def sync_monitor(request):
    """Sync Monitor page"""
    stations, healthy, stale, errors = _get_station_statuses()
    context = {
        'stations': stations,
        'healthy_count': healthy,
        'stale_count': stale,
        'error_count': errors,
        'total_stations': len(STATIONS),
    }
    return render(request, 'monitor.html', context)


@login_required
def sync_monitor_api(request):
    """JSON API for auto-refresh of monitor data"""
    stations, healthy, stale, errors = _get_station_statuses()
    return JsonResponse({
        'stations': stations,
        'healthy_count': healthy,
        'stale_count': stale,
        'error_count': errors,
    })


@login_required
def sync_all(request):
    """Trigger a manual sync of all stations via email inbox"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'POST required'}, status=405)

    _sync_all_state_file = os.path.join(os.path.dirname(__file__), '..', 'sync_all_state.json')

    def _write_state(data):
        try:
            with open(_sync_all_state_file, 'w') as f:
                json.dump(data, f)
        except Exception:
            pass

    def run_all():
        from .scheduler import (
            run_ppg_email_sync_job, run_ccc_email_sync_job, run_ccd_email_sync_job,
            run_hnl_email_sync_job, run_jfk_email_sync_job, run_lcl_email_sync_job,
            run_hou_email_sync_job, run_ics_email_sync_job, run_ord_email_sync_job,
            run_imp_email_sync_job, run_lax_email_sync_job, run_fax_email_sync_job,
            run_atl_email_sync_job, run_dfw_email_sync_job, run_con_email_sync_job,
            run_dor_email_sync_job, run_turnover_email_sync_job,
            run_wip_email_sync_job, run_import_ops_email_sync_job,
            run_creditor_email_sync_job, run_condor_dor_email_sync_job,
            run_bravo_tran_sync_job,
        )
        jobs = [
            ('PPG', run_ppg_email_sync_job), ('CCC', run_ccc_email_sync_job),
            ('CCD', run_ccd_email_sync_job), ('HNL', run_hnl_email_sync_job),
            ('JFK', run_jfk_email_sync_job), ('LCL', run_lcl_email_sync_job),
            ('HOU', run_hou_email_sync_job), ('ICS', run_ics_email_sync_job),
            ('ORD', run_ord_email_sync_job), ('IMP', run_imp_email_sync_job),
            ('LAX', run_lax_email_sync_job), ('FAX', run_fax_email_sync_job),
            ('ATL', run_atl_email_sync_job), ('DFW', run_dfw_email_sync_job),
            ('CON', run_con_email_sync_job), ('DOR', run_dor_email_sync_job),
            ('Turnover', run_turnover_email_sync_job),
            ('WIP & Accrual', run_wip_email_sync_job),
            ('Import Ops', run_import_ops_email_sync_job),
            ('Creditor', run_creditor_email_sync_job),
            ('Condor+DOR', run_condor_dor_email_sync_job),
            ('Bravo Trans', run_bravo_tran_sync_job),
        ]
        errors = 0
        for i, (name, fn) in enumerate(jobs):
            _write_state({'running': True, 'current': name, 'done': i, 'total': len(jobs), 'errors': errors})
            try:
                fn()
            except Exception as e:
                errors += 1
                print(f'[sync_all] {name} failed: {e}', flush=True)
        _write_state({'running': False, 'current': '', 'done': len(jobs), 'total': len(jobs), 'errors': errors})

    threading.Thread(target=run_all, daemon=True).start()
    return JsonResponse({'status': 'started'})


@login_required
def sync_all_status(request):
    """Return current sync-all progress."""
    state_file = os.path.join(os.path.dirname(__file__), '..', 'sync_all_state.json')
    try:
        with open(state_file) as f:
            return JsonResponse(json.load(f))
    except Exception:
        return JsonResponse({'running': False})


# ── Power BI Embed ────────────────────────────────────────────────────────────

@login_required
def get_powerbi_embed(request):
    """Return the saved Power BI embed URL for a given page."""
    from .models import PowerBIEmbed
    page_name = request.GET.get('page', '')
    try:
        obj = PowerBIEmbed.objects.get(page_name=page_name)
        return JsonResponse({'embed_url': obj.embed_url})
    except PowerBIEmbed.DoesNotExist:
        return JsonResponse({'embed_url': ''})


@login_required
def save_powerbi_embed(request):
    """Save or update the Power BI embed URL for a given page."""
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=405)
    from .models import PowerBIEmbed
    data = json.loads(request.body)
    page_name = data.get('page', '')
    embed_url = data.get('embed_url', '').strip()
    if not page_name:
        return JsonResponse({'status': 'error', 'message': 'page required'}, status=400)
    PowerBIEmbed.objects.update_or_create(page_name=page_name, defaults={'embed_url': embed_url})
    return JsonResponse({'status': 'ok'})


# ── User Management ────────────────────────────────────────────────────────────

@login_required
@admin_required
def user_list(request):
    users = User.objects.select_related('profile').all().order_by('date_joined')
    # Make sure every user has a profile so template can access flags
    for u in users:
        if not hasattr(u, 'profile') or u.profile is None:
            UserProfile.objects.get_or_create(user=u)
    return render(request, 'users.html', {'users': users, 'current_user': request.user})


@login_required
@admin_required
def user_create(request):
    if request.method != 'POST':
        return redirect('user_list')
    username = request.POST.get('username', '').strip()
    password = request.POST.get('password', '').strip()
    if not username or not password:
        messages.error(request, 'Username and password are required.')
        return redirect('user_list')
    if User.objects.filter(username=username).exists():
        messages.error(request, f'Username "{username}" already exists.')
        return redirect('user_list')
    user = User.objects.create_user(username=username, password=password)
    messages.success(request, f'User "{user.username}" created successfully.')
    return redirect('user_list')


@login_required
@admin_required
def user_edit(request, user_id):
    if request.method != 'POST':
        return redirect('user_list')
    try:
        user = User.objects.get(pk=user_id)
    except User.DoesNotExist:
        messages.error(request, 'User not found.')
        return redirect('user_list')

    # Role (admin vs user) — self-change allowed.
    role = request.POST.get('role', '').strip()
    if role in ('admin', 'user'):
        if role == 'admin':
            user.is_superuser = True
            user.is_staff = True
        else:
            user.is_superuser = False
            user.is_staff = False

    # Optional password update
    password = request.POST.get('password', '').strip()
    if password:
        user.set_password(password)
    user.save()

    # Page-access flags on UserProfile (ignored for admins — they see everything)
    profile, _ = UserProfile.objects.get_or_create(user=user)
    for key in ('data_analysis', 'emailing', 'planner', 'sync_monitor', 'automations'):
        setattr(profile, f'can_{key}', request.POST.get(f'can_{key}') == 'on')
    profile.save()

    messages.success(request, f'Updated settings for "{user.username}".')
    return redirect('user_list')


@login_required
@admin_required
def user_delete(request, user_id):
    if request.method != 'POST':
        return redirect('user_list')
    if request.user.pk == user_id:
        messages.error(request, 'You cannot delete your own account.')
        return redirect('user_list')
    try:
        user = User.objects.get(pk=user_id)
        username = user.username
        user.delete()
        messages.success(request, f'User "{username}" deleted.')
    except User.DoesNotExist:
        messages.error(request, 'User not found.')
    return redirect('user_list')


# ── Settings ───────────────────────────────────────────────────────────────────

@login_required
def settings_view(request):
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, 'settings.html', {'dark_mode': profile.dark_mode})


@login_required
def save_settings(request):
    if request.method != 'POST':
        return JsonResponse({'status': 'error'}, status=405)
    data = json.loads(request.body)
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    profile.dark_mode = bool(data.get('dark_mode', False))
    profile.save()
    return JsonResponse({'status': 'ok'})


# ── US-EU List ─────────────────────────────────────────────────────────────────

@login_required
@page_access('emailing')
def useu_list(request):
    # On first load, import CSV data into DB if table is empty
    if USEUContact.objects.count() == 0:
        import csv
        csv_path = os.path.join(django_settings.BASE_DIR, 'US-EU List.csv')
        try:
            with open(csv_path, 'r', encoding='utf-8-sig') as f:
                reader = csv.reader(f)
                next(reader)  # skip header
                batch = []
                for row in reader:
                    batch.append(USEUContact(
                        org_name=row[0] if len(row) > 0 else '',
                        default=row[1] if len(row) > 1 else '',
                        contact_name=row[2] if len(row) > 2 else '',
                        attach=row[3] if len(row) > 3 else '',
                        phone=row[4] if len(row) > 4 else '',
                        email=row[5] if len(row) > 5 else '',
                        touchpoint_1=row[6] if len(row) > 6 else '',
                        tp1_sent_on=row[7] if len(row) > 7 else '',
                        touchpoint_2=row[8] if len(row) > 8 else '',
                        last_touch=row[9] if len(row) > 9 else '',
                        status=row[10].strip() if len(row) > 10 else 'Active',
                        tp1_processing_id=row[11] if len(row) > 11 else '',
                    ))
                USEUContact.objects.bulk_create(batch, batch_size=1000)
        except FileNotFoundError:
            pass

    contacts = USEUContact.objects.all()
    total = contacts.count()
    active_count = contacts.filter(status='Active').count()
    faulty_count = contacts.filter(status='Faulty Data').count()

    # Server-side pagination
    page = int(request.GET.get('page', 1))
    per_page = int(request.GET.get('per_page', 100))
    search = request.GET.get('search', '').strip()

    qs = contacts
    status_filter = request.GET.get('status', '').strip()
    if status_filter:
        qs = qs.filter(status=status_filter)
    if search:
        from django.db.models import Q
        qs = qs.filter(
            Q(org_name__icontains=search) |
            Q(contact_name__icontains=search) |
            Q(email__icontains=search)
        )

    # Date range filter on tp{n}_sent_on. Input format: YYYY-MM-DD (HTML5 date input).
    # DB values use mixed formats ("dd-mm-yyyy" and "dd/mm/yyyy"), so we parse both.
    # sent_field selects which touchpoint column to filter on. If sent_field is set
    # (without dates), we restrict to rows that have that TP sent at all.
    sent_from = request.GET.get('sent_from', '').strip()
    sent_to = request.GET.get('sent_to', '').strip()
    tp_field_param = request.GET.get('sent_field', '').strip()
    allowed_tp_fields = {f'tp{i}_sent_on' for i in range(1, 11)}
    if tp_field_param and tp_field_param not in allowed_tp_fields:
        tp_field_param = ''
    if tp_field_param and (sent_from or sent_to):
        from datetime import datetime as _dt
        def _parse_iso(s):
            try:
                return _dt.strptime(s, '%Y-%m-%d').date()
            except Exception:
                return None
        def _parse_db(s):
            s = (s or '').strip()
            if not s:
                return None
            for fmt in ('%d-%m-%Y', '%d/%m/%Y', '%Y-%m-%d', '%Y/%m/%d'):
                try:
                    return _dt.strptime(s, fmt).date()
                except Exception:
                    continue
            return None
        d_from = _parse_iso(sent_from) if sent_from else None
        d_to = _parse_iso(sent_to) if sent_to else None
        matched_ids = []
        for cid, raw in qs.exclude(**{tp_field_param: ''}).values_list('id', tp_field_param).iterator():
            d = _parse_db(raw)
            if d is None:
                continue
            if d_from and d < d_from:
                continue
            if d_to and d > d_to:
                continue
            matched_ids.append(cid)
        qs = qs.filter(id__in=matched_ids)
    elif tp_field_param:
        qs = qs.exclude(**{tp_field_param: ''}).exclude(**{f'{tp_field_param}__isnull': True})

    filtered_total = qs.count()
    # Send ALL rows to the client so Excel-style filter / sort / paginate run locally.
    rows = list(qs.order_by('id').values_list(
        'id', 'org_name', 'contact_name', 'email', 'phone', 'status', 'last_touch',
        'touchpoint_1', 'tp1_sent_on',
        'touchpoint_2', 'tp2_sent_on',
        'touchpoint_3', 'tp3_sent_on',
        'touchpoint_4', 'tp4_sent_on',
        'touchpoint_5', 'tp5_sent_on',
        'touchpoint_6', 'tp6_sent_on',
        'touchpoint_7', 'tp7_sent_on',
        'touchpoint_8', 'tp8_sent_on',
        'touchpoint_9', 'tp9_sent_on',
        'touchpoint_10', 'tp10_sent_on',
        'deal_lost_reason',
    ))

    # AJAX requests get JSON
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        return JsonResponse({
            'rows': [list(r) for r in rows],
            'total': filtered_total,
            'page': page,
            'per_page': per_page,
        })

    # TP stats: sent count, remaining, undeliverable, last sent date for each TP
    tp_stats = []
    active_with_email = contacts.filter(status='Active').exclude(email='').exclude(email__isnull=True)
    undeliverable_contacts = contacts.filter(status='Undeliverable')

    # Check if any send job is currently running.
    # A job file is "stale" if it hasn't been touched in 2 minutes — the worker
    # writes progress every contact, so a lack of updates means the process died.
    _active_tp = None
    _active_job_id = None
    _base_dir = os.path.join(os.path.dirname(__file__), '..')
    _stale_cutoff = time.time() - 120  # 2 minutes
    for _jf in os.listdir(_base_dir):
        if _jf.startswith('send_job_') and _jf.endswith('.json'):
            _jpath = os.path.join(_base_dir, _jf)
            try:
                _mtime = os.path.getmtime(_jpath)
                with open(_jpath) as _f:
                    _jdata = json.load(_f)
                _done = _jdata.get('done', True)
                if not _done and _mtime < _stale_cutoff:
                    _jdata['done'] = True
                    _jdata['stopped'] = True
                    try:
                        with open(_jpath, 'w') as _fw:
                            json.dump(_jdata, _fw)
                    except Exception:
                        pass
                    try:
                        _tpm = re.search(r'tp(\d+)', _jf)
                        if _tpm:
                            update_touchpoint_progress(f'tp{_tpm.group(1)}', status='idle')
                    except Exception:
                        pass
                    continue
                if not _done:
                    _tp_match = re.search(r'tp(\d+)', _jf)
                    if _tp_match:
                        _active_tp = int(_tp_match.group(1))
                    # Extract job_id from filename: send_job_{job_id}.json
                    _active_job_id = _jf[len('send_job_'):-len('.json')]
            except Exception:
                pass

    for tp_num in range(1, 11):
        sent_field = f'tp{tp_num}_sent_on'
        sent_qs = active_with_email.exclude(**{sent_field: ''})
        sent_count = sent_qs.count()
        remaining = active_with_email.filter(**{sent_field: ''}).count()
        # Count undeliverable contacts that have this TP sent
        undel_count = undeliverable_contacts.exclude(**{sent_field: ''}).count()
        # Get the most recent sent date
        last_sent = sent_qs.order_by(f'-{sent_field}').values_list(sent_field, flat=True).first() or ''
        # Is this TP currently sending?
        is_sending = (_active_tp == tp_num)
        tp_stats.append({
            'num': tp_num,
            'total': sent_count + remaining,
            'sent': sent_count,
            'remaining': remaining,
            'undeliverable': undel_count,
            'last_sent': last_sent,
            'is_sending': is_sending,
        })

    # Status counts for filter badges
    from django.db.models import Count
    status_counts_qs = contacts.values('status').annotate(count=Count('id'))
    status_counts = {s['status']: s['count'] for s in status_counts_qs}

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, 'useu_list.html', {
        'rows_json': json.dumps([list(r) for r in rows]),
        'total_rows': total,
        'filtered_total': filtered_total,
        'active_count': active_count,
        'faulty_count': faulty_count,
        'tp_stats': tp_stats,
        'status_counts': json.dumps(status_counts),
        'dark_mode': profile.dark_mode,
        'current_page': page,
        'per_page': per_page,
        'search': search,
        'active_job_id': _active_job_id or '',
        'active_tp_num': _active_tp or 0,
    })


@login_required
def useu_update_cell(request):
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    try:
        data = json.loads(request.body)
        contact_id = data['id']
        field = data['field']
        value = data['value']
    except (json.JSONDecodeError, KeyError):
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)

    allowed_fields = [
        'org_name', 'contact_name', 'email', 'phone',
        'status', 'last_touch',
        'touchpoint_1', 'tp1_sent_on', 'touchpoint_2', 'tp2_sent_on',
        'touchpoint_3', 'tp3_sent_on', 'touchpoint_4', 'tp4_sent_on',
        'touchpoint_5', 'tp5_sent_on', 'touchpoint_6', 'tp6_sent_on',
        'touchpoint_7', 'tp7_sent_on', 'touchpoint_8', 'tp8_sent_on',
        'touchpoint_9', 'tp9_sent_on', 'touchpoint_10', 'tp10_sent_on',
        'deal_lost_reason',
    ]
    if field not in allowed_fields:
        return JsonResponse({'ok': False, 'error': 'Field not editable'}, status=400)

    try:
        contact = USEUContact.objects.get(id=contact_id)
        prev_status = contact.status
        setattr(contact, field, value)
        update_fields = [field]

        if field == 'status':
            hubspot_values = {'Moved to HubSpot', 'Move to HubSpot'}
            now_hs = value in hubspot_values
            was_hs = prev_status in hubspot_values
            if now_hs and not was_hs:
                contact.moved_to_hubspot_at = django_timezone.now()
                update_fields.append('moved_to_hubspot_at')
            elif was_hs and not now_hs:
                contact.moved_to_hubspot_at = None
                update_fields.append('moved_to_hubspot_at')

        contact.save(update_fields=update_fields)

        # Auto-calculate TP2-TP10 when TP1 date is set
        tp_dates = {}
        if field == 'touchpoint_1' and value:
            tp_dates = _auto_calc_tp_dates(contact, value)

        return JsonResponse({'ok': True, 'tp_dates': tp_dates})
    except USEUContact.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)


# ── US Public Holidays & TP Date Calculation ──────────────────────────────────

def _us_holidays(year):
    """Return a set of US federal holiday dates for a given year."""
    from datetime import date
    holidays = set()

    # New Year's Day - Jan 1
    holidays.add(date(year, 1, 1))

    # MLK Day - 3rd Monday of January
    d = date(year, 1, 1)
    mondays = 0
    while mondays < 3:
        if d.weekday() == 0:
            mondays += 1
            if mondays == 3:
                break
        d += timedelta(days=1)
    holidays.add(d)

    # Presidents Day - 3rd Monday of February
    d = date(year, 2, 1)
    mondays = 0
    while mondays < 3:
        if d.weekday() == 0:
            mondays += 1
            if mondays == 3:
                break
        d += timedelta(days=1)
    holidays.add(d)

    # Memorial Day - Last Monday of May
    d = date(year, 5, 31)
    while d.weekday() != 0:
        d -= timedelta(days=1)
    holidays.add(d)

    # Juneteenth - June 19
    holidays.add(date(year, 6, 19))

    # Independence Day - July 4
    holidays.add(date(year, 7, 4))

    # Labor Day - 1st Monday of September
    d = date(year, 9, 1)
    while d.weekday() != 0:
        d += timedelta(days=1)
    holidays.add(d)

    # Columbus Day - 2nd Monday of October
    d = date(year, 10, 1)
    mondays = 0
    while mondays < 2:
        if d.weekday() == 0:
            mondays += 1
            if mondays == 2:
                break
        d += timedelta(days=1)
    holidays.add(d)

    # Veterans Day - November 11
    holidays.add(date(year, 11, 11))

    # Thanksgiving - 4th Thursday of November
    d = date(year, 11, 1)
    thursdays = 0
    while thursdays < 4:
        if d.weekday() == 3:
            thursdays += 1
            if thursdays == 4:
                break
        d += timedelta(days=1)
    holidays.add(d)

    # Christmas Day - December 25
    holidays.add(date(year, 12, 25))

    return holidays


def _next_valid_send_date(start_date):
    """Given a date, return the next valid send date (not Mon/Fri, not a US holiday)."""
    d = start_date
    holidays = _us_holidays(d.year) | _us_holidays(d.year + 1)
    for _ in range(30):  # safety limit
        # 0=Mon, 4=Fri — skip these
        if d.weekday() not in (0, 4) and d not in holidays:
            return d
        d += timedelta(days=1)
    return d


def _auto_calc_tp_dates(contact, tp1_value):
    """Calculate TP2-TP10 dates based on TP1, 8 days apart, skipping Mon/Fri/weekends/holidays."""
    # Parse TP1 date (DD-MM-YYYY format)
    try:
        parts = tp1_value.strip().split('-')
        if len(parts) == 3 and len(parts[2]) == 4:
            tp1_date = datetime.strptime(tp1_value.strip(), '%d-%m-%Y').date()
        elif len(parts) == 3 and len(parts[0]) == 4:
            tp1_date = datetime.strptime(tp1_value.strip(), '%Y-%m-%d').date()
        else:
            return {}
    except (ValueError, AttributeError):
        return {}

    tp_dates = {}
    prev_date = tp1_date

    for tp_num in range(2, 11):
        # 8 calendar days after previous TP
        candidate = prev_date + timedelta(days=8)
        # Shift to next valid day (Tue/Wed/Thu, no holidays)
        send_date = _next_valid_send_date(candidate)
        display_date = send_date.strftime('%d-%m-%Y')

        setattr(contact, f'touchpoint_{tp_num}', display_date)
        tp_dates[f'touchpoint_{tp_num}'] = display_date
        prev_date = send_date

    contact.save(update_fields=[f'touchpoint_{n}' for n in range(2, 11)])
    return tp_dates


@login_required
@require_http_methods(["POST"])
def useu_create_contact(request):
    """Create a new USEU contact."""
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    contact = USEUContact(
        org_name=data.get('org_name', ''),
        contact_name=data.get('contact_name', ''),
        email=data.get('email', ''),
        phone=data.get('phone', ''),
        status=data.get('status', 'Active'),
        deal_lost_reason=data.get('deal_lost_reason', ''),
    )
    tp1_date = data.get('tp1_date', '')
    if tp1_date:
        contact.touchpoint_1 = tp1_date
    contact.save()

    # Auto-calc TP2-TP10 if TP1 date was provided
    if tp1_date:
        _auto_calc_tp_dates(contact, tp1_date)

    return JsonResponse({'ok': True, 'id': contact.id})


@login_required
@require_http_methods(["POST"])
def useu_edit_contact(request, contact_id):
    """Edit an existing USEU contact."""
    try:
        contact = USEUContact.objects.get(id=contact_id)
    except USEUContact.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    for field in ['org_name', 'contact_name', 'email', 'phone', 'status', 'deal_lost_reason']:
        if field in data:
            setattr(contact, field, data[field])

    tp1_date = data.get('tp1_date', '')
    if tp1_date:
        contact.touchpoint_1 = tp1_date
    contact.save()

    # Auto-calc TP2-TP10 if TP1 date was provided
    if tp1_date:
        _auto_calc_tp_dates(contact, tp1_date)

    return JsonResponse({'ok': True})


@login_required
@require_http_methods(["POST"])
def useu_delete_contact(request, contact_id):
    """Delete a USEU contact."""
    try:
        contact = USEUContact.objects.get(id=contact_id)
        contact.delete()
        return JsonResponse({'ok': True})
    except USEUContact.DoesNotExist:
        return JsonResponse({'ok': False, 'error': 'Not found'}, status=404)


# ── Send All Touchpoint ────────────────────────────────────────────────────────

_send_all_progress = {}  # in-memory progress tracker

@login_required
def send_all_touchpoint(request):
    """Send a touchpoint email to all Active contacts with empty TP sent date."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    tp_num = int(data.get('touchpoint_number', 1))
    if tp_num < 1 or tp_num > 10:
        return JsonResponse({'ok': False, 'error': 'Invalid touchpoint number'}, status=400)

    tp_field = f'touchpoint_{tp_num}'
    tp_sent_field = f'tp{tp_num}_sent_on'
    force_resend = bool(data.get('force_resend'))

    # Find eligible contacts: Active, has email. If force_resend, include already-sent ones.
    if force_resend:
        contacts = list(USEUContact.objects.filter(status='Active').exclude(email='').exclude(email__isnull=True))
        # Clear tp_sent_on so worker treats them as eligible (and re-sends)
        USEUContact.objects.filter(status='Active').exclude(email='').exclude(email__isnull=True).update(**{tp_sent_field: ''})
    else:
        contacts = list(USEUContact.objects.filter(status='Active', **{tp_sent_field: ''}).exclude(email='').exclude(email__isnull=True))

    if not contacts:
        return JsonResponse({'ok': False, 'error': 'No eligible contacts found'}, status=400)

    # TEST_EMAIL_OVERRIDE redirects all emails to the test address
    # but still sends to all eligible contacts so you can test the full flow

    # Get template
    try:
        template = TouchpointTemplate.objects.get(touchpoint_number=tp_num)
    except TouchpointTemplate.DoesNotExist:
        return JsonResponse({'ok': False, 'error': f'Template for TP{tp_num} not found'}, status=404)

    # Init progress
    job_id = f'tp{tp_num}_{int(datetime.now().timestamp())}'
    _send_all_progress[job_id] = {
        'total': len(contacts),
        'sent': 0,
        'failed': 0,
        'current': '',
        'done': False,
        'results': [],
    }

    # Initialize persistent touchpoint progress
    tp_type = f'tp{tp_num}'
    update_touchpoint_progress(tp_type, total=len(contacts), sent=0, failed=0, status="sending")

    import subprocess
    import sys as _sys

    # Pre-create the job file so progress polling works before the subprocess starts
    _job_file = os.path.join(os.path.dirname(__file__), '..', f'send_job_{job_id}.json')
    try:
        import tempfile as _tempfile
        _fd, _tmp = _tempfile.mkstemp(dir=os.path.dirname(_job_file), suffix='.tmp')
        with os.fdopen(_fd, 'w') as _f:
            json.dump({'total': len(contacts), 'sent': 0, 'failed': 0, 'current': '', 'done': False, 'results': []}, _f)
        os.replace(_tmp, _job_file)
    except Exception:
        pass

    # Launch the worker as a detached subprocess so it survives gunicorn restarts
    _worker = os.path.join(os.path.dirname(__file__), '..', 'send_campaign_worker.py')
    _log_file = os.path.join(os.path.dirname(__file__), '..', f'worker_{job_id}.log')
    _log_fh = open(_log_file, 'w')
    subprocess.Popen(
        [_sys.executable, '-u', _worker, '--tp-num', str(tp_num), '--job-id', job_id],
        stdout=_log_fh,
        stderr=_log_fh,
        start_new_session=True,  # detach from gunicorn's process group
    )


    return JsonResponse({'ok': True, 'job_id': job_id, 'total': len(contacts)})


@login_required
def stop_sending(request):
    """Stop an in-progress send campaign by writing a stop signal file."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    job_id = data.get('job_id', '')
    if not job_id:
        return JsonResponse({'ok': False, 'error': 'No job_id provided'}, status=400)

    # Write stop signal file for the worker to pick up
    stop_file = os.path.join(os.path.dirname(__file__), '..', f'send_stop_{job_id}.signal')
    job_file = os.path.join(os.path.dirname(__file__), '..', f'send_job_{job_id}.json')
    try:
        with open(stop_file, 'w') as f:
            f.write('stop')
        # Extract tp number from job_id (e.g. "tp1_1234567890" -> "tp1")
        tp_type = job_id.split('_')[0] if '_' in job_id else ''
        if tp_type:
            update_touchpoint_progress(tp_type, status='idle')
        # Mark job file as done so stale state doesn't persist
        try:
            if os.path.exists(job_file):
                with open(job_file) as jf:
                    jdata = json.load(jf)
                jdata['done'] = True
                jdata['stopped'] = True
                jdata['current'] = 'Stopped by user'
                with open(job_file, 'w') as jf:
                    json.dump(jdata, jf)
        except Exception:
            pass
        # Kill the worker process (cross-platform)
        import subprocess
        import sys as _sys
        if _sys.platform == 'win32':
            subprocess.Popen(
                ['taskkill', '/F', '/FI', f'WINDOWTITLE eq *{job_id}*'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000,
            )
        else:
            subprocess.Popen(['pkill', '-f', f'send_campaign_worker.*{job_id}'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return JsonResponse({'ok': True, 'message': 'Stop signal sent'})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
def send_all_progress(request):
    """Poll progress of a send-all job."""
    job_id = request.GET.get('job_id', '')

    # Always prefer the job file (written by the subprocess worker in real-time)
    progress = None
    _job_file = os.path.join(os.path.dirname(__file__), '..', f'send_job_{job_id}.json')
    if os.path.exists(_job_file):
        try:
            with open(_job_file) as _f:
                progress = json.load(_f)
        except Exception:
            pass

    # Fallback to in-memory dict (only before worker starts writing)
    if not progress:
        progress = _send_all_progress.get(job_id)

    if not progress:
        return JsonResponse({'ok': False, 'error': 'Job not found'}, status=404)

    # Return new results since last poll
    last_idx = int(request.GET.get('last_idx', 0))
    all_results = progress.get('results', [])
    new_results = all_results[last_idx:]

    return JsonResponse({
        'ok': True,
        'total': progress['total'],
        'sent': progress['sent'],
        'failed': progress.get('failed', 0),
        'current': progress.get('current', ''),
        'done': progress.get('done', False),
        'stopped': progress.get('stopped', False),
        'results': new_results,
        'next_idx': len(all_results),
    })


# ── Emails Sent & Status ──────────────────────────────────────────────────────

@login_required
def emails_sent(request):
    """Flat log of every email dispatched (SES, Graph, dry-run) with delivery status."""
    from dashboard.models import EmailSendLog
    logs = EmailSendLog.objects.select_related('contact').all()[:2000]
    rows = []
    status_counts = {'sent': 0, 'delivered': 0, 'bounced': 0, 'complained': 0,
                     'rejected': 0, 'failed': 0, 'dry_run': 0}
    provider_counts = {'ses': 0, 'graph': 0, 'dry_run': 0}
    for l in logs:
        status_counts[l.status] = status_counts.get(l.status, 0) + 1
        provider_counts[l.provider] = provider_counts.get(l.provider, 0) + 1
        rows.append({
            'id': l.id,
            'sent_at': l.sent_at.strftime('%Y-%m-%d %H:%M:%S'),
            'to_address': l.to_address,
            'from_address': l.from_address,
            'contact_name': l.contact.contact_name if l.contact else '—',
            'org_name': l.contact.org_name if l.contact else '—',
            'tp_num': l.touchpoint_number or '',
            'subject': l.subject,
            'provider': l.provider,
            'status': l.status,
            'message_id': l.message_id,
            'error_message': l.error_message,
        })
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, 'emails_sent.html', {
        'rows': rows,
        'total': len(rows),
        'status_counts': status_counts,
        'provider_counts': provider_counts,
        'dark_mode': profile.dark_mode,
    })


_SES_BASELINE_FILE = os.path.join(os.path.dirname(__file__), '..', 'ses_counter_baseline.json')


def _ses_load_baseline():
    try:
        with open(_SES_BASELINE_FILE) as f:
            return json.load(f)
    except Exception:
        return None


def _ses_save_baseline(baseline):
    try:
        with open(_SES_BASELINE_FILE, 'w') as f:
            json.dump(baseline, f)
    except Exception as e:
        print(f'[SES baseline save failed] {e}', flush=True)


def _ses_compute_stats():
    """Returns totals across the 14-day SES statistics window."""
    ses = _get_ses_client()
    q = ses.get_send_quota()
    stats = ses.get_send_statistics().get('SendDataPoints', [])
    totals = {'attempts': 0, 'bounces': 0, 'complaints': 0, 'rejects': 0}
    for s in stats:
        totals['attempts'] += s.get('DeliveryAttempts', 0)
        totals['bounces'] += s.get('Bounces', 0)
        totals['complaints'] += s.get('Complaints', 0)
        totals['rejects'] += s.get('Rejects', 0)
    return q, totals


@login_required
def emails_sent_refresh_stats(request):
    """Pull AWS SES stats. Subtract a baseline captured on first load so counters start from 0."""
    try:
        q, totals = _ses_compute_stats()
        baseline = _ses_load_baseline()
        if baseline is None:
            # First ever call — freeze current totals as baseline
            baseline = {
                'captured_at': __import__('datetime').datetime.utcnow().isoformat(),
                **totals,
            }
            _ses_save_baseline(baseline)

        # Deltas since baseline (never negative)
        deltas = {k: max(0, totals.get(k, 0) - baseline.get(k, 0)) for k in ('attempts', 'bounces', 'complaints', 'rejects')}
        delivered = max(0, deltas['attempts'] - deltas['bounces'] - deltas['complaints'] - deltas['rejects'])

        return JsonResponse({
            'ok': True,
            'quota_max_24h': q['Max24HourSend'],
            'quota_sent_24h': q['SentLast24Hours'],
            'quota_rate_per_sec': q['MaxSendRate'],
            'last_24h': {
                'delivery_attempts': deltas['attempts'],
                'bounces': deltas['bounces'],
                'complaints': deltas['complaints'],
                'rejects': deltas['rejects'],
                'delivered': delivered,
            },
            'baseline_captured_at': baseline.get('captured_at'),
        })
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
def emails_sent_reset_baseline(request):
    """Reset the SES counter baseline to NOW so displayed Sent/Delivered/Bounced start at 0."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    try:
        _, totals = _ses_compute_stats()
        baseline = {
            'captured_at': __import__('datetime').datetime.utcnow().isoformat(),
            **totals,
        }
        _ses_save_baseline(baseline)
        return JsonResponse({'ok': True, 'baseline': baseline})
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@csrf_exempt
def ses_webhook(request):
    """Receive SNS notifications from SES event publishing (delivery/bounce/complaint)
    and update matching EmailSendLog rows by MessageId.
    Subscribe this endpoint to the SNS topic: /webhooks/ses/
    """
    if request.method != 'POST':
        return HttpResponse(status=405)
    try:
        body = json.loads(request.body.decode('utf-8') or '{}')
    except Exception:
        return HttpResponse(status=400)

    msg_type = body.get('Type') or request.headers.get('x-amz-sns-message-type', '')

    # Auto-confirm SNS subscription
    if msg_type == 'SubscriptionConfirmation':
        try:
            import urllib.request
            urllib.request.urlopen(body['SubscribeURL'], timeout=10).read()
            return HttpResponse('confirmed')
        except Exception as e:
            return HttpResponse(f'confirm failed: {e}', status=500)

    if msg_type == 'Notification':
        from dashboard.models import EmailSendLog
        try:
            payload = json.loads(body.get('Message', '{}'))
        except Exception:
            payload = {}
        event_type = (payload.get('eventType') or payload.get('notificationType') or '').lower()
        mail = payload.get('mail', {})
        message_id = mail.get('messageId', '')
        if not message_id:
            return HttpResponse('no messageId', status=200)

        status_map = {
            'delivery': 'delivered',
            'bounce': 'bounced',
            'complaint': 'complained',
            'reject': 'rejected',
            'rendering failure': 'failed',
            'deliverydelay': 'sent',
        }
        new_status = status_map.get(event_type)
        if not new_status:
            return HttpResponse(f'ignored {event_type}', status=200)

        err = ''
        if event_type == 'bounce':
            b = payload.get('bounce', {})
            recips = b.get('bouncedRecipients', [{}])[0]
            err = f"{b.get('bounceType', '')}/{b.get('bounceSubType', '')}: {recips.get('diagnosticCode', '')}"
        elif event_type == 'complaint':
            err = payload.get('complaint', {}).get('complaintFeedbackType', '')

        logs = list(EmailSendLog.objects.filter(message_id=message_id))
        for log in logs:
            log.status = new_status
            log.error_message = err or ''
            log.save(update_fields=['status', 'error_message', 'status_updated_at'])
            # Propagate hard-fail statuses to the contact
            if new_status in ('bounced', 'complained', 'rejected') and log.contact:
                log.contact.status = 'Undeliverable'
                log.contact.save(update_fields=['status'])
                print(f'[SNS] Marked {log.to_address} as Undeliverable ({new_status})', flush=True)
        return HttpResponse('ok')

    return HttpResponse(status=200)


# ── Email Templates ────────────────────────────────────────────────────────────

@login_required
def email_templates(request):
    """Email template editor for touchpoints 1-10"""
    tpl_list = []
    for t in TouchpointTemplate.objects.all():
        tpl_list.append({
            'touchpoint_number': t.touchpoint_number,
            'subject': t.subject,
            'body': t.body,
            'body_html': t.body_html,
            'signature': t.signature,
            'attachment_name': t.attachment.name.split('/')[-1] if t.attachment else '',
            'attachment_url': t.attachment.url if t.attachment else '',
            'signature_image_name': t.signature_image.name.split('/')[-1] if t.signature_image else '',
            'signature_image_url': t.signature_image.url if t.signature_image else '',
            'days_after_previous': t.days_after_previous,
        })
    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, 'email_templates.html', {
        'templates_json': json.dumps(tpl_list),
        'dark_mode': profile.dark_mode,
    })


@login_required
def reporting(request):
    """Summary of list performance by status, with HubSpot growth over time,
    touchpoint coverage, deal-lost reasons, and bounce breakdown."""
    from django.db.models import Count, Q
    from django.db.models.functions import TruncWeek, TruncMonth, TruncYear
    from datetime import datetime as _dt, date as _date, timedelta as _td

    # ── Filters from query string ────────────────────────────────────────────
    date_from_raw = request.GET.get('date_from', '').strip()
    date_to_raw = request.GET.get('date_to', '').strip()
    status_filter = request.GET.get('status', '').strip()

    def _parse_iso(s):
        try:
            return _dt.strptime(s, '%Y-%m-%d').date()
        except Exception:
            return None

    date_from = _parse_iso(date_from_raw)
    date_to = _parse_iso(date_to_raw)

    contacts = USEUContact.objects.all()
    if status_filter:
        if status_filter == 'Moved to HubSpot':
            contacts = contacts.filter(Q(status='Moved to HubSpot') | Q(status='Move to HubSpot'))
        else:
            contacts = contacts.filter(status=status_filter)
    total_contacts = contacts.count()

    status_counts_qs = contacts.values('status').annotate(count=Count('id'))
    status_counts = {s['status']: s['count'] for s in status_counts_qs}

    active = status_counts.get('Active', 0)
    undelivered = status_counts.get('Undeliverable', 0)
    moved_to_hubspot = status_counts.get('Moved to HubSpot', 0) + status_counts.get('Move to HubSpot', 0)
    inactive = status_counts.get('Lost', 0)

    def pct(n):
        return round((n / total_contacts) * 100, 1) if total_contacts else 0.0

    summary = [
        {'label': 'Total contacts', 'value': total_contacts, 'pct': 100.0 if total_contacts else 0.0, 'pill': 'total'},
        {'label': 'Active (still reachable)', 'value': active, 'pct': pct(active), 'pill': 'active'},
        {'label': 'Bad email (bounced)', 'value': undelivered, 'pct': pct(undelivered), 'pill': 'undelivered'},
        {'label': 'Moved to HubSpot', 'value': moved_to_hubspot, 'pct': pct(moved_to_hubspot), 'pill': 'hubspot'},
        {'label': 'Not a fit / lost', 'value': inactive, 'pct': pct(inactive), 'pill': 'inactive'},
    ]

    # HubSpot growth series: rows with a moved_to_hubspot_at timestamp,
    # grouped by week / month / year. The date filter narrows this window.
    hs_rows = USEUContact.objects.filter(moved_to_hubspot_at__isnull=False)
    if date_from:
        hs_rows = hs_rows.filter(moved_to_hubspot_at__date__gte=date_from)
    if date_to:
        hs_rows = hs_rows.filter(moved_to_hubspot_at__date__lte=date_to)

    def build_series(trunc_fn, label_fmt):
        qs = (hs_rows.annotate(bucket=trunc_fn('moved_to_hubspot_at'))
              .values('bucket').annotate(c=Count('id')).order_by('bucket'))
        labels, counts, cum = [], [], []
        running = 0
        for row in qs:
            if not row['bucket']:
                continue
            labels.append(label_fmt(row['bucket']))
            counts.append(row['c'])
            running += row['c']
            cum.append(running)
        return {'labels': labels, 'counts': counts, 'cumulative': cum}

    weekly_series = build_series(TruncWeek, lambda d: d.strftime('Wk of %d %b %Y'))
    monthly_series = build_series(TruncMonth, lambda d: d.strftime('%b %Y'))
    yearly_series = build_series(TruncYear, lambda d: str(d.year))

    # ── Growth KPIs (YoY and MoM) based on unfiltered-but-status-ignoring data.
    # We want growth regardless of the current date/status filter — it's a
    # stable top-line metric. So recompute from all HubSpot-stamped contacts.
    growth_base = USEUContact.objects.filter(moved_to_hubspot_at__isnull=False)

    today = django_timezone.now().date()
    first_this_month = today.replace(day=1)
    first_prev_month = (first_this_month - _td(days=1)).replace(day=1)
    first_prev_prev_month = (first_prev_month - _td(days=1)).replace(day=1)

    mtd_this = growth_base.filter(
        moved_to_hubspot_at__date__gte=first_this_month,
        moved_to_hubspot_at__date__lte=today,
    ).count()
    prev_month_full = growth_base.filter(
        moved_to_hubspot_at__date__gte=first_prev_month,
        moved_to_hubspot_at__date__lt=first_this_month,
    ).count()
    prev_prev_month_full = growth_base.filter(
        moved_to_hubspot_at__date__gte=first_prev_prev_month,
        moved_to_hubspot_at__date__lt=first_prev_month,
    ).count()

    def growth_pct(current, previous):
        if previous <= 0:
            return None if current == 0 else 100.0 * current
        return round(((current - previous) / previous) * 100, 1)

    mom_value = prev_month_full  # last full month
    mom_prev = prev_prev_month_full  # month before
    mom_growth = growth_pct(mom_value, mom_prev)

    # YoY: last 12 months (rolling) vs prior 12 months
    one_year_ago = today - _td(days=365)
    two_years_ago = today - _td(days=730)
    ytd_this_y = growth_base.filter(
        moved_to_hubspot_at__date__gte=one_year_ago,
        moved_to_hubspot_at__date__lte=today,
    ).count()
    ytd_prev_y = growth_base.filter(
        moved_to_hubspot_at__date__gte=two_years_ago,
        moved_to_hubspot_at__date__lt=one_year_ago,
    ).count()
    yoy_growth = growth_pct(ytd_this_y, ytd_prev_y)

    # Touchpoint coverage: how many contacts have each TP sent
    tp_labels = [f'TP{n}' for n in range(1, 11)]
    tp_counts = []
    for n in range(1, 11):
        field = f'tp{n}_sent_on'
        tp_counts.append(
            contacts.exclude(**{field: ''}).exclude(**{f'{field}__isnull': True}).count()
        )

    # Deal lost reasons — count non-empty, bucket by reason text
    lost_with_reason_qs = contacts.exclude(deal_lost_reason='').exclude(deal_lost_reason__isnull=True)
    lost_with_reason = lost_with_reason_qs.count()
    lost_without_reason = inactive - contacts.filter(status='Lost').exclude(deal_lost_reason='').exclude(deal_lost_reason__isnull=True).count()
    lost_without_reason = max(0, lost_without_reason)
    reason_rows = (lost_with_reason_qs.values('deal_lost_reason')
                   .annotate(c=Count('id')).order_by('-c'))
    reason_labels = [r['deal_lost_reason'][:40] for r in reason_rows]
    reason_counts = [r['c'] for r in reason_rows]

    # Bounce breakdown from EmailSendLog — error_message is "{Type}/{SubType}: ..."
    # where Type is "Permanent" (hard) or "Transient" (soft). SES convention.
    hard_bounces = 0
    soft_bounces = 0
    undetermined_bounces = 0
    total_bounces = 0
    try:
        from .models import EmailSendLog
        bounce_logs = EmailSendLog.objects.filter(status='bounced').values_list('error_message', flat=True)
        for err in bounce_logs:
            total_bounces += 1
            low = (err or '').lower()
            if low.startswith('permanent'):
                hard_bounces += 1
            elif low.startswith('transient'):
                soft_bounces += 1
            else:
                undetermined_bounces += 1
    except Exception:
        pass

    STATUS_CHOICES = ['Active', 'Inactive', 'Undeliverable', 'Moved to HubSpot', 'Lost']

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, 'reporting.html', {
        'summary': summary,
        'total_contacts': total_contacts,
        'filter_date_from': date_from_raw,
        'filter_date_to': date_to_raw,
        'filter_status': status_filter,
        'status_choices': STATUS_CHOICES,
        'mom_growth': mom_growth,
        'mom_current': mom_value,
        'mom_previous': mom_prev,
        'mom_label_current': first_prev_month.strftime('%b %Y'),
        'mom_label_previous': first_prev_prev_month.strftime('%b %Y'),
        'yoy_growth': yoy_growth,
        'yoy_current': ytd_this_y,
        'yoy_previous': ytd_prev_y,
        'mtd_this': mtd_this,
        'mtd_label': first_this_month.strftime('%b %Y'),
        'pie_full': json.dumps({
            'labels': ['Active', 'Undelivered', 'Moved to HubSpot', 'Inactive'],
            'data': [active, undelivered, moved_to_hubspot, inactive],
        }),
        'pie_compare': json.dumps({
            'labels': ['Active', 'Undelivered', 'Moved to HubSpot'],
            'data': [active, undelivered, moved_to_hubspot],
        }),
        'hs_series': json.dumps({
            'week': weekly_series,
            'month': monthly_series,
            'year': yearly_series,
        }),
        'tp_coverage': json.dumps({'labels': tp_labels, 'counts': tp_counts}),
        'lost_reason_chart': json.dumps({'labels': reason_labels, 'counts': reason_counts}),
        'lost_with_reason': lost_with_reason,
        'lost_without_reason': lost_without_reason,
        'reason_rows': [{'reason': r['deal_lost_reason'], 'count': r['c']} for r in reason_rows],
        'bounce_chart': json.dumps({
            'labels': ['Hard (Permanent)', 'Soft (Transient)', 'Undetermined'],
            'counts': [hard_bounces, soft_bounces, undetermined_bounces],
        }),
        'hard_bounces': hard_bounces,
        'soft_bounces': soft_bounces,
        'undetermined_bounces': undetermined_bounces,
        'total_bounces': total_bounces,
        'dark_mode': profile.dark_mode,
    })


@login_required
def email_template_save(request):
    """Save a touchpoint email template (multipart form for file upload)"""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    try:
        tp_num = int(request.POST.get('touchpoint_number', 0))
        if tp_num < 1 or tp_num > 10:
            return JsonResponse({'ok': False, 'error': 'Invalid touchpoint number'}, status=400)
    except (ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)

    defaults = {
        'subject': request.POST.get('subject', ''),
        'body': request.POST.get('body', ''),
        'body_html': request.POST.get('body_html', ''),
        'signature': request.POST.get('signature', ''),
        'days_after_previous': int(request.POST.get('days_after_previous', 7)),
    }

    template, _ = TouchpointTemplate.objects.update_or_create(
        touchpoint_number=tp_num, defaults=defaults
    )

    # Handle file attachment
    if 'attachment' in request.FILES:
        template.attachment = request.FILES['attachment']
        template.save(update_fields=['attachment'])
    elif request.POST.get('clear_attachment') == '1':
        if template.attachment:
            template.attachment.delete(save=False)
            template.attachment = None
            template.save(update_fields=['attachment'])

    # Handle signature image upload (separate file input)
    if 'signature_image' in request.FILES:
        template.signature_image = request.FILES['signature_image']
        template.save(update_fields=['signature_image'])
    elif request.POST.get('clear_signature_image') == '1':
        if template.signature_image:
            template.signature_image.delete(save=False)
            template.signature_image = None
            template.save(update_fields=['signature_image'])

    att_name = template.attachment.name.split('/')[-1] if template.attachment else ''
    att_url = template.attachment.url if template.attachment else ''
    sig_name = template.signature_image.name.split('/')[-1] if template.signature_image else ''
    sig_url = template.signature_image.url if template.signature_image else ''
    return JsonResponse({
        'ok': True,
        'signature_image_name': sig_name,
        'signature_image_url': sig_url,
        'attachment_name': att_name,
        'attachment_url': att_url,
        'body_html': template.body_html,
    })


# ── Touchpoint Schedule ──────────────────────────────────────────────────────

@login_required
def set_touchpoint_schedule(request):
    """Set the scheduled date for a touchpoint and update all contacts' touchpoint_X field."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    try:
        data = json.loads(request.body)
        tp_num = int(data.get('touchpoint_number', 0))
        date_str = data.get('scheduled_date', '')  # YYYY-MM-DD or empty to clear
    except (json.JSONDecodeError, ValueError, TypeError):
        return JsonResponse({'ok': False, 'error': 'Invalid data'}, status=400)

    if tp_num < 1 or tp_num > 10:
        return JsonResponse({'ok': False, 'error': 'Invalid touchpoint number (1-10 only)'}, status=400)

    tp_field = f'touchpoint_{tp_num}'

    if date_str:
        # Accept either 'YYYY-MM-DD' or 'YYYY-MM-DD HH:MM' (SAST). Store date+time on contacts.
        from datetime import datetime as dt
        parsed = None
        for fmt in ('%Y-%m-%d %H:%M', '%Y-%m-%d'):
            try:
                parsed = dt.strptime(date_str, fmt)
                break
            except ValueError:
                continue
        if parsed is None:
            return JsonResponse({'ok': False, 'error': 'Invalid date format'}, status=400)
        display_date = parsed.strftime('%d-%m-%Y %H:%M') if parsed.hour or parsed.minute else parsed.strftime('%d-%m-%Y')

        # Update all contacts' touchpoint_X field to this date
        updated = USEUContact.objects.all().update(**{tp_field: display_date})

        # Save to template's scheduled_date
        template, _ = TouchpointTemplate.objects.update_or_create(
            touchpoint_number=tp_num,
            defaults={'scheduled_date': parsed.date()}
        )

        return JsonResponse({'ok': True, 'updated': updated, 'date': display_date})
    else:
        # Clear the schedule
        USEUContact.objects.all().update(**{tp_field: ''})
        try:
            template = TouchpointTemplate.objects.get(touchpoint_number=tp_num)
            template.scheduled_date = None
            template.save(update_fields=['scheduled_date'])
        except TouchpointTemplate.DoesNotExist:
            pass
        return JsonResponse({'ok': True, 'updated': 0, 'date': ''})


@login_required
def get_touchpoint_schedules(request):
    """Get current scheduled dates for all touchpoints."""
    schedules = {}
    # Get from templates
    for t in TouchpointTemplate.objects.all():
        if t.scheduled_date:
            schedules[t.touchpoint_number] = t.scheduled_date.strftime('%Y-%m-%d 09:00')

    # Also check what's actually set on contacts for each TP
    from django.db import connection
    with connection.cursor() as cur:
        for tp_num in range(2, 11):
            field = f'touchpoint_{tp_num}'
            cur.execute(f"SELECT {field}, COUNT(*) FROM useu_contacts WHERE {field} IS NOT NULL AND {field} != '' GROUP BY {field} ORDER BY COUNT(*) DESC LIMIT 1")
            row = cur.fetchone()
            if row and tp_num not in schedules:
                schedules[tp_num] = row[0]  # Show what's currently set

    return JsonResponse({'ok': True, 'schedules': schedules})


# ── Send Touchpoint Email ─────────────────────────────────────────────────────

GRAPH_CLIENT_ID = '43fbe5a9-6b5b-4c81-9067-7aff9ac3ed5a'
GRAPH_TENANT_ID = 'b1504b1d-d096-409a-a0f0-6cc546dde993'
GRAPH_CLIENT_SECRET = os.getenv('GRAPH_CLIENT_SECRET', '')
GRAPH_MAILBOX = 'Ethan.Sevenster@moc-pty.com'


def _gmail_send_mail(to_address, subject, body_html=None, body_text=None,
                     from_address=None, from_name='Magnum Opus Consultants',
                     attachments=None):
    """Send via Gmail SMTP (fallback when SES is quota-blocked)."""
    import smtplib, base64
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email.mime.image import MIMEImage
    from email import encoders
    user = os.getenv('GMAIL_USER', '')
    pw = os.getenv('GMAIL_APP_PASSWORD', '').replace(' ', '')
    if not user or not pw:
        err = 'Gmail: GMAIL_USER / GMAIL_APP_PASSWORD not set'
        _log_email_send(to_address, subject, provider='ses', status='failed', error_message=err)
        return False, err

    src = f'{from_name} <{user}>' if from_name else user
    msg = MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From'] = src
    msg['To'] = to_address

    if body_html:
        related = MIMEMultipart('related')
        related.attach(MIMEText(body_html, 'html', 'utf-8'))
        for att in (attachments or []):
            if att.get('isInline'):
                img = MIMEImage(base64.b64decode(att.get('contentBytes', '')))
                img.add_header('Content-ID', f"<{att.get('contentId','')}>")
                img.add_header('Content-Disposition', 'inline', filename=att.get('name', 'image.png'))
                related.attach(img)
        msg.attach(related)
    elif body_text:
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

    for att in (attachments or []):
        if att.get('isInline'):
            continue
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(base64.b64decode(att.get('contentBytes', '')))
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment', filename=att.get('name', 'attachment'))
        msg.attach(part)

    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465, timeout=30) as s:
            s.login(user, pw)
            s.sendmail(user, [to_address], msg.as_string())
        _log_email_send(to_address, subject, provider='ses', status='sent',
                        message_id=f'gmail-{int(__import__("time").time())}',
                        from_address=user)
        return True, 'gmail-sent'
    except Exception as e:
        err = f'Gmail SMTP: {e}'
        _log_email_send(to_address, subject, provider='ses', status='failed', error_message=err)
        return False, err


def _log_email_send(to_address, subject, provider='ses', status='sent',
                    message_id='', error_message='', from_address='', tp_num=None):
    """Write an EmailSendLog row. Never raises — logging failures must not break sends."""
    try:
        from dashboard.models import EmailSendLog, USEUContact
        contact = USEUContact.objects.filter(email__iexact=to_address).first()
        EmailSendLog.objects.create(
            contact=contact,
            to_address=to_address,
            from_address=from_address or django_settings.AWS_SES_FROM_EMAIL,
            touchpoint_number=tp_num,
            subject=(subject or '')[:998],
            provider=provider,
            status=status,
            message_id=message_id,
            error_message=error_message,
        )
    except Exception as _e:
        print(f"[LOG] EmailSendLog write failed: {_e}", flush=True)


def _graph_send_simple(to_address, subject, body_html=None, body_text=None, attachments=None):
    """Minimal Graph send helper — builds payload and sends via sendMail.
    Returns (success, message_id_or_error) matching the _ses_send_mail signature.
    """
    token = _get_graph_token()
    if not token:
        return False, 'Graph: no access token'
    content_type = 'HTML' if body_html else 'Text'
    content = body_html if body_html else (body_text or '')
    msg_attachments = []
    for att in (attachments or []):
        msg_attachments.append({
            '@odata.type': '#microsoft.graph.fileAttachment',
            'name': att.get('name', 'attachment'),
            'contentType': att.get('contentType', 'application/octet-stream'),
            'contentBytes': att.get('contentBytes', ''),
            'isInline': bool(att.get('isInline')),
            'contentId': att.get('contentId', ''),
        })
    payload = {
        'message': {
            'subject': subject,
            'body': {'contentType': content_type, 'content': content},
            'toRecipients': [{'emailAddress': {'address': to_address}}],
            'attachments': msg_attachments,
        },
        'saveToSentItems': True,
    }
    try:
        ok, status = _graph_send_mail(token, payload)
        if ok:
            _log_email_send(to_address, subject, provider='graph', status='sent', message_id=f'graph-{status}')
            return True, f'graph-{status}'
        err = f'Graph status {status}'
        _log_email_send(to_address, subject, provider='graph', status='failed', error_message=err)
        return False, err
    except Exception as e:
        _log_email_send(to_address, subject, provider='graph', status='failed', error_message=str(e))
        return False, f'Graph exception: {e}'


def _get_graph_token():
    app = msal.ConfidentialClientApplication(
        GRAPH_CLIENT_ID,
        authority=f'https://login.microsoftonline.com/{GRAPH_TENANT_ID}',
        client_credential=GRAPH_CLIENT_SECRET,
    )
    result = app.acquire_token_for_client(scopes=['https://graph.microsoft.com/.default'])
    return result.get('access_token')


# ── Unsubscribe / opt-out ─────────────────────────────────────────────────────

UNSUBSCRIBE_SALT = 'useu-unsubscribe-v1'


def _unsubscribe_signer():
    return signing.TimestampSigner(salt=UNSUBSCRIBE_SALT)


def _make_unsubscribe_token(contact_id):
    return _unsubscribe_signer().sign(str(contact_id))


def _build_unsubscribe_url(contact_id, request=None):
    token = _make_unsubscribe_token(contact_id)
    base = (os.getenv('PUBLIC_BASE_URL') or '').rstrip('/')
    if not base and request is not None:
        base = request.build_absolute_uri('/').rstrip('/')
    if not base:
        base = 'http://127.0.0.1:8000'
    return f"{base}/unsubscribe/{token}/"


def _append_unsubscribe_footer(body, contact, is_html, request=None):
    if not contact or not getattr(contact, 'id', None):
        return body
    url = _build_unsubscribe_url(contact.id, request=request)
    if is_html:
        footer = (
            '<div style="margin-top:32px;padding-top:16px;border-top:1px solid #e5e7eb;'
            'color:#6b7280;font-size:12px;font-family:Arial,sans-serif;line-height:1.5;">'
            'You are receiving this email because you are on the contact list at Magnum Opus Consultants.'
            '<br>If you no longer wish to receive these emails, '
            f'<a href="{url}" style="color:#2563eb;text-decoration:underline;">click here to unsubscribe</a>.'
            '</div>'
        )
        # Insert before </body> if present, else append
        if '</body>' in body.lower():
            return re.sub(r'</body>', footer + '</body>', body, count=1, flags=re.IGNORECASE)
        return body + footer
    footer = (
        '\n\n--\n'
        'You are receiving this email because you are on the contact list at Magnum Opus Consultants.\n'
        f'To unsubscribe: {url}\n'
    )
    return body + footer


def _render_unsub_page(title, heading, body_html, *, status=200, accent='#2d6b86'):
    page = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title} · Magnum Opus Consultants</title>
<link href="https://fonts.googleapis.com/css2?family=Segoe+UI:wght@300;400;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg: #f4f6f9;
    --surface: #ffffff;
    --border: #d8dfe6;
    --text-primary: #1a2838;
    --text-secondary: #526070;
    --text-muted: #8d9aa7;
    --accent: {accent};
    --accent-hover: #1f5670;
    --suiteheader-bg: #1a2838;
  }}
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  html, body {{ min-height: 100%; }}
  body {{
    font-family: 'Segoe UI', -apple-system, BlinkMacSystemFont, sans-serif;
    background-color: var(--bg);
    color: var(--text-primary);
    min-height: 100vh;
    display: flex;
    flex-direction: column;
  }}
  body::before {{
    content: '';
    position: fixed;
    inset: 0;
    z-index: -1;
    background:
      linear-gradient(rgba(244,246,249,0.55), rgba(244,246,249,0.70)),
      url('/static/HOME-The-process.png') center/cover no-repeat;
    background-attachment: fixed;
    pointer-events: none;
  }}
  .topbar {{
    background: var(--suiteheader-bg);
    color: #e9eef4;
    padding: 12px 24px;
    font-weight: 600;
    font-size: 15px;
    letter-spacing: 0.2px;
    box-shadow: 0 1px 0 rgba(0,0,0,0.06);
  }}
  .topbar .brand-mark {{
    display: inline-flex;
    align-items: center;
    gap: 12px;
  }}
  .topbar .brand-mark img {{
    width: 30px;
    height: 30px;
    border-radius: 6px;
    display: block;
  }}
  main {{
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 40px 20px;
  }}
  .card {{
    width: 100%;
    max-width: 520px;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 14px;
    padding: 36px 36px 32px;
    box-shadow: 0 12px 40px rgba(26,40,56,0.10), 0 2px 6px rgba(26,40,56,0.06);
  }}
  .eyebrow {{
    text-transform: uppercase;
    letter-spacing: 1.2px;
    font-size: 11px;
    font-weight: 700;
    color: var(--accent);
    margin-bottom: 10px;
  }}
  h1 {{
    font-size: 24px;
    font-weight: 700;
    color: var(--text-primary);
    margin-bottom: 14px;
    line-height: 1.25;
  }}
  p {{
    color: var(--text-secondary);
    line-height: 1.6;
    margin-bottom: 14px;
    font-size: 15px;
  }}
  p strong {{ color: var(--text-primary); font-weight: 600; }}
  .btn {{
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--accent);
    color: #fff;
    border: 0;
    padding: 12px 22px;
    border-radius: 8px;
    font-size: 14px;
    font-weight: 600;
    font-family: inherit;
    cursor: pointer;
    transition: background 0.15s ease, transform 0.05s ease;
    text-decoration: none;
  }}
  .btn:hover {{ background: var(--accent-hover); }}
  .btn:active {{ transform: translateY(1px); }}
  .btn-danger {{ background: #b91c1c; }}
  .btn-danger:hover {{ background: #991b1b; }}
  .muted {{
    color: var(--text-muted);
    font-size: 13px;
    margin-top: 18px;
  }}
  footer.brand-footer {{
    text-align: center;
    color: var(--text-muted);
    font-size: 12px;
    padding: 18px 12px 28px;
  }}
  footer.brand-footer a {{ color: var(--accent); text-decoration: none; }}
</style>
</head>
<body>
  <div class="topbar">
    <span class="brand-mark"><img src="/static/favicon-192.png" alt="MOC"> Magnum Opus Consultants</span>
  </div>
  <main>
    <div class="card">
      <div class="eyebrow">Email preferences</div>
      <h1>{heading}</h1>
      {body_html}
    </div>
  </main>
  <footer class="brand-footer">
    &copy; Magnum Opus Consultants
  </footer>
</body>
</html>"""
    return HttpResponse(page, status=status)


@csrf_exempt
def unsubscribe(request, token):
    """Public endpoint hit when a recipient clicks 'unsubscribe' in an email."""
    try:
        contact_id = int(_unsubscribe_signer().unsign(token, max_age=60 * 60 * 24 * 365 * 5))
    except (signing.BadSignature, ValueError):
        return _render_unsub_page(
            'Invalid link', 'Invalid or expired link',
            '<p>This unsubscribe link is no longer valid. Please contact us directly to be removed from our list.</p>',
            status=400, accent='#b91c1c',
        )

    contact = USEUContact.objects.filter(id=contact_id).first()
    if not contact:
        return _render_unsub_page(
            'Invalid link', 'Invalid or expired link',
            '<p>This unsubscribe link is no longer valid. Please contact us directly to be removed from our list.</p>',
            status=404, accent='#b91c1c',
        )

    already = bool(contact.opted_out_at)

    if request.method == 'POST':
        if not already:
            contact.opted_out_at = django_timezone.now()
            contact.status = 'Inactive'
            contact.save(update_fields=['opted_out_at', 'status'])
        who = contact.contact_name or contact.email
        return _render_unsub_page(
            'Unsubscribed', 'You have been unsubscribed',
            f'<p>{who}, you will no longer receive emails from <strong>Magnum Opus Consultants</strong>.</p>'
            '<p class="muted">If this was a mistake, please contact us directly to be re-added.</p>',
        )

    # GET — confirm page (protects against link-prefetchers)
    if already:
        return _render_unsub_page(
            'Already unsubscribed', "You're already unsubscribed",
            f'<p>The email address <strong>{contact.email}</strong> is no longer on our list.</p>'
            '<p class="muted">If this was a mistake, please contact us directly to be re-added.</p>',
        )

    body_html = (
        f'<p>Are you sure you want to stop receiving emails from <strong>Magnum Opus Consultants</strong> '
        f'at <strong>{contact.email}</strong>?</p>'
        f'<form method="post" action="/unsubscribe/{token}/" style="margin-top:18px;">'
        '<button type="submit" class="btn btn-danger">Yes, unsubscribe me</button>'
        '</form>'
        '<p class="muted">You can re-subscribe at any time by contacting us.</p>'
    )
    return _render_unsub_page('Unsubscribe', 'Unsubscribe', body_html)


# ── AWS SES Email Sending ─────────────────────────────────────────────────────

def _get_ses_client():
    """Create and return a boto3 SES client."""
    return boto3.client(
        'ses',
        region_name=django_settings.AWS_SES_REGION,
        aws_access_key_id=django_settings.AWS_SES_ACCESS_KEY_ID,
        aws_secret_access_key=django_settings.AWS_SES_SECRET_ACCESS_KEY,
    )


def _ses_send_mail(to_address, subject, body_html=None, body_text=None,
                   from_address=None, from_name='Ethan Sevenster',
                   attachments=None, max_retries=3):
    """Send an email via AWS SES. For emails with attachments, uses raw email.

    Returns (success: bool, message_id_or_error: str).
    """
    if os.getenv('SES_DRY_RUN') == '1':
        real_list = [e.strip().lower() for e in (os.getenv('SES_DRY_RUN_EXCEPT') or '').split(',') if e.strip()]
        if to_address.lower() not in real_list:
            att_info = ''
            if attachments:
                names = [a.get('name', '?') for a in attachments]
                att_info = f" | attachments={names}"
            body_len = len(body_html or body_text or '')
            print(f"[DRY-RUN] TO={to_address} | subject={subject!r} | body_len={body_len}{att_info}", flush=True)
            _log_email_send(to_address, subject, provider='dry_run', status='dry_run', message_id='dry-run')
            return True, 'dry-run-message-id'
        print(f"[DRY-RUN] Real send (exception list) to {to_address}", flush=True)

    if not from_address:
        from_address = django_settings.AWS_SES_FROM_EMAIL

    source = f'{from_name} <{from_address}>' if from_name else from_address

    # If there are attachments, use raw email via SES send_raw_email
    if attachments:
        return _ses_send_raw_mail(
            to_address, subject, body_html, body_text,
            source, from_address, attachments, max_retries
        )

    # Simple email (no attachments)
    ses = _get_ses_client()
    body = {}
    if body_html:
        body['Html'] = {'Data': body_html, 'Charset': 'UTF-8'}
    if body_text:
        body['Text'] = {'Data': body_text, 'Charset': 'UTF-8'}
    if not body:
        body['Text'] = {'Data': '', 'Charset': 'UTF-8'}

    for attempt in range(max_retries):
        try:
            response = ses.send_email(
                Source=source,
                Destination={'ToAddresses': [to_address]},
                Message={
                    'Subject': {'Data': subject, 'Charset': 'UTF-8'},
                    'Body': body,
                },
            )
            _log_email_send(to_address, subject, provider='ses', status='sent',
                            message_id=response['MessageId'], from_address=from_address)
            return True, response['MessageId']
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'Throttling':
                time.sleep(2 * (attempt + 1))
                continue
            err_msg = f"{error_code}: {e.response['Error']['Message']}"
            _log_email_send(to_address, subject, provider='ses', status='failed',
                            error_message=err_msg, from_address=from_address)
            return False, err_msg
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return False, str(e)

    return False, 'Max retries exceeded'


def _ses_send_raw_mail(to_address, subject, body_html, body_text,
                       source, from_address, attachments, max_retries=3):
    """Send a raw MIME email via SES (supports attachments)."""
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email.mime.image import MIMEImage
    from email import encoders

    msg = MIMEMultipart('mixed')
    msg['Subject'] = subject
    msg['From'] = source
    msg['To'] = to_address

    # Body part (prefer HTML)
    if body_html:
        # Use related for inline images
        body_related = MIMEMultipart('related')
        body_related.attach(MIMEText(body_html, 'html', 'utf-8'))

        # Attach inline images (like signature)
        for att in (attachments or []):
            if att.get('isInline'):
                content_bytes = base64.b64decode(att.get('contentBytes', ''))
                img = MIMEImage(content_bytes)
                img.add_header('Content-ID', f"<{att.get('contentId', '')}>")
                img.add_header('Content-Disposition', 'inline', filename=att.get('name', 'image.png'))
                body_related.attach(img)

        msg.attach(body_related)
    elif body_text:
        msg.attach(MIMEText(body_text, 'plain', 'utf-8'))

    # Regular attachments (non-inline)
    for att in (attachments or []):
        if att.get('isInline'):
            continue  # already handled above
        content_bytes = base64.b64decode(att.get('contentBytes', ''))
        part = MIMEBase('application', 'octet-stream')
        part.set_payload(content_bytes)
        encoders.encode_base64(part)
        part.add_header('Content-Disposition', 'attachment', filename=att.get('name', 'attachment'))
        msg.attach(part)

    ses = _get_ses_client()
    for attempt in range(max_retries):
        try:
            response = ses.send_raw_email(
                Source=from_address,
                Destinations=[to_address],
                RawMessage={'Data': msg.as_string()},
            )
            return True, response['MessageId']
        except ClientError as e:
            error_code = e.response['Error']['Code']
            if error_code == 'Throttling':
                time.sleep(2 * (attempt + 1))
                continue
            return False, f"{error_code}: {e.response['Error']['Message']}"
        except Exception as e:
            if attempt < max_retries - 1:
                time.sleep(2 * (attempt + 1))
                continue
            return False, str(e)

    return False, 'Max retries exceeded'


def _graph_send_mail(token, payload, max_retries=5):
    """Send an email via Graph API with 429 throttle retry and large-attachment support.

    If the JSON payload exceeds ~3.5 MB (Graph /sendMail limit is 4 MB for the
    whole JSON body), it automatically switches to the draft-then-upload flow
    so attachments up to 150 MB work.

    Returns (success: bool, status_code: int).
    """
    import sys
    
    # Debug log to see if emails are being attempted
    recipient = payload.get('message', {}).get('toRecipients', [{}])[0].get('emailAddress', {}).get('address', 'unknown')
    print(f"[DEBUG] Attempting Graph API email send to: {recipient}")

    headers = {'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'}

    # ── Estimate payload size (base64 attachments dominate) ──────────────
    attachments = payload.get('message', {}).get('attachments', [])
    att_bytes_total = sum(len(a.get('contentBytes', '')) for a in attachments)
    # contentBytes is already a base64 string; measure it directly as float
    estimated_json_mb = float(att_bytes_total) / (1024.0 * 1024.0)

    use_upload_session = estimated_json_mb > 3.0  # stay safely under 4 MB limit

    if not use_upload_session:
        # ── Normal /sendMail (small messages) ──────────────────────────
        for attempt in range(max_retries):
            try:
                r = http_requests.post(
                    f'https://graph.microsoft.com/v1.0/users/{GRAPH_MAILBOX}/sendMail',
                    headers=headers, json=payload, timeout=60,
                )
                if r.status_code == 202:
                    return True, 202
                if r.status_code == 429:
                    retry_after = int(r.headers.get('Retry-After', 10))
                    time.sleep(retry_after + attempt * 5)
                elif r.status_code == 413:
                    # Payload too large — fall back to upload session
                    use_upload_session = True
                    break
                elif r.status_code == 401:
                    token = _get_graph_token()
                    if token:
                        headers['Authorization'] = f'Bearer {token}'
                    time.sleep(1)
                else:
                    return False, r.status_code
            except Exception:
                time.sleep(3 * (attempt + 1))
        if not use_upload_session:
            return False, 0

    # ── Large-message flow: create draft → upload attachments → send ───
    try:
        # 1. Create a draft message (without attachments)
        draft_payload = json.loads(json.dumps(payload))  # deep copy
        draft_msg = draft_payload.get('message', {})
        large_atts = draft_msg.pop('attachments', [])
        save_to_sent = draft_payload.get('saveToSentItems', True)

        for attempt in range(max_retries):
            r = http_requests.post(
                f'https://graph.microsoft.com/v1.0/users/{GRAPH_MAILBOX}/messages',
                headers=headers, json=draft_msg, timeout=60,
            )
            if r.status_code in (200, 201):
                break
            if r.status_code == 429:
                time.sleep(int(r.headers.get('Retry-After', 10)) + attempt * 5)
            else:
                return False, r.status_code
        else:
            return False, 0

        draft_id = r.json().get('id')
        if not draft_id:
            return False, 0

        # 2. Upload each attachment (inline or regular)
        for att in large_atts:
            att_name = att.get('name', 'attachment')
            att_content_bytes = base64.b64decode(att.get('contentBytes', ''))
            att_size = len(att_content_bytes)
            is_inline = att.get('isInline', False)
            content_id = att.get('contentId', '')

            if att_size < 3 * 1024 * 1024:
                # Small attachment — add directly to draft
                add_url = f'https://graph.microsoft.com/v1.0/users/{GRAPH_MAILBOX}/messages/{draft_id}/attachments'
                for attempt in range(max_retries):
                    r = http_requests.post(add_url, headers=headers, json=att, timeout=60)
                    if r.status_code in (200, 201):
                        break
                    if r.status_code == 429:
                        time.sleep(int(r.headers.get('Retry-After', 10)) + attempt * 5)
                    else:
                        break
            else:
                # Large attachment — use upload session
                session_payload = {
                    'AttachmentItem': {
                        'attachmentType': 'file',
                        'name': att_name,
                        'size': att_size,
                        'isInline': is_inline,
                    }
                }
                if content_id:
                    session_payload['AttachmentItem']['contentId'] = content_id

                sess_url = (f'https://graph.microsoft.com/v1.0/users/{GRAPH_MAILBOX}'
                            f'/messages/{draft_id}/attachments/createUploadSession')
                r = http_requests.post(sess_url, headers=headers, json=session_payload, timeout=60)
                if r.status_code not in (200, 201):
                    continue  # skip this attachment

                upload_url = r.json().get('uploadUrl')
                if not upload_url:
                    continue

                # Upload in 3 MB chunks
                chunk_size = 3 * 1024 * 1024
                for offset in range(0, att_size, chunk_size):
                    end = min(offset + chunk_size, att_size)
                    chunk = att_content_bytes[offset:end]
                    chunk_headers = {
                        'Content-Type': 'application/octet-stream',
                        'Content-Length': str(len(chunk)),
                        'Content-Range': f'bytes {offset}-{end - 1}/{att_size}',
                    }
                    for attempt in range(max_retries):
                        cr = http_requests.put(upload_url, headers=chunk_headers, data=chunk, timeout=120)
                        if cr.status_code in (200, 201, 202):
                            break
                        if cr.status_code == 429:
                            time.sleep(int(cr.headers.get('Retry-After', 10)))
                        else:
                            break

        # 3. Send the draft
        send_url = f'https://graph.microsoft.com/v1.0/users/{GRAPH_MAILBOX}/messages/{draft_id}/send'
        for attempt in range(max_retries):
            r = http_requests.post(send_url, headers=headers, timeout=60)
            if r.status_code == 202:
                return True, 202
            if r.status_code == 429:
                time.sleep(int(r.headers.get('Retry-After', 10)) + attempt * 5)
            else:
                return False, r.status_code

        return False, 0
    except Exception as exc:
        import logging
        logging.getLogger(__name__).error(f'Large-message send failed: {exc}')
        return False, 0


@login_required
def send_touchpoint(request):
    """Send a touchpoint email to specific contacts via AWS SES."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    tp_num = data.get('touchpoint_number', 1)
    recipients = data.get('recipients', [])  # list of email addresses

    if not recipients:
        return JsonResponse({'ok': False, 'error': 'No recipients specified'}, status=400)

    try:
        template = TouchpointTemplate.objects.get(touchpoint_number=tp_num)
    except TouchpointTemplate.DoesNotExist:
        return JsonResponse({'ok': False, 'error': f'Template for TP{tp_num} not found'}, status=404)

    # Determine email body
    if template.body_html:
        body_content = template.body_html
        content_type = 'HTML'
    else:
        body_content = template.body
        if template.signature:
            body_content += '\n\n' + template.signature
        content_type = 'Text'

    # Embed uploaded signature image as inline CID attachment (optional, per template)
    sig_inline = None
    if content_type == 'HTML' and getattr(template, 'signature_image', None):
        try:
            sig_path = template.signature_image.path
            sig_name = os.path.basename(sig_path)
            ext = os.path.splitext(sig_name)[1].lower().lstrip('.') or 'png'
            cid = f'signature_tp{template.touchpoint_number}'
            body_content = re.sub(
                r'https://drive\.google\.com/thumbnail\?id=[^"\'&]+(?:&amp;[^"\']*|&[^"\']*)*',
                f'cid:{cid}',
                body_content,
                flags=re.IGNORECASE,
            )
            with open(sig_path, 'rb') as sf:
                sig_inline = {
                    'name': sig_name,
                    'contentType': f'image/{ext if ext!="jpg" else "jpeg"}',
                    'contentBytes': base64.b64encode(sf.read()).decode('utf-8'),
                    'contentId': cid,
                    'isInline': True,
                }
        except Exception as e:
            print(f'[views] signature_image load failed: {e}', flush=True)

    results = []
    for email_addr in recipients:
        email_addr = email_addr.strip()
        if not email_addr:
            continue

        # Override recipient for testing
        test_override = getattr(django_settings, 'TEST_EMAIL_OVERRIDE', None)
        original_email = email_addr
        if test_override:
            email_addr = test_override

        # Look up contact for variable substitution
        contact = USEUContact.objects.filter(email__iexact=original_email).first()

        # Skip contacts that have opted out
        if contact and contact.opted_out_at:
            results.append({'email': email_addr, 'ok': False, 'status': 'opted-out — skipped'})
            continue

        final_body = body_content
        if contact:
            final_body = final_body.replace('{{org_name}}', contact.org_name or '')
            final_body = final_body.replace('{{contact_name}}', contact.contact_name or '')
            final_body = final_body.replace('{{email}}', contact.email or '')
            final_body = final_body.replace('{{phone}}', contact.phone or '')
            final_body = final_body.replace('{{touchpoint_number}}', str(tp_num))

        # Append unsubscribe footer (only when we have a contact record to track)
        final_body = _append_unsubscribe_footer(
            final_body, contact, is_html=(content_type == 'HTML'), request=request,
        )

        subject = template.subject
        if contact:
            subject = subject.replace('{{org_name}}', contact.org_name or '')
            subject = subject.replace('{{contact_name}}', contact.contact_name or '')

        # Build attachments list
        attachments = []
        if template.attachment:
            try:
                att_path = template.attachment.path
                with open(att_path, 'rb') as f:
                    att_bytes = f.read()
                raw_name = os.path.basename(att_path)
                name_part, ext = os.path.splitext(raw_name)
                att_name = name_part.replace('_', ' ').replace('-', ' ')
                att_name = ' '.join(att_name.split()) + ext
                attachments.append({
                    'name': att_name,
                    'contentBytes': base64.b64encode(att_bytes).decode('utf-8'),
                })
            except Exception:
                pass
        if sig_inline:
            attachments.append(sig_inline)

        # Send via AWS SES
        body_html = final_body if content_type == 'HTML' else None
        body_text = final_body if content_type == 'Text' else None
        sent_ok, msg_id = _ses_send_mail(
            to_address=email_addr,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            attachments=attachments if attachments else None,
        )
        results.append({'email': email_addr, 'ok': sent_ok, 'status': msg_id})

        # Pace sends
        if sent_ok:
            time.sleep(0.1)

        # Update contact record if sent successfully
        if sent_ok and contact:
            tp_field = f'touchpoint_{tp_num}'
            tp_sent_field = f'tp{tp_num}_sent_on'
            now_str = datetime.now().strftime('%d/%m/%Y')
            update_fields = {tp_field: 'Sent', tp_sent_field: now_str, 'last_touch': str(tp_num)}
            USEUContact.objects.filter(id=contact.id).update(**update_fields)

    return JsonResponse({'ok': True, 'results': results})


@login_required
def send_test_touchpoint(request):
    """Send a test email for a touchpoint to user-specified recipients.
    Uses sample variable values so the user can see exactly what clients receive.
    Does NOT update any contact records."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)

    try:
        data = json.loads(request.body)
    except json.JSONDecodeError:
        return JsonResponse({'ok': False, 'error': 'Invalid JSON'}, status=400)

    tp_num = data.get('touchpoint_number', 1)
    recipients = data.get('recipients', [])

    if not recipients:
        return JsonResponse({'ok': False, 'error': 'Enter at least one email address'}, status=400)

    # Limit to 10 test recipients at a time
    recipients = [e.strip() for e in recipients if e.strip()][:10]

    try:
        template = TouchpointTemplate.objects.get(touchpoint_number=tp_num)
    except TouchpointTemplate.DoesNotExist:
        return JsonResponse({'ok': False, 'error': f'Template for TP{tp_num} not found. Save the template first.'}, status=404)

    # Determine email body
    if template.body_html:
        body_content = template.body_html
        content_type = 'HTML'
    else:
        body_content = template.body
        if template.signature:
            body_content += '\n\n' + template.signature
        content_type = 'Text'

    # Embed uploaded signature image as inline CID attachment
    sig_inline = None
    if content_type == 'HTML' and getattr(template, 'signature_image', None):
        try:
            sig_path = template.signature_image.path
            sig_name = os.path.basename(sig_path)
            ext = os.path.splitext(sig_name)[1].lower().lstrip('.') or 'png'
            cid = f'signature_tp{template.touchpoint_number}'
            body_content = re.sub(
                r'https://drive\.google\.com/thumbnail\?id=[^"\'&]+(?:&amp;[^"\']*|&[^"\']*)*',
                f'cid:{cid}',
                body_content,
                flags=re.IGNORECASE,
            )
            with open(sig_path, 'rb') as sf:
                sig_inline = {
                    'name': sig_name,
                    'contentType': f'image/{ext if ext!="jpg" else "jpeg"}',
                    'contentBytes': base64.b64encode(sf.read()).decode('utf-8'),
                    'contentId': cid,
                    'isInline': True,
                }
        except Exception as e:
            print(f'[views] test email signature_image load failed: {e}', flush=True)

    # Sample variable values for the test email
    sample_vars = {
        '{{org_name}}': 'Sample Corp Inc.',
        '{{contact_name}}': 'John Doe',
        '{{email}}': 'johndoe@samplecorp.com',
        '{{phone}}': '+1 (555) 123-4567',
        '{{touchpoint_number}}': str(tp_num),
    }

    # Build attachments list once
    attachments = []
    if template.attachment:
        try:
            att_path = template.attachment.path
            with open(att_path, 'rb') as f:
                att_bytes = f.read()
            raw_name = os.path.basename(att_path)
            name_part, ext = os.path.splitext(raw_name)
            att_name = name_part.replace('_', ' ').replace('-', ' ')
            att_name = ' '.join(att_name.split()) + ext
            attachments.append({
                'name': att_name,
                'contentBytes': base64.b64encode(att_bytes).decode('utf-8'),
            })
        except Exception:
            pass
    if sig_inline:
        attachments.append(sig_inline)

    # Substitute variables in subject and body — identical to what clients receive
    subject = template.subject
    final_body = body_content
    for var, val in sample_vars.items():
        subject = subject.replace(var, val)
        final_body = final_body.replace(var, val)

    results = []
    for email_addr in recipients:
        body_html = final_body if content_type == 'HTML' else None
        body_text = final_body if content_type == 'Text' else None
        sent_ok, msg_id = _ses_send_mail(
            to_address=email_addr,
            subject=subject,
            body_html=body_html,
            body_text=body_text,
            attachments=attachments if attachments else None,
        )
        results.append({'email': email_addr, 'ok': sent_ok, 'status': msg_id})
        if sent_ok:
            time.sleep(0.1)

    sent_count = sum(1 for r in results if r['ok'])
    return JsonResponse({
        'ok': True,
        'results': results,
        'message': f'Test email sent to {sent_count}/{len(recipients)} recipients',
    })


# Touchpoint Progress Tracking
def update_touchpoint_progress(tp_type, total=None, sent=None, failed=None, current_email="", status="idle"):
    """Update touchpoint sending progress (atomic write to prevent corruption)."""
    import json
    import os
    import tempfile
    from datetime import datetime

    progress_file = os.path.join(os.path.dirname(__file__), '..', 'touchpoint_progress.json')

    try:
        if os.path.exists(progress_file):
            with open(progress_file, 'r') as f:
                raw = f.read().strip()
                # Fix double-brace corruption if present
                while raw.endswith('}}') and not raw.endswith('"}}'):
                    raw = raw[:-1]
                progress = json.loads(raw) if raw else {}
        else:
            progress = {}

        if tp_type not in progress:
            progress[tp_type] = {}

        # Update provided values
        if total is not None:
            progress[tp_type]['total_contacts'] = total
        if sent is not None:
            progress[tp_type]['sent_count'] = sent
        if failed is not None:
            progress[tp_type]['failed_count'] = failed
        if current_email:
            progress[tp_type]['current_email'] = current_email

        progress[tp_type]['status'] = status
        progress[tp_type]['last_updated'] = datetime.now().isoformat()

        if status == "sending" and 'started_at' not in progress[tp_type]:
            progress[tp_type]['started_at'] = datetime.now().isoformat()
        elif status == "idle":
            progress[tp_type]['started_at'] = None

        # Atomic write: write to temp file then rename
        dir_name = os.path.dirname(progress_file)
        fd, tmp_path = tempfile.mkstemp(dir=dir_name, suffix='.tmp')
        try:
            with os.fdopen(fd, 'w') as f:
                json.dump(progress, f, indent=2)
            os.replace(tmp_path, progress_file)
        except Exception:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise
    except Exception as e:
        print(f"Error updating touchpoint progress: {e}")

def get_touchpoint_progress(tp_type):
    """Get touchpoint sending progress"""
    import json
    import os
    
    progress_file = os.path.join(os.path.dirname(__file__), '..', 'touchpoint_progress.json')
    
    try:
        if os.path.exists(progress_file):
            with open(progress_file, 'r') as f:
                progress = json.load(f)
                return progress.get(tp_type, {
                    'total_contacts': 0,
                    'sent_count': 0,
                    'failed_count': 0,
                    'current_email': '',
                    'status': 'idle'
                })
    except Exception as e:
        print(f"Error reading touchpoint progress: {e}")
    
    return {
        'total_contacts': 0,
        'sent_count': 0,
        'failed_count': 0,
        'current_email': '',
        'status': 'idle'
    }

@require_http_methods(["GET"])
def get_tp_progress(request):
    """AJAX endpoint to get touchpoint progress"""
    tp_type = request.GET.get('tp_type', 'tp1')
    progress = get_touchpoint_progress(tp_type)
    return JsonResponse(progress)


def import_ops(request):
    """Import Operations page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM import_ops")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT mode) FROM import_ops WHERE mode != ''")
            mode_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT origin_country) FROM import_ops WHERE origin_country != ''")
            origin_country_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT destination_country) FROM import_ops WHERE destination_country != ''")
            dest_country_count = cursor.fetchone()[0] or 0
    except:
        total_records = mode_count = origin_country_count = dest_country_count = 0

    last_sync = onedrive_sync.get_import_ops_last_sync()

    return render(request, 'import_ops.html', {
        'total_records': total_records,
        'mode_count': mode_count,
        'origin_country_count': origin_country_count,
        'dest_country_count': dest_country_count,
        'last_sync': last_sync
    })


# Import Ops sync progress tracking
import_ops_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_import_ops_progress(status, message, current=0, total=0):
    global import_ops_sync_progress
    import_ops_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_import_ops(request):
    """Sync Import Ops data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_import_ops_progress('starting', 'Starting Import Ops sync...', 0, 100)

        def run_sync():
            try:
                update_import_ops_progress('syncing', 'Checking OneDrive for Import Ops files...', 10, 100)
                count = onedrive_sync.sync_import_ops_data()
                if count > 0:
                    update_import_ops_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_import_ops_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_import_ops_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_import_ops_progress_view(request):
    """Get Import Ops sync progress"""
    return JsonResponse(import_ops_sync_progress)


def accruals(request):
    """Accruals page — reuses the wip_accrual table, different view/lens."""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM wip_accrual")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT branch) FROM wip_accrual WHERE branch != ''")
            branch_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT dept) FROM wip_accrual WHERE dept != ''")
            dept_count = cursor.fetchone()[0] or 0
    except Exception:
        total_records = branch_count = dept_count = 0

    return render(request, 'accruals.html', {
        'total_records': total_records,
        'branch_count': branch_count,
        'dept_count': dept_count,
    })


@login_required
def wip_accrual(request):
    """WIP & Accrual Report page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM wip_accrual")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT branch) FROM wip_accrual WHERE branch != ''")
            branch_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT dept) FROM wip_accrual WHERE dept != ''")
            dept_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT type) FROM wip_accrual WHERE type != ''")
            type_count = cursor.fetchone()[0] or 0
    except:
        total_records = branch_count = dept_count = type_count = 0

    last_sync = onedrive_sync.get_wip_accrual_last_sync()

    return render(request, 'wip_accrual.html', {
        'total_records': total_records,
        'branch_count': branch_count,
        'dept_count': dept_count,
        'type_count': type_count,
        'last_sync': last_sync
    })


# WIP Accrual sync progress tracking
wip_accrual_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_wip_accrual_progress(status, message, current=0, total=0):
    global wip_accrual_sync_progress
    wip_accrual_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total
    }


@login_required
def sync_wip_accrual(request):
    """Sync WIP Accrual data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_wip_accrual_progress('starting', 'Starting WIP Accrual sync...', 0, 100)

        def run_sync():
            try:
                update_wip_accrual_progress('syncing', 'Checking OneDrive for WIP Accrual files...', 10, 100)
                count = onedrive_sync.sync_wip_accrual_data()
                if count > 0:
                    update_wip_accrual_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_wip_accrual_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_wip_accrual_progress('error', f'Error: {str(e)}', 0, 100)

        thread = threading.Thread(target=run_sync)
        thread.start()

        return JsonResponse({'status': 'started', 'message': 'Sync started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_wip_accrual_progress_view(request):
    """Get WIP Accrual sync progress"""
    return JsonResponse(wip_accrual_sync_progress)


# --- Software: Planner & Gantt ---

@login_required
@page_access('planner')
def planner(request):
    """System planner - Kanban board grouped by project"""
    if request.method == 'POST':
        action = request.POST.get('action')
        if action == 'create':
            ProjectTask.objects.create(
                title=request.POST.get('title', '').strip(),
                description=request.POST.get('description', '').strip(),
                status=request.POST.get('status', 'todo'),
                priority=request.POST.get('priority', 'medium'),
                company=request.POST.get('company', '').strip(),
                project_name=request.POST.get('project_name', '').strip(),
                start_date=request.POST.get('start_date') or None,
                end_date=request.POST.get('end_date') or None,
                start_time=request.POST.get('start_time') or None,
                end_time=request.POST.get('end_time') or None,
            )
        elif action == 'update':
            task_id = request.POST.get('task_id')
            try:
                task = ProjectTask.objects.get(id=task_id)
                task.title = request.POST.get('title', task.title).strip()
                task.description = request.POST.get('description', task.description).strip()
                task.status = request.POST.get('status', task.status)
                task.priority = request.POST.get('priority', task.priority)
                task.company = request.POST.get('company', task.company).strip()
                task.project_name = request.POST.get('project_name', task.project_name).strip()
                task.start_date = request.POST.get('start_date') or None
                task.end_date = request.POST.get('end_date') or None
                task.start_time = request.POST.get('start_time') or None
                task.end_time = request.POST.get('end_time') or None
                task.save()
            except ProjectTask.DoesNotExist:
                pass
        elif action == 'delete':
            task_id = request.POST.get('task_id')
            ProjectTask.objects.filter(id=task_id).delete()
        elif action == 'move':
            task_id = request.POST.get('task_id')
            new_status = request.POST.get('status')
            ProjectTask.objects.filter(id=task_id).update(status=new_status)
            return JsonResponse({'status': 'ok'})
        return redirect('planner')

    tasks = ProjectTask.objects.filter(parent=None).order_by('project_name', 'created_at')
    projects = tasks.values_list('project_name', flat=True).distinct()

    columns = [
        ('backlog', 'Backlog'),
        ('todo', 'To Do'),
        ('in_progress', 'In Progress'),
        ('review', 'Review'),
        ('done', 'Done'),
    ]

    board = {}
    for status, label in columns:
        board[status] = {'label': label, 'tasks': list(tasks.filter(status=status))}

    tasks_json = [{
        'id': t.id,
        'title': t.title,
        'description': t.description,
        'status': t.status,
        'priority': t.priority,
        'company': t.company,
        'company_display': t.get_company_display() if t.company else '',
        'project_name': t.project_name,
        'start_date': t.start_date.isoformat() if t.start_date else '',
        'end_date': t.end_date.isoformat() if t.end_date else '',
        'start_time': t.start_time.strftime('%H:%M') if t.start_time else '',
        'end_time': t.end_time.strftime('%H:%M') if t.end_time else '',
    } for t in tasks]

    return render(request, 'planner.html', {
        'board': board,
        'columns': columns,
        'projects': sorted(set(p for p in projects if p)),
        'all_tasks': tasks,
        'tasks_json': tasks_json,
    })


@login_required
@page_access('planner')
def gantt(request):
    """Gantt chart for all project tasks with dates"""
    tasks = ProjectTask.objects.filter(
        parent=None, start_date__isnull=False, end_date__isnull=False
    ).order_by('project_name', 'start_date')

    import json as _json
    tasks_data = [
        {
            'id': t.id,
            'title': t.title,
            'project': t.project_name or 'General',
            'status': t.status,
            'priority': t.priority,
            'start': t.start_date.isoformat(),
            'end': t.end_date.isoformat(),
        }
        for t in tasks
    ]

    return render(request, 'gantt.html', {
        'tasks_json': _json.dumps(tasks_data),
        'has_tasks': bool(tasks_data),
    })


# ── TFS Weekly Data ──────────────────────────────────────────────────────────

@login_required
def tfs(request):
    """TFS Weekly Data page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM tfs_weekly")
            total_records = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT year) FROM tfs_weekly")
            year_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT week_number) FROM tfs_weekly")
            week_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COALESCE(SUM(revenue), 0) FROM tfs_weekly WHERE year = (SELECT MAX(year) FROM tfs_weekly)")
            ytd_revenue = cursor.fetchone()[0] or 0
            cursor.execute("SELECT MAX(num_trucks) FROM tfs_weekly")
            num_trucks = cursor.fetchone()[0] or 32
            cursor.execute("SELECT AVG(utilization_pct) FROM tfs_weekly WHERE utilization_pct IS NOT NULL")
            avg_util = cursor.fetchone()[0]
            avg_util = float(avg_util) * 100 if avg_util else 0
    except:
        total_records = year_count = week_count = 0
        ytd_revenue = 0
        num_trucks = 32
        avg_util = 0

    last_sync = onedrive_sync.get_tfs_last_sync()

    return render(request, 'tfs.html', {
        'total_records': total_records,
        'year_count': year_count,
        'week_count': week_count,
        'ytd_revenue': f"{ytd_revenue:,.2f}",
        'num_trucks': num_trucks,
        'avg_util': f"{avg_util:.1f}",
        'last_sync': last_sync,
    })


tfs_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def update_tfs_progress(status, message, current=0, total=0):
    global tfs_sync_progress
    tfs_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total,
    }


@login_required
def sync_tfs(request):
    """Sync TFS data from OneDrive"""
    if request.method == 'POST':
        if not onedrive_sync.get_access_token():
            return JsonResponse({'status': 'error', 'message': 'OneDrive not connected'})

        update_tfs_progress('starting', 'Starting TFS sync...', 0, 100)

        def run_sync():
            try:
                update_tfs_progress('syncing', 'Checking OneDrive for TFS files...', 10, 100)
                count = onedrive_sync.sync_tfs_data()
                if count > 0:
                    update_tfs_progress('complete', f'Synced {count} records', 100, 100)
                else:
                    update_tfs_progress('complete', 'No files to sync', 100, 100)
            except Exception as e:
                update_tfs_progress('error', f'Error: {str(e)}', 0, 100)

        import threading
        threading.Thread(target=run_sync, daemon=True).start()
        return JsonResponse({'status': 'started'})

    return JsonResponse({'status': 'error', 'message': 'Invalid request method'})


@login_required
def sync_tfs_progress(request):
    """Get TFS sync progress"""
    return JsonResponse(tfs_sync_progress)


# ── Up-Down Trader Report ──────────────────────────────────────────────────────

updown_trader_sync_progress = {'status': 'idle', 'message': '', 'current': 0, 'total': 0}


def _update_updown_progress(status, message, current=0, total=0):
    global updown_trader_sync_progress
    updown_trader_sync_progress = {
        'status': status,
        'message': message,
        'current': current,
        'total': total,
    }


def _get_updown_trader_last_sync():
    try:
        sync_file = os.path.join(os.path.dirname(__file__), '..', 'updown_trader_last_sync.json')
        with open(sync_file, 'r') as f:
            data = json.load(f)
            if 'last_sync' in data:
                dt = datetime.fromisoformat(data['last_sync'])
                return {'time': dt.strftime('%H:%M'), 'date': dt.strftime('%B %d, %Y')}
    except Exception:
        pass
    return None


@login_required
def updown_trader(request):
    """Up-Down Trader Report page"""
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT COUNT(*) FROM customer_spend")
            cs_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(*) FROM customer_spend_operational")
            cso_count = cursor.fetchone()[0] or 0
            cursor.execute("SELECT COUNT(DISTINCT debtor) FROM customer_spend")
            debtor_count = cursor.fetchone()[0] or 0
    except Exception:
        cs_count = cso_count = debtor_count = 0

    last_sync = _get_updown_trader_last_sync()

    # Fetch file list from SharePoint
    sp_files = []
    try:
        import requests as req
        token = _get_graph_token()
        if token:
            headers = {'Authorization': f'Bearer {token}'}
            sr = req.get(f'https://graph.microsoft.com/v1.0/sites/{UPDOWN_SHAREPOINT_SITE}',
                         headers=headers, timeout=15)
            sr.raise_for_status()
            site_id = sr.json()['id']
            dr = req.get(f'https://graph.microsoft.com/v1.0/sites/{site_id}/drive',
                         headers=headers, timeout=15)
            dr.raise_for_status()
            drive_id = dr.json()['id']
            fr = req.get(
                f'https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{UPDOWN_SHAREPOINT_FOLDER}:/children',
                headers=headers, timeout=15)
            fr.raise_for_status()
            for item in fr.json().get('value', []):
                name = item.get('name', '')
                if name.lower().endswith(('.xlsx', '.xls')):
                    sp_files.append({
                        'name': name,
                        'size': item.get('size', 0),
                        'modified': item.get('lastModifiedDateTime', ''),
                        'web_url': item.get('webUrl', ''),
                    })
    except Exception:
        pass

    # Fetch customer_spend_summary preview data
    summary_headers = []
    summary_rows = []
    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT * FROM customer_spend_summary LIMIT 50")
            summary_headers = [desc[0] for desc in cursor.description]
            summary_rows = cursor.fetchall()
    except Exception:
        pass

    return render(request, 'updown_trader.html', {
        'cs_count': cs_count,
        'cso_count': cso_count,
        'debtor_count': debtor_count,
        'last_sync': last_sync,
        'sp_files': sp_files,
        'summary_headers': summary_headers,
        'summary_rows': summary_rows,
    })


UPDOWN_SHAREPOINT_SITE = 'magnumopusconsultantspty352.sharepoint.com:/sites/DataPrime'
UPDOWN_SHAREPOINT_FOLDER = 'Clients/ISCM/Up Down Trader Report/Shipment Data'


@login_required
def sync_updown_trader(request):
    """Sync Up-Down Trader data from SharePoint folder"""
    if request.method != 'POST':
        return JsonResponse({'status': 'error', 'message': 'Invalid request method'})

    _update_updown_progress('starting', 'Starting SharePoint sync...', 0, 100)

    def run_sync():
        import tempfile, requests as req, base64

        temp_files = []
        try:
            from data.up_down_trader.load_data import (
                ensure_tables, upsert_customer_spend, upsert_customer_spend_operational,
                _extract_year, dedupe_operational, trim_to_source_year, rebuild_summary_view
            )

            # Get Graph API token
            _update_updown_progress('syncing', 'Connecting to SharePoint...', 5, 100)
            token = _get_graph_token()
            if not token:
                _update_updown_progress('error', 'Graph API token unavailable', 0, 100)
                return
            headers = {'Authorization': f'Bearer {token}'}

            # Get site and drive
            sr = req.get(f'https://graph.microsoft.com/v1.0/sites/{UPDOWN_SHAREPOINT_SITE}',
                         headers=headers, timeout=30)
            sr.raise_for_status()
            site_id = sr.json()['id']

            dr = req.get(f'https://graph.microsoft.com/v1.0/sites/{site_id}/drive',
                         headers=headers, timeout=30)
            dr.raise_for_status()
            drive_id = dr.json()['id']

            # List files in folder
            _update_updown_progress('syncing', 'Listing SharePoint files...', 10, 100)
            fr = req.get(
                f'https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{UPDOWN_SHAREPOINT_FOLDER}:/children',
                headers=headers, timeout=30)
            fr.raise_for_status()
            items = [i for i in fr.json().get('value', [])
                     if i.get('name', '').lower().endswith(('.xlsx', '.xls'))]

            if not items:
                _update_updown_progress('complete', 'No Excel files found in SharePoint folder', 100, 100)
                return

            ensure_tables()
            total_records = 0
            cs_count = 0
            op_count = 0
            operational_truncated = False

            for idx, item in enumerate(items):
                fname = item['name']
                # Only load 2024 onward (2024, 2025, 2026 and future years); skip older files.
                fyear = _extract_year(fname)
                if fyear and fyear < 2024:
                    continue
                pct = 15 + int(70 * idx / len(items))
                _update_updown_progress('syncing', f'Downloading {fname}...', pct, 100)

                # Download file content
                dl = req.get(
                    f'https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item["id"]}/content',
                    headers=headers, timeout=120)
                dl.raise_for_status()

                # Save to temp file
                tmp = tempfile.NamedTemporaryFile(delete=False, suffix='.xlsx')
                tmp.write(dl.content)
                tmp.close()
                temp_files.append(tmp.name)

                # Detect file type and process
                import openpyxl
                wb = openpyxl.load_workbook(tmp.name, read_only=True, data_only=True)
                sheets = wb.sheetnames
                wb.close()

                has_financial = 'Financial Data ' in sheets or 'Financial Data' in sheets
                has_operational = 'Operational Data' in sheets or 'Shipment Profile' in sheets

                # Financial Data is no longer used. The report sources job income
                # and revenue from the shipment profile (operational) data only.
                if has_financial:
                    _update_updown_progress('syncing', f'Skipping {fname} — financial data no longer used', pct + 5, 100)

                if has_operational:
                    if not operational_truncated:
                        # Truncate once before first operational insert
                        with connection.cursor() as cur:
                            cur.execute("TRUNCATE customer_spend_operational RESTART IDENTITY")
                        operational_truncated = True
                    _update_updown_progress('syncing', f'Processing Operational data from {fname}...', pct + 10, 100)
                    count = upsert_customer_spend_operational(
                        tmp.name,
                        progress_callback=lambda msg, cur, tot: _update_updown_progress('syncing', msg, cur, tot),
                        truncate=False
                    )
                    op_count += count
                    # Tag the rows just inserted with the year of this file, so a
                    # year's column comes only from that year's file.
                    y = _extract_year(fname)
                    if y:
                        with connection.cursor() as cur:
                            cur.execute("UPDATE customer_spend_operational SET source_year=%s WHERE source_year IS NULL", [y])

            total_records = cs_count + op_count

            # Shipment files overlap, so the same shipment can be appended from
            # multiple files — remove duplicate rows before building the report
            # view (otherwise every summed value is doubled).
            _update_updown_progress('syncing', 'Removing duplicate rows...', 90, 100)
            dedupe_operational()

            # Keep only rows whose recognition year matches their source file year,
            # so e.g. the 2025 file's 2024-recognised rows don't bleed into 2024.
            _update_updown_progress('syncing', 'Trimming to source-file year...', 91, 100)
            trim_to_source_year()

            # Rebuild the summary view with all discovered years
            _update_updown_progress('syncing', 'Rebuilding summary view...', 92, 100)
            rebuild_summary_view()

            # Save last sync timestamp
            sync_file = os.path.join(os.path.dirname(__file__), '..', 'updown_trader_last_sync.json')
            with open(sync_file, 'w') as f:
                json.dump({
                    'last_sync': datetime.now(ZoneInfo('Africa/Johannesburg')).isoformat(),
                    'records': total_records
                }, f)

            msg = f'Synced {len(items)} files: {cs_count} spend + {op_count} operational records'
            _update_updown_progress('complete', msg, 100, 100)

        except Exception as e:
            import traceback
            traceback.print_exc()
            _update_updown_progress('error', f'Error: {str(e)}', 0, 100)
        finally:
            for path in temp_files:
                try:
                    os.unlink(path)
                except OSError:
                    pass

    import threading
    threading.Thread(target=run_sync, daemon=True).start()
    return JsonResponse({'status': 'started'})


@login_required
def sync_updown_trader_progress(request):
    """Get Up-Down Trader sync progress"""
    return JsonResponse(updown_trader_sync_progress)


@login_required
def automations_panel(request):
    """Automations control panel — toggle, pause, and manage scheduled jobs."""
    from .scheduler import scheduler as bg_scheduler

    jobs_data = []
    if bg_scheduler:
        for job in bg_scheduler.get_jobs():
            next_run = job.next_run_time
            jobs_data.append({
                'id': job.id,
                'name': job.name,
                'next_run': next_run.strftime('%Y-%m-%d %H:%M:%S') if next_run else 'Paused',
                'is_paused': next_run is None,
                'trigger': str(job.trigger),
            })

    # Categorize jobs
    email_jobs = [j for j in jobs_data if j['id'] in ('scheduled_touchpoints', 'bounce_check')]
    sync_jobs = [j for j in jobs_data if j['id'].endswith('_sync')]
    system_jobs = [j for j in jobs_data if j['id'] not in [ej['id'] for ej in email_jobs] and j['id'] not in [sj['id'] for sj in sync_jobs]]

    profile, _ = UserProfile.objects.get_or_create(user=request.user)
    return render(request, 'automations_panel.html', {
        'email_jobs': email_jobs,
        'sync_jobs': sync_jobs,
        'system_jobs': system_jobs,
        'total_jobs': len(jobs_data),
        'dark_mode': profile.dark_mode,
    })


@login_required
def automation_toggle(request):
    """Pause or resume a scheduled job."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    from .scheduler import scheduler as bg_scheduler
    if not bg_scheduler:
        return JsonResponse({'ok': False, 'error': 'Scheduler not running'}, status=500)

    data = json.loads(request.body)
    job_id = data.get('job_id', '')
    action = data.get('action', '')  # 'pause', 'resume', 'remove', 'run_now'

    try:
        job = bg_scheduler.get_job(job_id)
        if not job:
            return JsonResponse({'ok': False, 'error': f'Job {job_id} not found'}, status=404)

        if action == 'pause':
            job.pause()
            return JsonResponse({'ok': True, 'status': 'paused'})
        elif action == 'resume':
            job.resume()
            return JsonResponse({'ok': True, 'status': 'resumed'})
        elif action == 'remove':
            bg_scheduler.remove_job(job_id)
            return JsonResponse({'ok': True, 'status': 'removed'})
        elif action == 'run_now':
            job.func()
            return JsonResponse({'ok': True, 'status': 'executed'})
        else:
            return JsonResponse({'ok': False, 'error': 'Invalid action'}, status=400)
    except Exception as e:
        return JsonResponse({'ok': False, 'error': str(e)}, status=500)


@login_required
def automation_stop_all_emails(request):
    """Stop all email-related automation jobs."""
    if request.method != 'POST':
        return JsonResponse({'ok': False, 'error': 'POST required'}, status=405)
    from .scheduler import scheduler as bg_scheduler
    if not bg_scheduler:
        return JsonResponse({'ok': False, 'error': 'Scheduler not running'}, status=500)

    stopped = []
    for job_id in ('scheduled_touchpoints', 'bounce_check'):
        job = bg_scheduler.get_job(job_id)
        if job:
            job.pause()
            stopped.append(job_id)

    # Also kill any running campaign workers
    import subprocess
    import sys as _sys
    if _sys.platform == 'win32':
        subprocess.Popen(['taskkill', '/F', '/FI', 'WINDOWTITLE eq *send_campaign*'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=0x08000000)
    else:
        subprocess.Popen(['pkill', '-f', 'send_campaign_worker'],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    return JsonResponse({'ok': True, 'stopped': stopped})


# ── Documentation API: Company → System → Documents ─────────────────────────────
def _doc_auth(request):
    return request.user.is_authenticated


def _company_dict(c):
    return {
        'id': c.id,
        'name': c.name,
        'logo': c.logo,
        'brand_color': c.brand_color,
        'industry': c.industry,
        'website': c.website,
        'contact_name': c.contact_name,
        'contact_email': c.contact_email,
        'contact_phone': c.contact_phone,
        'description': c.description,
        'systems': c.systems.count(),
        'documents': DocDocument.objects.filter(system__company=c).count(),
    }


@csrf_exempt
def api_doc_companies(request):
    err = _require_module(request, 'documentation')
    if err:
        return err
    if request.method == 'POST':
        try:
            data = json.loads(request.body or b'{}')
        except json.JSONDecodeError:
            data = {}
        name = (data.get('name') or '').strip()
        if not name:
            return JsonResponse({'detail': 'Company name required.'}, status=400)
        obj, created = DocCompany.objects.get_or_create(name=name)
        return JsonResponse(_company_dict(obj), status=201 if created else 200)
    return JsonResponse({'companies': [_company_dict(c) for c in DocCompany.objects.all()]})


@csrf_exempt
@require_http_methods(["GET", "PATCH", "POST", "DELETE"])
def api_doc_company_detail(request, pk):
    err = _require_module(request, 'documentation')
    if err:
        return err
    c = DocCompany.objects.filter(id=pk).first()
    if not c:
        return JsonResponse({'detail': 'Company not found.'}, status=404)
    if request.method == 'DELETE':
        c.delete()
        return JsonResponse({'ok': True})
    if request.method in ('PATCH', 'POST'):
        try:
            data = json.loads(request.body or b'{}')
        except json.JSONDecodeError:
            data = {}
        if 'name' in data:
            new_name = (data.get('name') or '').strip()
            if not new_name:
                return JsonResponse({'detail': 'Company name required.'}, status=400)
            if DocCompany.objects.filter(name=new_name).exclude(id=c.id).exists():
                return JsonResponse({'detail': 'Another company already uses that name.'}, status=400)
            c.name = new_name
        for f in ['brand_color', 'industry', 'website', 'contact_name', 'contact_email', 'contact_phone', 'description']:
            if f in data:
                setattr(c, f, (data.get(f) or '').strip())
        if 'logo' in data:
            c.logo = data.get('logo') or ''   # base64 data URL — don't strip
        c.save()
        return JsonResponse({'ok': True, 'company': _company_dict(c)})
    return JsonResponse(_company_dict(c))


@csrf_exempt
def api_doc_systems(request):
    if not _doc_auth(request):
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    if request.method == 'POST':
        try:
            data = json.loads(request.body or b'{}')
        except json.JSONDecodeError:
            data = {}
        company = DocCompany.objects.filter(id=data.get('company')).first()
        name = (data.get('name') or '').strip()
        if not company or not name:
            return JsonResponse({'detail': 'Company and system name required.'}, status=400)
        obj, created = DocSystem.objects.get_or_create(
            company=company, name=name,
            defaults={'description': (data.get('description') or '').strip()},
        )
        return JsonResponse({'id': obj.id, 'name': obj.name}, status=201 if created else 200)
    company_id = request.GET.get('company')
    qs = DocSystem.objects.filter(company_id=company_id) if company_id else DocSystem.objects.all()
    out = [{
        'id': s.id, 'name': s.name, 'description': s.description,
        'company': s.company_id, 'documents': s.documents.count(),
    } for s in qs]
    return JsonResponse({'systems': out})


@csrf_exempt
@require_http_methods(["DELETE"])
def api_doc_system_detail(request, pk):
    if not _doc_auth(request):
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    DocSystem.objects.filter(id=pk).delete()
    return JsonResponse({'ok': True})


@csrf_exempt
def api_doc_documents(request):
    if not _doc_auth(request):
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    if request.method == 'POST':
        system = DocSystem.objects.filter(id=request.POST.get('system')).first()
        f = request.FILES.get('file')
        if not system or not f:
            return JsonResponse({'detail': 'System and file are required.'}, status=400)
        folder_id = request.POST.get('folder')
        folder = DocFolder.objects.filter(id=folder_id, system=system).first() if folder_id else None
        doc = DocDocument.objects.create(
            system=system, folder=folder, name=f.name, file=f, size=f.size,
            content_type=getattr(f, 'content_type', '') or '',
            uploaded_by=request.user.username,
        )
        return JsonResponse({'id': doc.id, 'name': doc.name, 'size': doc.size}, status=201)
    return JsonResponse({'detail': 'Use /api/docs/contents to list.'}, status=400)


def _doc_json(d):
    return {
        'id': d.id, 'name': d.name, 'size': d.size, 'content_type': d.content_type,
        'uploaded_by': d.uploaded_by,
        'uploaded_at': d.uploaded_at.strftime('%b %d, %Y %H:%M'),
    }


def api_doc_contents(request):
    """Folder-tree contents for a system at a given folder (blank = root)."""
    if not _doc_auth(request):
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    system = DocSystem.objects.filter(id=request.GET.get('system')).first()
    if not system:
        return JsonResponse({'detail': 'System not found.'}, status=404)
    folder_id = request.GET.get('folder') or None
    current = DocFolder.objects.filter(id=folder_id, system=system).first() if folder_id else None

    # breadcrumb path from root → current
    path = []
    node = current
    while node is not None:
        path.insert(0, {'id': node.id, 'name': node.name})
        node = node.parent

    subfolders = DocFolder.objects.filter(system=system, parent=current)
    folders = [{
        'id': fo.id, 'name': fo.name,
        'folders': fo.children.count(), 'files': fo.files.count(),
    } for fo in subfolders]
    documents = [_doc_json(d) for d in DocDocument.objects.filter(system=system, folder=current)]

    return JsonResponse({
        'system': {'id': system.id, 'name': system.name},
        'folder': {'id': current.id, 'name': current.name} if current else None,
        'path': path,
        'folders': folders,
        'documents': documents,
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_doc_folders(request):
    if not _doc_auth(request):
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = {}
    system = DocSystem.objects.filter(id=data.get('system')).first()
    name = (data.get('name') or '').strip()
    if not system or not name:
        return JsonResponse({'detail': 'System and folder name required.'}, status=400)
    parent = DocFolder.objects.filter(id=data.get('parent'), system=system).first() if data.get('parent') else None
    obj = DocFolder.objects.create(system=system, parent=parent, name=name)
    return JsonResponse({'id': obj.id, 'name': obj.name}, status=201)


@csrf_exempt
@require_http_methods(["DELETE"])
def api_doc_folder_detail(request, pk):
    if not _doc_auth(request):
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    DocFolder.objects.filter(id=pk).delete()
    return JsonResponse({'ok': True})


@csrf_exempt
@require_http_methods(["DELETE"])
def api_doc_document_detail(request, pk):
    if not _doc_auth(request):
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    doc = DocDocument.objects.filter(id=pk).first()
    if doc:
        try:
            doc.file.delete(save=False)
        except Exception:
            pass
        doc.delete()
    return JsonResponse({'ok': True})


def api_doc_download(request, pk):
    if not _doc_auth(request):
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)
    doc = DocDocument.objects.filter(id=pk).first()
    if not doc:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    from django.http import FileResponse
    return FileResponse(doc.file.open('rb'), as_attachment=True, filename=doc.name)


# ── Servers: live status of the infrastructure (inventory from the Obsidian vault) ──
SERVER_INVENTORY = [
    {
        "name": "Magnum Opus Consultants Old Server", "company": "Magnum Opus Consultants", "ip": "206.189.204.60", "host": "workspace.moc-pty.com", "port": 443,
        "group": "DigitalOcean Cloud", "role": "Original MOC host — Automation Platform, RMAA, LANCorp, MOC Emailing",
        "hostname": "moc-prime", "os": "Ubuntu 24.04.3 LTS", "provider": "DigitalOcean droplet", "netbird_url": None,
        "cpu": "1 vCPU", "ram": "0.96 GB (~287 MB free)", "disk": "24 GB (58% used, 9.9 GB free)",
        "runtimes": ["Python 3.12.3", "Node 20.20.2", "nginx 1.24.0", "PostgreSQL 16.14", "MySQL"],
        "services": ["lancorp-backend", "moc-backend + moc-frontend", "rmaa-backend", "mysql", "postgresql@16-main", "nginx", "Automation Platform gunicorn (:8002)"],
        "databases": ["PostgreSQL automation_platform 302 MB", "MySQL"],
        "domains": ["automation.moc-pty.com", "workspace.moc-pty.com", "landcorp.moc-pty.com", "pulseboard.moc-pty.com", "rmaa.moc-pty.com", "magnumopusmail.moc-pty.com", "fuelrefundinstitute.com"],
        "access": "root via id_ed25519_mocprime", "netbird_ip": None, "lan_ip": None,
        "notes": ["PostgreSQL 5432 is internet-facing — firewall priority.", "Low RAM (~1 GB) with MySQL + Postgres + app backends.", "Original MOC host; workloads also on the Magnum Opus Consultants Applications Server — DNS cut-over pending.", "No application DB backup timer — databases unprotected."],
    },
    {
        "name": "Food Safety Agency Production Server", "company": "Food Safety Agency", "ip": "64.227.19.8", "host": "inspector-app.fsa-pty.co.za", "port": 443,
        "group": "DigitalOcean Cloud", "role": "FSA production — APS, EPVS, Debtor, Mobile",
        "hostname": "ubuntu-s-2vcpu-2gb-nyc1", "os": "Ubuntu 24.04.4 LTS", "provider": "DigitalOcean droplet", "netbird_url": None,
        "cpu": "2 vCPU", "ram": "1.9 GB", "disk": "58 GB (32% used, 40 GB free)",
        "runtimes": ["Python 3.12.3", "Node 20.20.2", "nginx 1.24.0", "PostgreSQL 16.14", "certbot"],
        "services": ["aps-gunicorn (:8001)", "aps-frontend (:3000)", "epvs-django (:8004)", "epvs-node (:5000)", "dms-gunicorn (:8003)", "fsa-mobile-django (:8005)", "nginx", "postgresql@16-main"],
        "databases": ["fsa_inspection 52 MB (APS)", "FSA_Debtors 28 MB (Debtor)", "fsa_mobile 16 MB (Mobile)", "epvs 11 MB (EPVS)"],
        "domains": ["agricultural-production.fsa-pty.co.za", "egg-production-verification.fsa-pty.co.za", "debtor-management.fsa-pty.co.za", "inspector-app.fsa-pty.co.za", "v4-project.moc-pty.com", "fsa-debitor-system.moc-pty.com"],
        "access": "root via id_ed25519_digitalocean", "netbird_ip": "100.108.208.173", "lan_ip": None,
        "notes": ["Daily DB + media backup timers (02:00 / 03:00).", "APS send_weekly_report cron every 20 min."],
    },
    {
        "name": "Magnum Opus Consultants Applications Server", "company": "Magnum Opus Consultants", "ip": "134.209.20.61", "host": "rmaa.moc-pty.com", "port": 443,
        "group": "DigitalOcean Cloud", "role": "New MOC server — RMAA, PulseBoard, MOC Emailing, Fuel Refund",
        "hostname": "Server-one", "os": "Ubuntu 24.04.4 LTS", "provider": "DigitalOcean droplet", "netbird_url": None,
        "cpu": "1 vCPU", "ram": "1.9 GB", "disk": "48 GB (15% used, 41 GB free)",
        "runtimes": ["Python 3.12.3", "Node 20.20.2", "nginx 1.24.0", "PostgreSQL 16.14", "MySQL (3306/33060)"],
        "services": ["rmaa-backend", "pulseboard", "moc-backend + moc-frontend", "fuelrefund", "mysql", "postgresql@16-main", "nginx"],
        "databases": ["PostgreSQL automation_platform 238 MB (migrated copy)", "MySQL"],
        "domains": ["rmaa.moc-pty.com", "pulseboard.moc-pty.com", "magnumopusmail.moc-pty.com", "fuelrefundinstitute.com"],
        "access": "root via id_ed25519 (ssh server-one)", "netbird_ip": "100.108.21.132", "lan_ip": None,
        "notes": ["Migration target for RMAA, PulseBoard, MOC Emailing, Fuel Refund.", "Some DNS still points at the Magnum Opus Consultants Old Server pending cut-over.", "Daily moc-db-backup timer."],
    },
    {
        "name": "Headquarters Hypervisor", "company": "Shared", "ip": "10.0.0.21", "host": "10.0.0.21", "port": 8006,
        "group": "Headquarters Office Servers", "role": "Proxmox VE hypervisor — office LAN, runs 5 VMs",
        "hostname": "proxmox", "os": "Proxmox VE 9.1.5 (kernel 6.17.9)", "provider": "Office LAN (owned hardware)",
        "netbird_url": "https://100.108.29.54:8006",
        "cpu": "40 × Xeon E5-2680 v2 @ 2.80 GHz", "ram": "135 GB (73 GB used)", "disk": "101 GB root (9.4 GB used)",
        "runtimes": ["Proxmox VE 9.1.5"],
        "services": ["local-lvm (lvmthin 32/367 GB)", "local (dir 9/101 GB)", "RiadZ2_pool (ZFS 10.4/22.6 TB)"],
        "databases": [], "domains": [], "access": "Web/API root@pam at https://10.0.0.21:8006 (NetBird: 100.108.29.54)", "netbird_ip": "100.108.29.54", "lan_ip": "10.0.0.21",
        "notes": ["Hosts VMs 101–105.", "No firewall enabled at datacenter, node, or VM level — Firewall Plan pending."],
    },
    {
        "name": "Food Safety Agency Nextcloud Storage", "company": "Food Safety Agency", "ip": "100.108.208.36", "host": "fsacloud.netbird.cloud", "port": 443,
        "group": "Headquarters Office Servers", "role": "FSA Nextcloud — primary backup target",
        "hostname": "fsacloud", "os": "Ubuntu 24.04.4 LTS", "provider": "Proxmox VM 101 (10.0.0.21)",
        "netbird_url": "https://fsacloud.netbird.cloud",
        "cpu": "10 cores", "ram": "32 GB", "disk": "29 GB root (44% used) + 3.6 TB data (26% used)",
        "runtimes": ["Docker Compose", "Nextcloud 30.0.17"],
        "services": ["nextcloud-app-1 (nextcloud:30-apache)", "nginx-proxy-manager-app-1", "nextcloud-db-1 (postgres:16)", "nextcloud-redis-1 (redis:7)"],
        "databases": ["Nextcloud postgres:16 (container)"], "domains": ["fsacloud.netbird.cloud"],
        "access": "Web over NetBird; NPM admin :81; commands via Proxmox guest agent", "netbird_ip": "100.108.208.36", "lan_ip": "10.0.0.22",
        "notes": ["Primary backup target — receives FSA DB + media backups.", "Inode incident fixed 2026-08-06 (root LV grown 14.5 → 29 GB)."],
    },
    {
        "name": "Magnum Opus Consultants Nextcloud Storage", "company": "Magnum Opus Consultants", "ip": "100.108.200.197", "host": "cloud.moc-pty.com", "port": 443,
        "group": "Headquarters Office Servers", "role": "MOC Nextcloud",
        "hostname": "moccloud", "os": "Ubuntu 24.04.4 LTS", "provider": "Proxmox VM 102 (10.0.0.21)",
        "netbird_url": "https://100.108.200.197",
        "cpu": "3 cores", "ram": "8 GB", "disk": "15 GB root (⚠️ 73% used) + 3.6 TB data (1% used)",
        "runtimes": ["Docker Compose", "Nextcloud 30"],
        "services": ["nextcloud-app-1 (nextcloud:30-apache)", "nginx-proxy-manager-app-1", "nextcloud-db-1 (postgres:16)", "nextcloud-redis-1 (redis:7)"],
        "databases": ["Nextcloud postgres:16 (container)"], "domains": ["cloud.moc-pty.com"],
        "access": "Web (LE cert); NPM admin :81; commands via Proxmox guest agent", "netbird_ip": "100.108.200.197", "lan_ip": "10.0.0.23",
        "notes": ["⚠️ Root disk 73% full on a 15 GB disk — grow before it fills."],
    },
    {
        "name": "E-Click Application Server", "company": "E-Click", "ip": None, "host": None, "port": None,
        "group": "Headquarters Office Servers", "role": "E-Click Software (guest agent unresponsive)",
        "hostname": "E-Click-Software", "os": "unknown", "provider": "Proxmox VM 103 (10.0.0.21)", "netbird_url": None,
        "cpu": "2 cores", "ram": "16 GB", "disk": "32 GB",
        "runtimes": [], "services": [], "databases": [], "domains": [],
        "access": "Proxmox console only (guest agent unresponsive)", "netbird_ip": None, "lan_ip": None,
        "notes": ["qemu guest agent does not respond — OS/services/IPs unknown.", "Needs a manual check from the Proxmox console."],
    },
    {
        "name": "Magnum Opus Consultants Development Sandbox", "company": "Magnum Opus Consultants", "ip": "100.108.18.30", "host": "100.108.18.30", "port": 22,
        "group": "Headquarters Office Servers", "role": "Idle MOC dev/demo sandbox (NetBird)",
        "hostname": "moc-devbox", "os": "Ubuntu 24.04.4 LTS", "provider": "Proxmox VM 104 (10.0.0.21)", "netbird_url": None,
        "cpu": "8 cores", "ram": "16 GB", "disk": "250 GB (1% used)",
        "runtimes": [], "services": ["sshd (:22)", "systemd-resolved (:53)"],
        "databases": [], "domains": [],
        "access": "ssh ethan@100.108.18.30 (key id_ed25519, passwordless sudo)", "netbird_ip": "100.108.18.30", "lan_ip": "10.0.0.114",
        "notes": ["Idle — no web/app services running.", "Sandbox for MOC app development / demo copies."],
    },
    {
        "name": "Food Safety Agency Demo & Sandbox", "company": "Food Safety Agency", "ip": "100.108.223.27", "host": "aps-demo.fsa-pty.co.za", "port": 443,
        "group": "Headquarters Office Servers", "role": "FSA demo environment (NetBird only)",
        "hostname": "food-safety-agency-devbox", "os": "Ubuntu 24.04.4 LTS", "provider": "Proxmox VM 105 (10.0.0.21)", "netbird_url": None,
        "cpu": "8 cores", "ram": "16 GB", "disk": "250 GB (2% used, 237 GB free)",
        "runtimes": ["nginx 1.24", "PostgreSQL 16", "Python 3.12", "Node 20.20.2", "certbot"],
        "services": ["aps-demo-gunicorn + aps-demo-frontend (:8001/:3000)", "epvs-demo-django + epvs-demo-node (:8004/:5000)", "dms-demo-gunicorn (:8003)", "nginx", "postgresql@16-main"],
        "databases": ["PostgreSQL 16 (demo apps)"],
        "domains": ["aps-demo.fsa-pty.co.za", "epvs-demo.fsa-pty.co.za", "debtor-demo.fsa-pty.co.za"],
        "access": "ssh ethan@100.108.223.27 (key id_ed25519); jump host to Proxmox when off-LAN", "netbird_ip": "100.108.223.27", "lan_ip": "10.0.0.115",
        "notes": ["Runs the three internal demo apps.", "Wildcard TLS *.fsa-pty.co.za (DNS-01, manual renew).", "Reachable on NetBird only."],
    },
]


# User-editable metadata only. Hardware/system/database fields are scanned from the server.
_SERVER_FIELDS = ['name', 'company', 'group', 'ip', 'host', 'port', 'hostname', 'provider',
                  'access', 'netbird_ip', 'lan_ip', 'netbird_url',
                  'ssh_user', 'ssh_ip', 'ssh_key', 'password', 'domains', 'notes', 'order']


def _split_lines(t):
    return [ln.strip() for ln in (t or '').split('\n') if ln.strip()]


def _server_dict(rec):
    d = {
        'id': rec.id, 'name': rec.name, 'company': rec.company, 'group': rec.group,
        'ip': rec.ip or None, 'host': rec.host, 'port': rec.port,
        'hostname': rec.hostname, 'os': rec.os, 'provider': rec.provider,
        'cpu': rec.cpu, 'ram': rec.ram, 'disk': rec.disk, 'access': rec.access,
        'netbird_ip': rec.netbird_ip or None, 'lan_ip': rec.lan_ip or None, 'netbird_url': rec.netbird_url or None,
        'ssh_user': rec.ssh_user, 'ssh_ip': rec.ssh_ip, 'ssh_key': rec.ssh_key, 'password': rec.password,
        'scanned_at': rec.scanned_at.strftime('%b %d, %Y %H:%M') if rec.scanned_at else None,
        'runtimes': _split_lines(rec.runtimes), 'services': _split_lines(rec.services),
        'databases': _split_lines(rec.databases), 'domains': _split_lines(rec.domains),
        'notes': _split_lines(rec.notes),
    }
    d['ssh_command'] = (f"ssh -i ~/.ssh/{rec.ssh_key} {rec.ssh_user}@{rec.ssh_ip}"
                        if rec.ssh_user and rec.ssh_ip and rec.ssh_key else None)
    return d


def _apply_fields(rec, data):
    for f in _SERVER_FIELDS:
        if f in data:
            if f == 'port':
                rec.port = int(data[f]) if str(data[f] or '').strip() else None
            elif f == 'order':
                rec.order = int(data[f] or 0)
            else:
                setattr(rec, f, data[f] or '')


def api_servers(request):
    err = _require_module(request, 'servers')
    if err:
        return err
    import socket
    import time
    from concurrent.futures import ThreadPoolExecutor
    records = list(ServerRecord.objects.all())

    def check(rec):
        d = _server_dict(rec)
        d['target'] = f"{rec.host}:{rec.port}" if rec.host and rec.port else None
        if not rec.host or not rec.port:
            d['status'] = 'unknown'
            d['latency_ms'] = None
            return d
        start = time.time()
        try:
            with socket.create_connection((rec.host, rec.port), timeout=2.5):
                d['status'] = 'up'
                d['latency_ms'] = int((time.time() - start) * 1000)
        except Exception:
            d['status'] = 'down'
            d['latency_ms'] = None
        return d

    results = []
    if records:
        with ThreadPoolExecutor(max_workers=len(records)) as ex:
            results = list(ex.map(check, records))
    up = sum(1 for r in results if r['status'] == 'up')
    down = sum(1 for r in results if r['status'] == 'down')
    return JsonResponse({'servers': results, 'up': up, 'down': down, 'total': len(results)})


@csrf_exempt
@require_http_methods(["POST"])
def api_server_create(request):
    err = _require_module(request, 'servers')
    if err:
        return err
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = {}
    rec = ServerRecord(order=ServerRecord.objects.count())
    _apply_fields(rec, data)
    if not rec.name:
        rec.name = 'New Server'
    rec.save()
    return JsonResponse({'id': rec.id}, status=201)


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_server_update(request, pk):
    err = _require_module(request, 'servers')
    if err:
        return err
    rec = ServerRecord.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    try:
        data = json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        data = {}
    _apply_fields(rec, data)
    rec.save()
    return JsonResponse({'ok': True})


@csrf_exempt
@require_http_methods(["DELETE"])
def api_server_delete(request, pk):
    err = _require_module(request, 'servers')
    if err:
        return err
    ServerRecord.objects.filter(id=pk).delete()
    return JsonResponse({'ok': True})


@csrf_exempt
@require_http_methods(["POST"])
def api_server_scan(request, pk):
    """SSH into a server and auto-detect its hardware, runtimes, services and databases."""
    err = _require_module(request, 'servers')
    if err:
        return err
    rec = ServerRecord.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'ok': False, 'detail': 'Not found.'}, status=404)
    if not (rec.ssh_user and rec.ssh_ip and rec.ssh_key):
        return JsonResponse({'ok': False, 'detail': 'No SSH access configured — add SSH user, IP and key first.'}, status=200)

    import subprocess
    ssh_bin = r'C:\Program Files\Git\usr\bin\ssh.exe'
    if not os.path.exists(ssh_bin):
        ssh_bin = 'ssh'
    keypath = os.path.join(os.path.expanduser('~'), '.ssh', rec.ssh_key)
    remote = (
        'echo @@OS; ( . /etc/os-release 2>/dev/null; echo "$PRETTY_NAME" ); '
        'echo @@CORES; nproc; '
        'echo @@MODEL; grep -m1 "model name" /proc/cpuinfo | cut -d: -f2-; '
        'echo @@RAM; free -m 2>/dev/null | grep -i "^Mem:"; '
        'echo @@DISK; df -h / | tail -1; '
        'echo @@RUN; python3 --version 2>/dev/null; node --version 2>/dev/null; nginx -v 2>&1; psql --version 2>/dev/null; mysql --version 2>/dev/null; docker --version 2>/dev/null; '
        'echo @@SVC; systemctl list-units --type=service --state=running --no-legend --no-pager 2>/dev/null; '
        'echo @@DB; sudo -n -u postgres psql -tAc "SELECT datname FROM pg_database WHERE datistemplate=false" 2>/dev/null; '
        'echo @@END'
    )
    try:
        p = subprocess.run(
            [ssh_bin, '-i', keypath, '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
             '-o', 'ConnectTimeout=6', '-o', 'StrictHostKeyChecking=no', '-o', 'UserKnownHostsFile=/dev/null',
             f"{rec.ssh_user}@{rec.ssh_ip}", remote],
            capture_output=True, text=True, timeout=25,
        )
    except Exception:
        return JsonResponse({'ok': False, 'detail': 'SSH scan failed (host not reachable / no key).'}, status=200)

    sec, cur = {}, None
    for line in p.stdout.splitlines():
        s = line.strip()
        if s.startswith('@@'):
            cur = s[2:].strip()
            sec[cur] = []
        elif cur is not None and s:
            sec[cur].append(s)

    def first(k):
        v = sec.get(k) or []
        return v[0] if v else ''

    if not first('OS') and not first('CORES'):
        return JsonResponse({'ok': False, 'detail': 'Scan returned no data (SSH auth or command failed).'}, status=200)

    cores, model = first('CORES'), first('MODEL').strip()
    rec.os = first('OS')
    rec.cpu = (f"{cores} cores" if cores else '') + (f" \u00b7 {model}" if model else '')
    ramline = first('RAM').split()
    if len(ramline) >= 3 and ramline[0].lower().startswith('mem'):
        try:
            rec.ram = f"{int(ramline[1]) / 1024:.1f} GB ({int(ramline[2]) / 1024:.1f} GB used)"
        except Exception:
            pass
    dl = first('DISK').split()
    if len(dl) >= 5:
        rec.disk = f"{dl[1]} ({dl[4]} used, {dl[3]} free)"

    runtimes = []
    for r in sec.get('RUN', []):
        if 'not found' in r or 'command not' in r:
            continue
        runtimes.append(r.replace('nginx version: ', '').strip())
    rec.runtimes = '\n'.join(runtimes)

    skip = ('systemd', 'dbus', 'cron', 'ssh', 'getty', 'rsyslog', 'polkit', 'user@', 'accounts',
            'unattended', 'multipathd', 'snapd', 'udisks', 'modemmanager', 'networkd', 'resolved',
            'timesyncd', 'logind', 'irqbalance', 'packagekit', 'serial-getty')
    services = []
    for line in sec.get('SVC', []):
        name = line.split()[0].replace('.service', '') if line.split() else ''
        if name and not any(x in name for x in skip):
            services.append(name)
    rec.services = '\n'.join(services[:16])

    rec.databases = '\n'.join(f"PostgreSQL: {d}" for d in sec.get('DB', []) if d and d != 'postgres')

    from django.utils import timezone as _tz
    rec.scanned_at = _tz.now()
    rec.save()
    return JsonResponse({'ok': True})


# Estimated monthly cost per server (USD). Only cloud droplets bill; owned hardware = 0.
COST_MONTHLY = {
    "MOC-Prime": 6.0,
    "FSA-Production": 18.0,
    "MOC-ServerOne": 12.0,
    "Proxmox-Host": 0.0,       # owned hardware — no cloud cost
    "FSA-Nextcloud": 0.0,      # runs on the Proxmox host
    "MOC-Nextcloud": 0.0,
    "EClick-Software": 0.0,
    "MOC-DevBox": 0.0,
    "FSA-Sandbox": 0.0,
}

# SSH access for live metrics — keyed by stable hostname (survives display renames).
SSH_CONF = {
    "moc-prime": {"user": "root", "ip": "206.189.204.60", "key": "id_ed25519_mocprime"},
    "ubuntu-s-2vcpu-2gb-nyc1": {"user": "root", "ip": "64.227.19.8", "key": "id_ed25519_digitalocean"},
    "Server-one": {"user": "root", "ip": "134.209.20.61", "key": "id_ed25519"},
    "moc-devbox": {"user": "ethan", "ip": "100.108.18.30", "key": "id_ed25519"},
    "food-safety-agency-devbox": {"user": "ethan", "ip": "100.108.223.27", "key": "id_ed25519"},
}


def api_server_metrics(request):
    """Live hardware metrics for one server via SSH, using its stored SSH access."""
    err = _require_module(request, 'servers')
    if err:
        return err
    rec = ServerRecord.objects.filter(id=request.GET.get('id')).first()
    if not rec:
        return JsonResponse({'available': False, 'detail': 'Server not found.'})
    if not (rec.ssh_user and rec.ssh_ip and rec.ssh_key):
        return JsonResponse({'available': False, 'detail': 'No SSH access configured for live metrics.'})

    import subprocess
    ssh_bin = r'C:\Program Files\Git\usr\bin\ssh.exe'
    if not os.path.exists(ssh_bin):
        ssh_bin = 'ssh'
    key = os.path.join(os.path.expanduser('~'), '.ssh', rec.ssh_key)
    remote = 'nproc; head -1 /proc/loadavg; free -m | sed -n "2p"; df -m / | tail -1; uptime -p'
    try:
        p = subprocess.run(
            [ssh_bin, '-i', key, '-o', 'IdentitiesOnly=yes', '-o', 'BatchMode=yes',
             '-o', 'ConnectTimeout=5', '-o', 'StrictHostKeyChecking=no',
             '-o', 'UserKnownHostsFile=/dev/null',
             f"{rec.ssh_user}@{rec.ssh_ip}", remote],
            capture_output=True, text=True, timeout=12,
        )
        lines = [l for l in p.stdout.splitlines() if l.strip()]
        if len(lines) < 4:
            return JsonResponse({'available': False, 'detail': 'SSH metrics unavailable'})
        cores = int(lines[0].strip())
        load = float(lines[1].split()[0])
        mem = lines[2].split()
        mem_total, mem_used = int(mem[1]), int(mem[2])
        disk = lines[3].split()
        disk_total_mb, disk_used_mb = int(disk[1]), int(disk[2])
        uptime = lines[4] if len(lines) > 4 else None
        return JsonResponse({
            'available': True, 'source': 'ssh',
            'cpu_percent': round(min(100.0, load / cores * 100), 1) if cores else None,
            'cores': cores, 'load': load,
            'mem_used_mb': mem_used, 'mem_total_mb': mem_total,
            'disk_used_gb': round(disk_used_mb / 1024, 1), 'disk_total_gb': round(disk_total_mb / 1024, 1),
            'uptime': uptime,
        })
    except Exception:
        return JsonResponse({'available': False, 'detail': 'SSH metrics unavailable (host not reachable / no key).'})
