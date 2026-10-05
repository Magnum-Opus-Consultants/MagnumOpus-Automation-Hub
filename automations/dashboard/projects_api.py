"""Project endpoints: the Gantt, and editing the project record behind it.

Kept apart from the task API because a project is now its own record with a
client, a status and dates, rather than just a string on a task.
"""
import json
import logging
import re
from concurrent.futures import ThreadPoolExecutor

import requests
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import activity, github_api as gh, project_gantt, project_reports
from .models import ProjectMeta, Repository, ServiceAgreement, TaskActivity
from .views import _require_module

logger = logging.getLogger(__name__)

# The website fields, with their length caps. URLs are checked separately so a
# typo comes back as an error rather than a link that goes nowhere.
_URL_FIELDS = ('website_url', 'demo_url')
_TEXT_FIELDS = (('client', 200), ('client_email', 254), ('client_contact', 200),
                ('description', 4000), ('sprint', 80), ('hosting', 200),
                ('tech_stack', 200), ('website_notes', 4000))


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _project_dict(p):
    """One project record, as every project endpoint returns it."""
    return {
        'name': p.name, 'client': p.client, 'client_email': p.client_email,
        'client_contact': p.client_contact,
        'status': p.status, 'status_display': p.get_status_display(),
        'priority': p.priority, 'priority_display': p.get_priority_display(),
        'description': p.description,
        'start_date': p.start_date.isoformat() if p.start_date else None,
        'end_date': p.end_date.isoformat() if p.end_date else None,
        'quoted_hours': float(p.quoted_hours) if p.quoted_hours else None,
        'sprint': p.sprint, 'is_automated': p.is_automated,
        'website_url': p.website_url, 'demo_url': p.demo_url,
        'hosting': p.hosting,
        'tech_stack': p.tech_stack, 'website_notes': p.website_notes,
        'color': p.color, 'icon': p.icon, 'logo_url': p.logo_url,
        'workspace': p.workspace.name if p.workspace_id else '',
        'assigned': [{'id': u.id,
                      'name': u.get_full_name() or u.username}
                     for u in p.assigned_users.all()],
    }


def _repo_dict(r):
    """A repository as the project page shows it."""
    return {
        'id': r.id, 'name': r.name, 'description': r.description,
        'remote_url': r.remote_url, 'provider': r.provider,
        'provider_display': r.get_provider_display(),
        'default_branch': r.default_branch, 'company': r.company,
        'project_name': r.project_name,
    }


def _agreement_dict(a):
    return {
        'id': a.id, 'client': a.client, 'tier': a.tier,
        'tier_display': a.get_tier_display(),
        'response_hours': a.response_hours, 'resolution_hours': a.resolution_hours,
        'support_window': a.support_window,
        'hosting_provider': a.hosting_provider, 'hosting_notes': a.hosting_notes,
        'environment_url': a.environment_url, 'backup_schedule': a.backup_schedule,
        'renewal_date': a.renewal_date.isoformat() if a.renewal_date else None,
        'renews_in_days': a.renews_in_days,
        'is_active': a.is_active,
    }


@require_http_methods(["GET"])
def api_project_gantt(request):
    """Projects on a timeline, each with its weekly breakdown."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    return JsonResponse(project_gantt.chart(
        workspace=request.GET.get('workspace', '').strip(),
        include_unassigned=request.GET.get('unassigned', '1') != '0',
        show_weeks=request.GET.get('weeks', '1') != '0',
    ))


@require_http_methods(["GET"])
def api_projects(request):
    """The project records, for the editor and the pickers."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    rows = [_project_dict(p) for p in ProjectMeta.objects.select_related(
        'workspace').prefetch_related('assigned_users')]
    return JsonResponse({
        'projects': rows,
        'statuses': [{'value': v, 'label': l}
                     for v, l in ProjectMeta.STATUS_CHOICES],
        'priorities': [{'value': v, 'label': l}
                       for v, l in ProjectMeta.PRIORITY_CHOICES],
    })


