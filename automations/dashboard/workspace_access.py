"""Workspace membership: who can see what, and telling them they were added.

Access is granted per workspace and inherited by everything inside it. A
superuser bypasses membership entirely - otherwise the first workspace anyone
created would lock its own author out.
"""
import json
import logging
from urllib.parse import quote

from django.contrib.auth.models import User
from django.http import JsonResponse
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import email_layout as el
from .models import Workspace, WorkspaceMember, ProjectMeta, ProjectTask
from .views import _require_module, _graph_send_simple

logger = logging.getLogger(__name__)

_ROLES = [c[0] for c in WorkspaceMember.ROLE_CHOICES]


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _base_url():
    from django.conf import settings
    return (getattr(settings, 'PUBLIC_BASE_URL', '')
            or 'https://workspace.moc-pty.com').rstrip('/')


def visible_workspaces(user):
    """Workspaces this user may see. Superusers see all of them."""
    if user.is_superuser:
        return Workspace.objects.all()
    return Workspace.objects.filter(members__user=user).distinct()


def _member_dict(m):
    return {
        'id': m.id,
        'user_id': m.user_id,
        'username': m.user.username,
        'full_name': (m.user.get_full_name() or '').strip(),
        'email': m.user.email,
        'role': m.role,
        'role_display': m.get_role_display(),
        'added_at': m.added_at.isoformat() if m.added_at else None,
        'notified': m.notified_at is not None,
        'added_by': m.added_by.username if m.added_by else '',
    }


# ══════════════════════════════════════════════════════════════════════════════
# Read
# ══════════════════════════════════════════════════════════════════════════════

def api_workspace_members(request):
    """Members of one workspace, or of every workspace when none is named."""
    err = _require_module(request, 'tasks')
    if err:
        return err

    name = (request.GET.get('workspace') or '').strip()
    qs = WorkspaceMember.objects.select_related('user', 'workspace', 'added_by')
    if name:
        ws = Workspace.objects.filter(name=name).first()
        if ws is None:
            return JsonResponse({'detail': f'No workspace named "{name}".'}, status=404)
        qs = qs.filter(workspace=ws)

    grouped = {}
    for m in qs:
        grouped.setdefault(m.workspace.name, []).append(_member_dict(m))

    # Everyone who could be added, so the picker needs no second call.
    people = [
        {'id': u.id, 'username': u.username,
         'full_name': (u.get_full_name() or '').strip(), 'email': u.email,
         'is_superuser': u.is_superuser}
        for u in User.objects.filter(is_active=True).order_by('username')
    ]
    return JsonResponse({
        'members': grouped,
        'users': people,
        'roles': list(WorkspaceMember.ROLE_CHOICES),
    })


def api_my_access(request):
    """What the caller can reach - used to gate the UI."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    user = request.user
    rows = []
    for m in WorkspaceMember.objects.filter(user=user).select_related('workspace'):
        rows.append({'workspace': m.workspace.name, 'role': m.role})
    return JsonResponse({
        'is_superuser': user.is_superuser,
        'sees_everything': user.is_superuser,
        'workspaces': rows,
    })


# ══════════════════════════════════════════════════════════════════════════════
# Write
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_http_methods(["POST"])
def api_workspace_member_add(request):
    """Grant a user access to a workspace and email them about it."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    data = _body(request)

    ws = Workspace.objects.filter(name=(data.get('workspace') or '').strip()).first()
    if ws is None:
        return JsonResponse({'detail': 'Unknown workspace.'}, status=404)

    ident = data.get('user') or data.get('username') or data.get('user_id')
    user = None
    if isinstance(ident, int) or (isinstance(ident, str) and ident.isdigit()):
        user = User.objects.filter(pk=int(ident)).first()
    elif isinstance(ident, str) and ident.strip():
        ident = ident.strip()
        user = (User.objects.filter(username__iexact=ident).first()
                or User.objects.filter(email__iexact=ident).first())
    if user is None:
        return JsonResponse({'detail': 'Unknown user.'}, status=404)

    role = (data.get('role') or 'member').strip()
    if role not in _ROLES:
        return JsonResponse(
            {'detail': 'role must be one of: ' + ', '.join(_ROLES) + '.'}, status=400)

    m, created = WorkspaceMember.objects.get_or_create(
        workspace=ws, user=user,
        defaults={'role': role, 'added_by': request.user},
    )
    if not created and m.role != role:
        m.role = role
        m.save(update_fields=['role'])

    # Only tell them the first time, unless a resend is asked for: re-running
    # this to change a role should not re-announce it.
    notified = False
    if (created or data.get('notify')) and user.email:
        ok, msg = notify_added(m, request.user)
        notified = ok
        if not ok:
            logger.error('[workspace-access] notify %s failed: %s', user.username, msg)

    return JsonResponse(
        {**_member_dict(m), 'created': created, 'notified': notified,
         'no_email_on_file': not bool(user.email)},
        status=201 if created else 200)


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_workspace_member_remove(request):
    err = _require_module(request, 'tasks')
    if err:
        return err
    data = _body(request)
    ws_name = (data.get('workspace') or '').strip()
    ident = str(data.get('user') or data.get('username') or data.get('user_id') or '').strip()

    qs = WorkspaceMember.objects.filter(workspace__name=ws_name)
    if ident.isdigit():
        qs = qs.filter(user_id=int(ident))
    else:
        qs = qs.filter(user__username__iexact=ident)
    n, _ = qs.delete()
    if n == 0:
        return JsonResponse({'detail': 'That user is not a member of this workspace.'},
                            status=404)
    return JsonResponse({'ok': True, 'removed': n})


