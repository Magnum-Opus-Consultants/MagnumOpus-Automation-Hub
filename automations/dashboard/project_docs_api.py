"""A project's documentation from its commits: read it, or check for new ones."""
from django.http import JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import commit_docs, github_api as gh
from .models import CommitDoc, ProjectMeta
from .views import _require_module

KIND_LABEL = {key: heading for key, heading in commit_docs.repo_docs.KINDS.items()}


def _entry(d):
    return {
        'id': d.id, 'sha': d.sha, 'short_sha': d.sha[:7], 'url': d.url,
        'repo': d.repository.name, 'repo_id': d.repository_id,
        'committed_at': d.committed_at.isoformat() if d.committed_at else None,
        'author': d.author, 'kind': d.kind,
        'kind_label': KIND_LABEL.get(d.kind, 'Other changes'),
        'title': d.title or d.subject, 'body': d.body, 'files': d.files,
        'additions': d.additions, 'deletions': d.deletions, 'source': d.source,
    }


@require_http_methods(["GET"])
def api_project_docs(request, name):
    err = _require_module(request, 'tasks')
    if err:
        return err
    if not ProjectMeta.objects.filter(name=name).exists():
        return JsonResponse({'detail': 'Project not found.'}, status=404)
    repos = list(commit_docs.project_repos(name))
    try:
        limit = min(int(request.GET.get('limit', 100)), 500)
    except ValueError:
        limit = 100
    entries = (CommitDoc.objects.filter(repository__in=repos)
               .select_related('repository')[:limit])
    return JsonResponse({
        'github_configured': gh.is_configured(),
        'ai': commit_docs.ai_enabled(),
        'checking': commit_docs.is_running(name),
        'repos': [{'id': r.id, 'name': r.name, 'url': r.remote_url} for r in repos],
        'entries': [_entry(d) for d in entries],
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_project_docs_sync(request, name):
    """Check the project's repositories for new commits now."""
    err = _require_module(request, 'tasks')
    if err:
        return err
    if not ProjectMeta.objects.filter(name=name).exists():
        return JsonResponse({'detail': 'Project not found.'}, status=404)
    if not gh.is_configured():
        return JsonResponse({'detail': 'GitHub is not connected on this server.'}, status=400)
    if not commit_docs.is_running(name):
        commit_docs.sync_project_in_background(name)
    return JsonResponse({'checking': True}, status=202)