@csrf_exempt
@require_http_methods(["GET", "POST", "PATCH"])
def api_project_update(request, name):
    """Read one project (GET), or edit it. Every edit lands in the activity log."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    project = ProjectMeta.objects.filter(name=name).first()
    if project is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    if request.method == 'GET':
        # Service agreements are keyed by project name, or only by client when
        # nobody filled the project in - both describe this project's hosting.
        agreements = ServiceAgreement.objects.filter(project_name=project.name)
        if not agreements.exists() and project.client:
            agreements = ServiceAgreement.objects.filter(
                client__iexact=project.client, project_name='')
        return JsonResponse({
            'project': _project_dict(project),
            'agreements': [_agreement_dict(a) for a in agreements],
            'repositories': [_repo_dict(r) for r in
                             Repository.objects.filter(project_name=project.name)],
            'statuses': [{'value': v, 'label': l}
                         for v, l in ProjectMeta.STATUS_CHOICES],
            'priorities': [{'value': v, 'label': l}
                           for v, l in ProjectMeta.PRIORITY_CHOICES],
        })

    data = _body(request)
    user = request.user if request.user.is_authenticated else None
    changed, fields = [], []

    def note(kind, field, old, new):
        changed.append(TaskActivity(
            project_name=project.name, user=user, kind=kind, field=field,
            old_value=str(old or '')[:300], new_value=str(new or '')[:300]))

    for field in _URL_FIELDS:
        if field in data:
            new = (data.get(field) or '').strip()[:500]
            if new and not new.lower().startswith(('http://', 'https://')):
                return JsonResponse(
                    {'detail': f'{field} must start with http:// or https://.'},
                    status=400)
            if new != getattr(project, field):
                note('edited', field, getattr(project, field), new)
                setattr(project, field, new)
                fields.append(field)

    for field, cap in _TEXT_FIELDS:
        if field in data:
            new = (data.get(field) or '').strip()[:cap]
            if new != getattr(project, field):
                note('edited', field, getattr(project, field), new)
                setattr(project, field, new)
                fields.append(field)

    for field, choices, kind in (
            ('status', ProjectMeta.STATUS_CHOICES, 'status'),
            ('priority', ProjectMeta.PRIORITY_CHOICES, 'priority')):
        if field in data:
            if data[field] not in dict(choices):
                return JsonResponse({'detail': f'Unknown {field}.'}, status=400)
            if data[field] != getattr(project, field):
                note(kind, field, getattr(project, field), data[field])
                setattr(project, field, data[field])
                fields.append(field)

    for field in ('start_date', 'end_date'):
        if field in data:
            raw = data.get(field) or None
            if raw:
                from django.utils.dateparse import parse_date
                parsed = parse_date(raw)
                if parsed is None:
                    return JsonResponse({'detail': f'{field} must be YYYY-MM-DD.'},
                                        status=400)
            else:
                parsed = None
            if parsed != getattr(project, field):
                note('dates', field, getattr(project, field), parsed)
                setattr(project, field, parsed)
                fields.append(field)

    if 'quoted_hours' in data:
        raw = data.get('quoted_hours')
        try:
            parsed = None if raw in (None, '') else round(float(raw), 2)
        except (TypeError, ValueError):
            return JsonResponse({'detail': 'quoted_hours must be a number.'},
                                status=400)
        if parsed != (float(project.quoted_hours) if project.quoted_hours else None):
            note('hours', 'quoted_hours', project.quoted_hours, parsed)
            project.quoted_hours = parsed
            fields.append('quoted_hours')

    if 'assigned' in data:
        ids = data.get('assigned') or []
        if not isinstance(ids, list):
            return JsonResponse({'detail': 'assigned must be a list of user ids.'},
                                status=400)
        before = sorted(u.id for u in project.assigned_users.all())
        project.assigned_users.set(ids)
        after = sorted(u.id for u in project.assigned_users.all())
        if before != after:
            note('assigned', 'assigned_users', before, after)

    if fields:
        project.save(update_fields=fields + ['updated_at'])
    if changed:
        TaskActivity.objects.bulk_create(changed)

    return JsonResponse({'ok': True, 'changed': fields,
                         'activity': len(changed)})


@require_http_methods(["GET"])
def api_project_activity(request, name):
    """What has happened on this project, newest first."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    try:
        limit = min(int(request.GET.get('limit', 50)), 300)
    except ValueError:
        limit = 50
    rows = (TaskActivity.objects.filter(project_name=name)
            .select_related('user', 'task')[:limit])
    return JsonResponse({'activity': [
        {'id': a.id, 'kind': a.kind, 'summary': a.summary,
         'task': a.task.title if a.task_id else '',
         'when': a.created_at.isoformat()}
        for a in rows]})


