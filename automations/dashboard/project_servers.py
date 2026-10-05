"""Project server endpoints: list, create, power and delete a project's VM.

Anyone with Projects access can see a project's servers; only administrators
can create, power or delete them, since each one takes memory and disk from
the host the client Nextclouds run on.
"""
import json
import logging
import os
import secrets

from django.core import signing
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import activity, github_api as gh, proxmox
from .project_credentials import save_server_login
from .models import ProjectMeta, ProjectServer, TaskActivity
from .views import _require_module

logger = logging.getLogger(__name__)

# Console passes: signed by Sentinel, checked by the console relay
# (management/commands/console_proxy.py). Short-lived and single-use.
CONSOLE_SALT = 'project-server-console'
CONSOLE_PASS_AGE = 60


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _is_admin(request):
    return request.user.is_authenticated and request.user.is_superuser


def _server_dict(s):
    return {
        'id': s.id, 'name': s.name, 'vmid': s.vmid, 'os': s.os,
        'cores': s.cores, 'memory_mb': s.memory_mb, 'disk_gb': s.disk_gb,
        'ip': s.ip, 'username': s.username,
        'status': s.status, 'status_display': s.get_status_display(),
        'step': s.step, 'error': s.error,
        'created_by': (s.created_by.get_full_name() or s.created_by.username)
                      if s.created_by_id else '',
        'created_at': s.created_at.isoformat(),
    }


def _options(request):
    return {
        'configured': proxmox.is_configured(),
        'can_manage': _is_admin(request),
        'size': proxmox.SIZE,
        'os': proxmox.OS_LABEL,
        'choices': {'cores': proxmox.CORE_CHOICES, 'memory_mb': proxmox.MEMORY_CHOICES,
                    'max_disk_gb': proxmox.MAX_DISK_GB},
        # The New project dialog offers a repository alongside the server.
        'github': {'configured': gh.is_configured(), 'owner': os.getenv('GITHUB_OWNER', '')},
    }


@require_http_methods(["GET"])
def api_server_options(request):
    """What the New project dialog needs to offer a server."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    return JsonResponse(_options(request))


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_project_servers(request, name):
    """A project's servers (GET), or create one (POST, administrators)."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    project = ProjectMeta.objects.filter(name=name).first()
    if project is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    if request.method == 'GET':
        rows = ProjectServer.objects.filter(project_name=name).exclude(status='deleted')
        return JsonResponse({**_options(request),
                             'servers': [_server_dict(s) for s in rows]})

    if not _is_admin(request):
        return JsonResponse({'detail': 'Only administrators can create servers.'}, status=403)
    if not proxmox.is_configured():
        return JsonResponse({'detail': 'Proxmox is not connected yet.'}, status=400)
    cfg = proxmox.config()
    if cfg['ip_pool'] and not cfg['gateway']:
        return JsonResponse({'detail': 'PROXMOX_IP_POOL is set without PROXMOX_GATEWAY.'},
                            status=400)

    data = _body(request)
    problem = proxmox.check_public_keys(str(data.get('ssh_key') or ''))
    if problem:
        return JsonResponse({'detail': problem}, status=400)
    live = ProjectServer.objects.exclude(status='deleted')
    try:
        client = proxmox.Client(cfg)
        proxmox.check_capacity(client)
        vmid = proxmox.pick_vmid(client, reserved=live.exclude(vmid=None)
                                 .values_list('vmid', flat=True))
    except proxmox.ProxmoxError as e:
        return JsonResponse({'detail': str(e)}, status=400)

    ip = ''
    if cfg['ip_pool']:
        ip = proxmox.next_free_ip(cfg['ip_pool'], set(live.values_list('ip', flat=True)))
        if not ip:
            return JsonResponse({'detail': f'No free address left in {cfg["ip_pool"]}.'},
                                status=400)

    server = ProjectServer.objects.create(
        project_name=project.name,
        name=proxmox.hostname_for(project.name, set(live.values_list('name', flat=True))),
        vmid=vmid, os=proxmox.OS_LABEL, ip=ip, username=cfg['user'],
        created_by=request.user, **proxmox.SIZE)
    password = proxmox.new_password()
    proxmox.in_background(proxmox.provision, server.id, password,
                          str(data.get('ssh_key') or '').strip())

    TaskActivity.objects.create(project_name=project.name, user=request.user,
                                kind='edited', field='server', new_value=server.name)
    activity.record(request, 'created', 'server', obj=server, label=server.name,
                    detail=f'Proxmox VM {vmid} for {project.name}', project=project.name)
    # Kept, encrypted, in the project's credentials when the vault is set up;
    # otherwise this response is the only place the password ever appears.
    saved = save_server_login(server, password, request.user)
    return JsonResponse({'server': _server_dict(server), 'password': password,
                         'saved_to_credentials': saved}, status=201)


