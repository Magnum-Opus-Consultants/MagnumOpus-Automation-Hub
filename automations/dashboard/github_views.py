"""The GitHub endpoints: status, create a repository, import an existing one.

Creating a repository is not undoable from here - GitHub keeps it until
somebody deletes it there - so the endpoint is deliberately explicit about
what it made and where, and refuses rather than guesses when the name is
already taken.
"""
import json
import logging
from datetime import timedelta

from django.http import JsonResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import activity
from . import github_api as gh
from .models import (ProjectList, ProjectMeta, ProjectTask, RepoDoc,
                     Repository, ServerRecord, Workspace)
from .views import _require_module

logger = logging.getLogger(__name__)

MODULE = 'repos'


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


@require_http_methods(["GET"])
def api_github_status(request):
    """Whether GitHub is wired up, and what it is wired up to."""
    err = _require_module(request, MODULE)
    if err:
        return err
    if not gh.is_configured():
        return JsonResponse({
            'configured': False,
            'detail': 'No GitHub token on this server. Add GITHUB_TOKEN and '
                      'GITHUB_OWNER to the environment.',
        })
    ok, who = gh.whoami()
    if not ok:
        return JsonResponse({'configured': True, 'ok': False,
                             'detail': who.get('message')})
    ok, repos = gh.list_repos()
    return JsonResponse({
        'configured': True, 'ok': True, 'account': who,
        'repos': repos if ok else [],
        'repo_error': None if ok else repos.get('message'),
        # Which of them the platform already tracks, so the page can offer to
        # import the rest rather than listing everything twice.
        'tracked': list(Repository.objects.exclude(remote_url='')
                        .values_list('remote_url', flat=True)),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_github_create(request):
    """Create a repository on GitHub and track it here in one step.

    Both, or neither: a repo made on GitHub that the platform does not know
    about is exactly the situation this feature exists to avoid.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'detail': 'A repository name is required.'}, status=400)

    ok, repo = gh.create_repo(
        name,
        description=(data.get('description') or '').strip(),
        private=data.get('private', True),
    )
    if not ok:
        return JsonResponse({'detail': repo.get('message')}, status=400)

    # Which host it runs on, if that is known yet. A bad id is ignored rather
    # than failing the call: the repository exists on GitHub by this point, and
    # refusing here would leave it created but untracked.
    server = None
    server_id = data.get('server')
    if server_id:
        server = ServerRecord.objects.filter(id=server_id).first()

    rec = Repository.objects.create(
        name=repo['name'],
        description=(data.get('description') or '').strip(),
        remote_url=repo['url'],
        provider='github',
        default_branch=repo['default_branch'],
        company=(data.get('company') or '').strip(),
        server=server,
        notes=(data.get('project') or '').strip(),
        order=Repository.objects.count(),
    )
    project = _ensure_project(rec.name)
    activity.record(request, 'created', 'repository', obj=rec, label=rec.name,
                    detail=f'on GitHub ({repo["full_name"]})')
    return JsonResponse({'ok': True, 'repo': repo, 'id': rec.id,
                         'project': project}, status=201)


def _ensure_project(name):
    """Give a new repository somewhere to put its work.

    Code without a place to track the work against it is how a repository ends
    up with no record of why any of it happened. So creating one also declares
    a project of the same name, with a Documentation list ready for the notes
    that become the project's documentation.

    Existing names are left alone - somebody who already has a project called
    this means that project.
    """
    if ProjectTask.objects.filter(project_name=name).exists():
        return {'name': name, 'created': False}

    meta, made = ProjectMeta.objects.get_or_create(
        name=name, defaults={'workspace': Workspace.default()})
    ProjectList.objects.get_or_create(
        project_name=name, workspace=None, name='Documentation',
        defaults={'order': 0})
    return {'name': meta.name, 'created': made,
            'workspace': meta.workspace.name if meta.workspace else ''}


@csrf_exempt
@require_http_methods(["POST"])
def api_github_import(request):
    """Track a repository that already exists on GitHub."""
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)
    full_name = (data.get('full_name') or '').strip()
    if not full_name or '/' not in full_name:
        return JsonResponse({'detail': 'full_name must look like owner/repo.'},
                            status=400)

    ok, repos = gh.list_repos()
    if not ok:
        return JsonResponse({'detail': repos.get('message')}, status=400)
    match = next((r for r in repos if r['full_name'] == full_name), None)
    if match is None:
        return JsonResponse(
            {'detail': f'"{full_name}" is not on the connected account.'},
            status=404)
    if Repository.objects.filter(remote_url=match['url']).exists():
        return JsonResponse({'detail': 'That repository is already tracked.'},
                            status=409)

    rec = Repository.objects.create(
        name=match['name'], description=match['description'],
        remote_url=match['url'], provider='github',
        default_branch=match['default_branch'],
        order=Repository.objects.count(),
    )
    return JsonResponse({'ok': True, 'id': rec.id, 'name': rec.name}, status=201)


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_github_delete(request, pk):
    """Delete a tracked repository on GitHub, and stop tracking it here.

    Irreversible on GitHub's side, so the caller has to ask for it explicitly
    with `confirm: true` - an accidental DELETE to the wrong id should not
    destroy somebody's code.

    GitHub is deleted first. If that fails the row stays, because a tracked
    repository that no longer exists is a smaller problem than a deleted one
    nobody has a record of.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    rec = Repository.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    if not _body(request).get('confirm'):
        return JsonResponse(
            {'detail': 'Deleting on GitHub cannot be undone; send confirm: true.'},
            status=400)
    if 'github.com/' not in (rec.remote_url or ''):
        return JsonResponse(
            {'detail': 'That repository has no GitHub remote recorded.'},
            status=400)

    full_name = rec.remote_url.split('github.com/', 1)[1].strip('/')
    full_name = full_name[:-4] if full_name.endswith('.git') else full_name

    ok, result = gh.delete_repo(full_name)
    if not ok:
        return JsonResponse({'detail': result.get('message')}, status=400)

    name = rec.name
    repo_pk = rec.id
    rec.delete()
    logger.info('[github] deleted %s and stopped tracking it', full_name)
    activity.record(request, 'deleted', 'repository', object_id=repo_pk,
                    label=name, detail=f'on GitHub ({full_name})')
    return JsonResponse({'ok': True, 'deleted': full_name, 'name': name})


@require_http_methods(["GET"])
def api_repo_documentation(request, pk):
    """The repository's commits, arranged as documentation for its project."""
    err = _require_module(request, MODULE)
    if err:
        return err
    from . import repo_docs

    try:
        limit = min(300, max(1, int(request.GET.get('limit') or 100)))
    except ValueError:
        limit = 100
    data, problem = repo_docs.build(pk, limit=limit)
    if problem:
        return JsonResponse({'detail': problem},
                            status=404 if problem == 'Not found.' else 400)
    return JsonResponse(data)


@csrf_exempt
@require_http_methods(["POST"])
def api_repo_doc_save(request, pk):
    """Create or update one documentation page, stored here.

    Keyed on `path` within the repository rather than on a row id, so saving a
    page that currently comes from the repository's own README simply starts
    overriding it - which is the whole point of being able to write here.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    rec = Repository.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)

    data = _body(request)
    title = (data.get('title') or '').strip()
    if not title:
        return JsonResponse({'detail': 'A title is required.'}, status=400)

    path = (data.get('path') or '').strip() or _slug_path(title)
    who = request.user if request.user.is_authenticated else None
    doc, made = RepoDoc.objects.update_or_create(
        repository=rec, path=path,
        defaults={
            'title': title,
            'body': data.get('body') or '',
            'order': int(data.get('order') or 0),
            'updated_by': who,
            'updated_by_name': (who.get_full_name() or who.username) if who else '',
        })
    activity.record(request, 'created' if made else 'updated', 'document',
                    obj=doc, label=doc.title, project=rec.name)
    return JsonResponse({'ok': True, 'id': doc.id, 'path': doc.path,
                         'title': doc.title, 'created': made},
                        status=201 if made else 200)


def _slug_path(title):
    """A file-ish path from a title, for a page created without one."""
    import re as _re
    slug = _re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-') or 'page'
    return f'docs/{slug}.md'


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_repo_doc_delete(request, pk, doc_id):
    """Delete a page written here.

    Only pages stored on this platform can be deleted; one read from the
    repository is not ours to remove, and the way to be rid of it is to delete
    it in the repository.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    doc = RepoDoc.objects.filter(id=doc_id, repository_id=pk).first()
    if not doc:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    title, doc_pk = doc.title, doc.id
    doc.delete()
    activity.record(request, 'deleted', 'document', object_id=doc_pk,
                    label=title, project=doc.repository.name)
    return JsonResponse({'ok': True, 'deleted': title})


@csrf_exempt
@require_http_methods(["POST"])
def api_repo_doc_import(request, pk):
    """Copy the repository's own README and docs/ into pages held here.

    Useful once, when a repository already documents itself and the team wants
    to keep editing that text in the platform rather than through commits.
    Pages that already exist here are left alone - importing must not discard
    somebody's edits.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    from . import repo_docs

    rec = Repository.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    name = repo_docs.full_name(rec)
    if not name:
        return JsonResponse(
            {'detail': 'That repository has no GitHub remote recorded.'},
            status=400)

    existing = set(rec.docs.values_list('path', flat=True))
    who = request.user if request.user.is_authenticated else None
    made = 0
    for page in repo_docs._read_pages(rec, name):
        if page['source'] != 'repo' or page['path'] in existing:
            continue
        RepoDoc.objects.create(
            repository=rec, path=page['path'], title=page['title'],
            body=page['body'], order=made,
            updated_by=who,
            updated_by_name=(who.get_full_name() or who.username) if who else '')
        made += 1
    return JsonResponse({'ok': True, 'imported': made})


@require_http_methods(["GET"])
def api_activity(request):
    """The activity feed for the platform's own pages.

    Same data as the token gateway at /api/v1/activity, reached with a session
    instead - so what a person reads on the Activity page and what an agent
    reads over the API cannot drift apart.
    """
    if not request.user.is_authenticated:
        return JsonResponse({'detail': 'Not authenticated.'}, status=401)

    since = None
    days = request.GET.get('days')
    if days:
        try:
            since = timezone.now() - timedelta(days=max(0, int(days)))
        except ValueError:
            since = None
    try:
        limit = int(request.GET.get('limit') or 100)
    except ValueError:
        limit = 100

    entries = activity.feed(
        limit=limit,
        actor=(request.GET.get('actor') or '').strip(),
        object_type=(request.GET.get('type') or '').strip(),
        since=since,
        search=(request.GET.get('q') or '').strip(),
    )
    return JsonResponse({
        'entries': entries,
        'summary': activity.summary(entries),
        'people': sorted({e['actor'] for e in entries if e['actor']}),
        'types': sorted({e['object_type'] for e in entries}),
    })


@require_http_methods(["GET"])
def api_github_commits(request, pk):
    """Commits for a tracked repository, read from GitHub rather than a clone.

    The existing history endpoint shells out to git against a local checkout,
    which only works for repos cloned onto this server. This one works for
    anything on the account.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    rec = Repository.objects.filter(id=pk).first()
    if not rec:
        return JsonResponse({'detail': 'Not found.'}, status=404)
    if 'github.com/' not in (rec.remote_url or ''):
        return JsonResponse(
            {'detail': 'That repository has no GitHub remote recorded.'},
            status=400)

    full_name = rec.remote_url.split('github.com/', 1)[1].strip('/')
    full_name = full_name[:-4] if full_name.endswith('.git') else full_name
    ok, commits = gh.list_commits(full_name, since=request.GET.get('since'))
    if not ok:
        return JsonResponse({'detail': commits.get('message')}, status=400)
    return JsonResponse({'repo': full_name, 'count': len(commits),
                         'commits': commits})