@require_http_methods(["GET"])
def api_project_metrics(request):
    """The reporting figures, for the reports page."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    try:
        days = min(max(int(request.GET.get('days', 30)), 1), 365)
    except ValueError:
        days = 30
    return JsonResponse(project_reports.metrics(
        days=days,
        project_name=request.GET.get('project', '').strip(),
        workspace=request.GET.get('workspace', '').strip()))


# ══════════════════════════════════════════════════════════════════════════════
# Repositories on a project
# ══════════════════════════════════════════════════════════════════════════════

def _norm_remote(url):
    """A remote URL compared loosely: no case, trailing slash or .git."""
    url = (url or '').strip().rstrip('/')
    if url.lower().endswith('.git'):
        url = url[:-4]
    return url.lower()


def _find_by_remote(url):
    want = _norm_remote(url)
    return next((r for r in Repository.objects.exclude(remote_url='')
                 if _norm_remote(r.remote_url) == want), None)


def _note_repo(request, project, old, new):
    TaskActivity.objects.create(
        project_name=project.name,
        user=request.user if request.user.is_authenticated else None,
        kind='edited', field='repository', old_value=old[:300], new_value=new[:300])


def _provider_for(host):
    host = host.lower()
    if 'github' in host:
        return 'github'
    if 'gitlab' in host:
        return 'gitlab'
    if 'bitbucket' in host:
        return 'bitbucket'
    if 'dev.azure' in host or 'visualstudio' in host:
        return 'azure'
    return 'other'


@csrf_exempt
@require_http_methods(["GET", "POST"])
def api_project_repos(request, name):
    """The repositories on a project (GET), or assign one to it (POST).

    POST takes one of:
      {"repo_id": 3}             - a repository Sentinel already tracks
      {"full_name": "org/repo"}  - one on the connected GitHub account, imported
      {"url": "https://..."}     - any remote, tracked from its link
    A repository belongs to one project, so assigning it here moves it.
    """
    err = _require_module(request, 'tasks')
    if err:
        return err
    project = ProjectMeta.objects.filter(name=name).first()
    if project is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    if request.method == 'GET':
        out = {
            'assigned': [_repo_dict(r) for r in
                         Repository.objects.filter(project_name=project.name)],
            'tracked': [_repo_dict(r) for r in
                        Repository.objects.exclude(project_name=project.name)],
            'github': {'configured': gh.is_configured()},
        }
        # GitHub is asked only when the picker wants it - it is a network call.
        if request.GET.get('github') == '1' and out['github']['configured']:
            ok, repos = gh.list_repos()
            if ok:
                tracked = {_norm_remote(u) for u in
                           Repository.objects.values_list('remote_url', flat=True)}
                out['github'].update(ok=True, repos=[
                    r for r in repos if _norm_remote(r['url']) not in tracked])
            else:
                out['github'].update(ok=False, detail=repos.get('message'))
        return JsonResponse(out)

    data = _body(request)
    if data.get('repo_id'):
        rec = Repository.objects.filter(id=data.get('repo_id')).first()
        if rec is None:
            return JsonResponse({'detail': 'No such repository.'}, status=404)

    elif data.get('full_name'):
        full_name = str(data['full_name']).strip()
        if not gh.is_configured():
            return JsonResponse({'detail': 'GitHub is not connected on this server.'},
                                status=400)
        ok, repos = gh.list_repos()
        if not ok:
            return JsonResponse({'detail': repos.get('message')}, status=400)
        match = next((r for r in repos if r['full_name'] == full_name), None)
        if match is None:
            return JsonResponse(
                {'detail': f'"{full_name}" is not on the connected account.'}, status=404)
        rec = _find_by_remote(match['url'])
        if rec is None:
            rec = Repository.objects.create(
                name=match['name'], description=match['description'],
                remote_url=match['url'], provider='github',
                default_branch=match['default_branch'],
                order=Repository.objects.count())
            activity.record(request, 'created', 'repository', obj=rec, label=rec.name,
                            detail=f'imported from GitHub for {project.name}',
                            project=project.name)

    elif data.get('create'):
        # A new repository on the connected account, made for this project.
        if not request.user.is_superuser:
            return JsonResponse({'detail': 'Only administrators can create repositories.'},
                                status=403)
        if not gh.is_configured():
            return JsonResponse({'detail': 'GitHub is not connected on this server.'}, status=400)
        from .proxmox import hostname_for
        ok, existing = gh.list_repos()
        taken = {r['name'].lower() for r in existing} if ok else set()
        repo_name = hostname_for(str(data.get('name') or project.name), taken)
        ok, made = gh.create_repo(repo_name, description=f'{project.name} (created by Sentinel)',
                                  private=bool(data.get('private', True)))
        if not ok:
            return JsonResponse({'detail': made.get('message') or 'GitHub refused.'}, status=400)
        rec = Repository.objects.create(
            name=made['name'], description=f'{project.name} (created by Sentinel)',
            remote_url=made['url'], provider='github',
            default_branch=made.get('default_branch') or 'main',
            order=Repository.objects.count())
        activity.record(request, 'created', 'repository', obj=rec, label=rec.name,
                        detail=f'on GitHub ({made.get("full_name", rec.name)}) for {project.name}',
                        project=project.name)

    elif data.get('url'):
        url = str(data['url']).strip().rstrip('/')
        if not url.lower().startswith(('http://', 'https://')):
            return JsonResponse(
                {'detail': 'The repository link must start with https://.'}, status=400)
        rec = _find_by_remote(url)
        if rec is None:
            # The name is the last part of the path: github.com/org/<name>.
            clean = re.sub(r'\.git$', '', url, flags=re.I)
            host = re.sub(r'^https?://', '', clean, flags=re.I).split('/', 1)[0]
            rec = Repository.objects.create(
                name=clean.rsplit('/', 1)[-1][:200] or project.name,
                remote_url=clean, provider=_provider_for(host),
                order=Repository.objects.count())
            activity.record(request, 'created', 'repository', obj=rec, label=rec.name,
                            detail=f'added from a link for {project.name}',
                            project=project.name)
    else:
        return JsonResponse({'detail': 'Give repo_id, full_name or url.'}, status=400)

    if rec.project_name != project.name:
        moved_from = rec.project_name
        rec.project_name = project.name
        rec.save(update_fields=['project_name', 'updated_at'])
        _note_repo(request, project,
                   f'{rec.name} on {moved_from}' if moved_from else '', rec.name)
    return JsonResponse({'ok': True, 'repository': _repo_dict(rec)}, status=201)


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_project_repo_remove(request, name, pk):
    """Take a repository off a project. The repository itself stays tracked."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    project = ProjectMeta.objects.filter(name=name).first()
    rec = Repository.objects.filter(id=pk, project_name=name).first()
    if project is None or rec is None:
        return JsonResponse({'detail': 'That repository is not on this project.'},
                            status=404)
    rec.project_name = ''
    rec.save(update_fields=['project_name', 'updated_at'])
    _note_repo(request, project, rec.name, 'none')
    return JsonResponse({'ok': True})