@csrf_exempt
@require_http_methods(["POST"])
def api_project_server_action(request, name, pk):
    """refresh, start, stop, reboot or delete one of the project's servers."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    server = ProjectServer.objects.filter(id=pk, project_name=name).exclude(status='deleted').first()
    if server is None:
        return JsonResponse({'detail': 'No such server on this project.'}, status=404)
    action = str(_body(request).get('action') or '')
    if action != 'refresh' and not _is_admin(request):
        return JsonResponse({'detail': 'Only administrators can change servers.'}, status=403)
    if action not in ('refresh', 'start', 'stop', 'reboot', 'delete'):
        return JsonResponse({'detail': 'Unknown action.'}, status=400)
    if server.status in ('provisioning', 'deleting') and action != 'refresh':
        return JsonResponse({'detail': 'Wait for it to finish what it is doing.'}, status=409)

    try:
        if action == 'refresh':
            proxmox.refresh(server)
        elif action == 'delete':
            server.status, server.step = 'deleting', 'Starting'
            server.save(update_fields=['status', 'step', 'updated_at'])
            proxmox.in_background(proxmox.destroy, server.id)
            TaskActivity.objects.create(project_name=name, user=request.user, kind='edited',
                                        field='server', old_value=server.name, new_value='deleted')
            activity.record(request, 'deleted', 'server', obj=server, label=server.name,
                            detail=f'Proxmox VM {server.vmid}', project=name)
        else:
            proxmox.power(server, action)
            activity.record(request, 'updated', 'server', obj=server, label=server.name,
                            detail=action, project=name)
    except proxmox.ProxmoxError as e:
        return JsonResponse({'detail': str(e)}, status=400)
    server.refresh_from_db()
    return JsonResponse({'server': _server_dict(server)})


@csrf_exempt
@require_http_methods(["POST"])
def api_project_server_resize(request, name, pk):
    """Change a server's CPU, memory and disk (administrators)."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    if not _is_admin(request):
        return JsonResponse({'detail': 'Only administrators can change servers.'}, status=403)
    server = ProjectServer.objects.filter(id=pk, project_name=name,
                                          status__in=('running', 'stopped')).first()
    if server is None:
        return JsonResponse({'detail': 'The server must be running or stopped to change it.'},
                            status=409)
    data = _body(request)
    try:
        cores = int(data.get('cores', server.cores))
        memory_mb = int(data.get('memory_mb', server.memory_mb))
        disk_gb = int(data.get('disk_gb', server.disk_gb))
    except (TypeError, ValueError):
        return JsonResponse({'detail': 'CPU, memory and disk must be whole numbers.'}, status=400)
    before = f'{server.cores} CPU, {server.memory_mb // 1024} GB, {server.disk_gb} GB disk'
    try:
        restart = proxmox.resize(server, cores, memory_mb, disk_gb)
    except proxmox.ProxmoxError as e:
        return JsonResponse({'detail': str(e)}, status=400)
    server.cores, server.memory_mb, server.disk_gb = cores, memory_mb, disk_gb
    server.save(update_fields=['cores', 'memory_mb', 'disk_gb', 'updated_at'])
    after = f'{cores} CPU, {memory_mb // 1024} GB, {disk_gb} GB disk'
    if before != after:
        TaskActivity.objects.create(project_name=name, user=request.user, kind='edited',
                                    field=f'server {server.name} size',
                                    old_value=before, new_value=after)
        activity.record(request, 'updated', 'server', obj=server, label=server.name,
                        detail=f'resized to {after}', project=name)
    return JsonResponse({'server': _server_dict(server), 'restart_needed': restart})


@csrf_exempt
@require_http_methods(["POST"])
def api_project_server_console(request, name, pk):
    """A one-minute, one-use pass to open this server's console (administrators)."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    if not _is_admin(request):
        return JsonResponse({'detail': 'Only administrators can open a server console.'}, status=403)
    server = ProjectServer.objects.filter(id=pk, project_name=name, status='running').first()
    if server is None:
        return JsonResponse({'detail': 'The server is not running.'}, status=409)
    grant = signing.dumps({'s': server.id, 'u': request.user.id, 'n': secrets.token_hex(8)},
                          salt=CONSOLE_SALT)
    base = os.getenv('CONSOLE_PROXY_URL', 'ws://localhost:8010').rstrip('/')
    activity.record(request, 'opened', 'server console', obj=server, label=server.name,
                    project=name)
    return JsonResponse({'url': f'{base}/console?pass={grant}'})


@require_http_methods(["GET"])
def api_project_server_stats(request, name, pk):
    """What the server is doing right now: CPU, memory, uptime, traffic."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    server = ProjectServer.objects.filter(id=pk, project_name=name).exclude(status='deleted').first()
    if server is None or not server.vmid:
        return JsonResponse({'detail': 'No such server on this project.'}, status=404)
    try:
        client = proxmox.Client()
        if not proxmox._own_vm(client, server):
            return JsonResponse({'detail': 'That VM is not one Sentinel made.'}, status=409)
        st = client.vm_status(server.vmid)
    except proxmox.ProxmoxError as e:
        return JsonResponse({'detail': str(e)}, status=400)
    return JsonResponse({
        'status': st.get('status'),
        'cpu_percent': round((st.get('cpu') or 0) * 100, 1),
        'cpus': st.get('cpus'),
        'mem_used': st.get('mem'), 'mem_total': st.get('maxmem'),
        'uptime': st.get('uptime'),
        'net_in': st.get('netin'), 'net_out': st.get('netout'),
        'disk_total': st.get('maxdisk'),
    })