# ══════════════════════════════════════════════════════════════════════════════
# Email
# ══════════════════════════════════════════════════════════════════════════════

def notify_added(member, actor=None):
    """Tell someone they now have access, and to what."""
    ws = member.workspace
    # Percent-encode the name: a workspace called "R&D core" would otherwise
    # truncate the query string, and "<" would land raw in the href.
    link = f'{_base_url()}/tasks?workspace={quote(ws.name, safe="")}'

    projects = list(
        ProjectMeta.objects.filter(workspace=ws).values_list('name', flat=True))
    if ws.is_default:
        # The default workspace also holds every project nobody filed elsewhere.
        filed = set(ProjectMeta.objects.exclude(workspace=None)
                    .exclude(workspace=ws).values_list('name', flat=True))
        for name in ProjectTask.objects.values_list('project_name', flat=True).distinct():
            if name and name not in filed and name not in projects:
                projects.append(name)
    projects = sorted(p for p in projects if p)

    who = (actor.get_full_name() or actor.username) if actor else ''
    name = (member.user.get_full_name() or member.user.username).strip()
    blurb = {
        'viewer': 'view the work in it',
        'member': 'create and edit tasks in it',
        'manager': 'manage its projects, lists and members',
    }.get(member.role, 'work in it')

    blocks = [
        el.heading(f'You now have access to {ws.name}',
                   f'Added{" by " + who if who else ""} as a {member.get_role_display()}'),
        el.para(f'Hi {name},'),
        el.para(f'You have been added to the {ws.name} workspace on Sentinel. '
                f'As a {member.get_role_display()} you can {blurb}.'),
    ]
    if projects:
        blocks.append(el.para(f'It holds {len(projects)} '
                              f'project{"" if len(projects) == 1 else "s"}:'))
        blocks.append(el.bullet_list(projects[:25]))
        if len(projects) > 25:
            blocks.append(el.para(f'…and {len(projects) - 25} more.', muted=True, size=13))
    else:
        blocks.append(el.para('It has no projects in it yet.', muted=True, size=13))

    blocks.append(el.button('Open the workspace', link))

    html = el.render(
        f'You have been added to {ws.name}', blocks,
        preheader=f'{member.get_role_display()} access to the {ws.name} workspace.',
        footer_note='If you were not expecting this, reply to this email and we will look into it.',
    )

    holds = (('It holds:\n' + '\n'.join(f'- {p}' for p in projects[:25]) + '\n\n')
             if projects else 'It has no projects in it yet.\n\n')
    text = (f'Hi {name},\n\n'
            f'You have been added to the {ws.name} workspace on Sentinel as a '
            f'{member.get_role_display()}. You can {blurb}.\n\n'
            + holds
            + f'Open it here: {link}\n\nSentinel - Magnum Opus Consultants\n')

    subject = f'You have been added to the {ws.name} workspace'
    banner = el.banner_attachment()
    ok, msg = _graph_send_simple(member.user.email, subject, body_html=html,
                                 body_text=text,
                                 attachments=[banner] if banner else [])
    if ok:
        WorkspaceMember.objects.filter(pk=member.pk).update(notified_at=timezone.now())
        logger.info('[workspace-access] told %s about %s', member.user.username, ws.name)
    return ok, msg