# ══════════════════════════════════════════════════════════════════════════════
# Website preview
# ══════════════════════════════════════════════════════════════════════════════

def _frame_check(url):
    """Whether a site will show inside the project page, from its headers.

    Most sites forbid being framed by anybody else, and a browser gives the page
    no way to find out - the frame just stays blank. Asking from the server
    turns that into a sentence and an "open in a new tab" button instead.
    Only ever called with the project's own stored URLs.
    """
    try:
        r = requests.get(url, timeout=6, allow_redirects=True, stream=True,
                         headers={'User-Agent': 'Sentinel site preview'})
        r.close()
    except requests.RequestException:
        return {'url': url, 'reachable': False, 'embeddable': False,
                'reason': 'The site did not respond.'}

    xfo = r.headers.get('X-Frame-Options', '').strip().upper()
    ancestors = None
    for part in r.headers.get('Content-Security-Policy', '').split(';'):
        part = part.strip()
        if part.lower().startswith('frame-ancestors'):
            ancestors = part[len('frame-ancestors'):].split()
    reason = ''
    if ancestors is not None and '*' not in ancestors:
        reason = "The site's security policy only lets its own pages show it."
    elif xfo in ('DENY', 'SAMEORIGIN'):
        reason = ('The site refuses to be shown inside other pages '
                  f'(X-Frame-Options: {xfo}).')
    return {'url': url, 'final_url': r.url, 'status': r.status_code,
            'reachable': r.status_code < 500, 'embeddable': not reason,
            'reason': reason}


@require_http_methods(["GET"])
def api_project_site_check(request, name):
    """Can the live and demo sites be previewed on the project page?"""
    err = _require_module(request, 'tasks')
    if err:
        return err
    project = ProjectMeta.objects.filter(name=name).first()
    if project is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)
    urls = {'live': project.website_url, 'demo': project.demo_url}
    wanted = {k: u for k, u in urls.items() if u}
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = dict(zip(wanted, pool.map(_frame_check, wanted.values())))
    return JsonResponse({k: results.get(k) for k in urls})
