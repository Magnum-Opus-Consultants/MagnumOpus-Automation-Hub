"""Project credentials: list, add, change, remove and reveal.

The list never carries a secret. Revealing one is a separate call, open to
administrators only and written to the activity log, so there is a record of
who looked at which password and when. Adding, changing and removing are
administrators only too; secret values never appear in any log.
"""
import json

from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import activity, vault
from .models import ProjectCredential, ProjectMeta, TaskActivity
from .views import _require_module

KINDS = dict(ProjectCredential.KIND_CHOICES)


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _is_admin(request):
    return request.user.is_authenticated and request.user.is_superuser


def _dict(c):
    return {
        'id': c.id, 'kind': c.kind, 'kind_display': c.get_kind_display(),
        'label': c.label, 'username': c.username, 'location': c.location,
        'notes': c.notes, 'has_secret': bool(c.secret_encrypted),
        'server': c.server.name if c.server_id else '',
        'updated_at': c.updated_at.isoformat(),
        'updated_by': ((c.updated_by.get_full_name() or c.updated_by.username)
                       if c.updated_by_id else ''),
    }


def _note(request, project, old, new):
    TaskActivity.objects.create(project_name=project, user=request.user, kind='edited',
                                field='credential', old_value=old[:300], new_value=new[:300])


def save_server_login(server, password, user=None):
    """Keep a new server's login with its project, if the vault is set up."""
    if not vault.is_ready():
        return False
    ProjectCredential.objects.create(
        project_name=server.project_name, kind='server', server=server,
        label=f'Server {server.name}', username=server.username,
        secret_encrypted=vault.seal(password),
        location=f'ssh {server.username}@{server.ip}' if server.ip else '',
        notes=f'Proxmox VM {server.vmid}. Saved when the server was created.',
        created_by=user, updated_by=user)
    return True


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_project_credentials(request, name):
    """A project's credentials without their secrets (GET), or add one (POST)."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    if not ProjectMeta.objects.filter(name=name).exists():
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    if request.method == 'GET':
        rows = ProjectCredential.objects.filter(project_name=name).select_related(
            'server', 'updated_by')
        return JsonResponse({
            'vault_ready': vault.is_ready(), 'can_manage': _is_admin(request),
            'kinds': [{'value': k, 'label': v} for k, v in KINDS.items()],
            'credentials': [_dict(c) for c in rows],
        })

    if not _is_admin(request):
        return JsonResponse({'detail': 'Only administrators can add credentials.'}, status=403)
    data = _body(request)
    label = (data.get('label') or '').strip()[:200]
    if not label:
        return JsonResponse({'detail': 'Give it a name.'}, status=400)
    kind = data.get('kind') if data.get('kind') in KINDS else 'other'
    try:
        sealed = vault.seal(str(data.get('secret') or ''))
    except vault.VaultError as e:
        return JsonResponse({'detail': str(e)}, status=400)
    c = ProjectCredential.objects.create(
        project_name=name, kind=kind, label=label,
        username=(data.get('username') or '').strip()[:200],
        location=(data.get('location') or '').strip()[:500],
        notes=(data.get('notes') or '').strip()[:4000],
        secret_encrypted=sealed, created_by=request.user, updated_by=request.user)
    _note(request, name, '', f'added {label}')
    activity.record(request, 'created', 'credential', obj=c, label=label, project=name)
    return JsonResponse({'credential': _dict(c)}, status=201)


def _get(request, name, pk):
    err = _require_module(request, 'tasks')
    if err:
        return None, err
    if not _is_admin(request):
        return None, JsonResponse({'detail': 'Only administrators can do that.'}, status=403)
    c = ProjectCredential.objects.filter(id=pk, project_name=name).first()
    if c is None:
        return None, JsonResponse({'detail': 'No such credential on this project.'}, status=404)
    return c, None


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_project_credential_update(request, name, pk):
    """Change a credential. A blank secret leaves the stored one as it is."""
    c, err = _get(request, name, pk)
    if err:
        return err
    data = _body(request)
    if 'label' in data:
        label = (data.get('label') or '').strip()[:200]
        if not label:
            return JsonResponse({'detail': 'Give it a name.'}, status=400)
        c.label = label
    if data.get('kind') in KINDS:
        c.kind = data['kind']
    for field, cap in (('username', 200), ('location', 500), ('notes', 4000)):
        if field in data:
            setattr(c, field, (data.get(field) or '').strip()[:cap])
    if data.get('secret'):
        try:
            c.secret_encrypted = vault.seal(str(data['secret']))
        except vault.VaultError as e:
            return JsonResponse({'detail': str(e)}, status=400)
    c.updated_by = request.user
    c.save()
    _note(request, name, '', f'changed {c.label}' + (' (new secret)' if data.get('secret') else ''))
    return JsonResponse({'credential': _dict(c)})


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_project_credential_delete(request, name, pk):
    c, err = _get(request, name, pk)
    if err:
        return err
    label = c.label
    c.delete()
    _note(request, name, label, 'removed')
    activity.record(request, 'deleted', 'credential', object_id=pk, label=label, project=name)
    return JsonResponse({'ok': True})


@csrf_exempt
@require_http_methods(["POST"])
def api_project_credential_reveal(request, name, pk):
    """The secret itself, for an administrator, with a record that they looked."""
    c, err = _get(request, name, pk)
    if err:
        return err
    try:
        secret = vault.unseal(c.secret_encrypted)
    except vault.VaultError as e:
        return JsonResponse({'detail': str(e)}, status=400)
    activity.record(request, 'viewed', 'credential', obj=c, label=c.label, project=name)
    return JsonResponse({'secret': secret})
