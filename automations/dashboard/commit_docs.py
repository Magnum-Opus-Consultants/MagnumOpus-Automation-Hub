"""Documentation from commits.

When a commit lands on a repository that belongs to a project, Sentinel
writes it up as a piece of that project's documentation (a CommitDoc), so the
project explains itself as it is built. New commits are picked up by the
scheduler every 10 minutes, and straight away from the project's Docs page.

Two ways to write one up:

* **From the commit itself** - always. The message, laid out, with the files
  it changed and by how much. Nothing is invented: a commit that says "wip"
  is documented as "wip", which is the honest record and the prompt to write
  better messages (the same rule as repo_docs.py).
* **By an AI**, from the message and short excerpts of the changed code, when
  COMMIT_DOCS_AI=true and a Gemini key is configured. That sends those
  excerpts to Google, so it stays off until somebody decides that is fine for
  the repositories involved - several are clients' code.

Only the newest commits are read when a repository is first linked
(FIRST_LOOK), so linking an old repository does not document years of history
in one go; from then on every new commit is written up.
"""
import logging
import os
import re
import threading

from django.db import IntegrityError, close_old_connections
from django.utils.dateparse import parse_datetime

from . import github_api as gh
from . import llm, repo_docs
from .models import CommitDoc, Repository

logger = logging.getLogger(__name__)

FIRST_LOOK = 15
KIND_KEY = {heading: key for key, heading in repo_docs.KINDS.items()}
_locks = {}
_locks_guard = threading.Lock()
_running = set()   # project names with a check in progress


class DocsError(Exception):
    """Something stopped the documentation being written. For people."""


def ai_enabled():
    return (os.getenv('COMMIT_DOCS_AI', '').lower() in ('1', 'true', 'yes')
            and llm.available())


def _lock_for(repo_id):
    with _locks_guard:
        return _locks.setdefault(repo_id, threading.Lock())


def _files_list(files, limit=40):
    lines = [f"- `{f['filename']}` - {f['status']}, +{f['additions']} -{f['deletions']}"
             for f in files[:limit]]
    if len(files) > limit:
        lines.append(f'- and {len(files) - limit} more files')
    return lines


# Git trailers record who signed or co-wrote a commit; they are not documentation.
_TRAILER = re.compile(r'^(Co-Authored-By|Signed-off-by|Reviewed-by|Change-Id):', re.I)


def _message_body(text):
    lines = [ln for ln in (text or '').splitlines() if not _TRAILER.match(ln.strip())]
    return '\n'.join(lines).strip()


def _from_commit(detail):
    """The commit's own words, laid out, with what it touched."""
    _, subject = repo_docs._classify(detail['subject'])
    parts = []
    body = _message_body(detail['body'])
    if body:
        parts += [body, '']
    if detail['files']:
        parts += [f"**Files changed ({len(detail['files'])})**", *_files_list(detail['files'])]
    return subject, '\n'.join(parts).strip(), 'commit'


PROMPT = """You write the documentation for a software project, one commit at a time.
Below is a git commit from the project "{project}": its message and excerpts of what changed.
Explain the change for someone maintaining this project later: what changed, why (from the
message), and which parts of the system it affects. Only state what the commit shows; do not
guess at things it does not show. Plain, specific English. No marketing words.

Return JSON: {{"title": "short heading, under 80 characters",
"summary": "two or three sentences",
"details": ["one specific point per item"],
"areas": ["parts of the system affected"]}}

Commit message:
{message}

Changed files and excerpts:
{changes}
"""


def _by_ai(detail, project):
    changes, budget = [], 12000
    for f in detail['files']:
        block = f"--- {f['filename']} ({f['status']}, +{f['additions']} -{f['deletions']})\n{f['patch']}"
        if len(block) > budget:
            changes.append(f"--- {f['filename']} ({f['status']}) [excerpt omitted]")
            continue
        changes.append(block)
        budget -= len(block)
    body = _message_body(detail['body'])
    message = detail['subject'] + ('\n\n' + body if body else '')
    data = llm.generate_json(PROMPT.format(project=project, message=message,
                                           changes='\n\n'.join(changes) or '(no file changes)'),
                             temperature=0.2, max_tokens=2048)
    if not isinstance(data, dict) or not data.get('title'):
        return None
    parts = [str(data.get('summary') or '').strip(), '']
    parts += [f'- {d}' for d in data.get('details') or [] if str(d).strip()]
    if data.get('areas'):
        parts += ['', '**Affects:** ' + ', '.join(str(a) for a in data['areas'])]
    if detail['files']:
        parts += ['', f"**Files changed ({len(detail['files'])})**", *_files_list(detail['files'])]
    return str(data['title']), '\n'.join(parts).strip(), 'ai'


def sync_repo(rec, limit=FIRST_LOOK):
    """Write up the repository's commits that have no documentation yet."""
    full = repo_docs.full_name(rec)
    if not full:
        return 0
    with _lock_for(rec.id):
        ok, commits = gh.list_commits(full, limit=limit)
        if not ok:
            raise DocsError(commits.get('message') or 'GitHub did not answer.')
        known = set(CommitDoc.objects.filter(repository=rec, sha__in=[c['sha'] for c in commits])
                    .values_list('sha', flat=True))
        use_ai = ai_enabled()
        made = 0
        for c in reversed(commits):   # oldest first, so the page reads in order
            if c['sha'] in known or not c['subject'] or repo_docs._MERGE.match(c['subject']):
                continue
            ok, detail = gh.get_commit(full, c['sha'])
            if not ok or detail['parents'] > 1:
                continue
            written = None
            if use_ai:
                try:
                    written = _by_ai(detail, rec.project_name or rec.name)
                except Exception:  # noqa: BLE001 - the plain write-up is the fallback
                    logger.exception('AI write-up failed for %s', detail['sha'])
            title, body, source = written or _from_commit(detail)
            heading, _ = repo_docs._classify(detail['subject'])
            try:
                CommitDoc.objects.create(
                    repository=rec, sha=detail['sha'],
                    committed_at=parse_datetime(detail['date']) if detail['date'] else None,
                    author=detail['author'][:200], url=detail['url'] or '',
                    kind=KIND_KEY.get(heading, 'other'), subject=detail['subject'][:500],
                    title=title[:300], body=body,
                    files=[{k: f[k] for k in ('filename', 'status', 'additions', 'deletions')}
                           for f in detail['files']],
                    additions=detail['stats'].get('additions', 0),
                    deletions=detail['stats'].get('deletions', 0), source=source)
                made += 1
            except IntegrityError:
                pass   # written by a check running at the same moment
        return made


def project_repos(project_name):
    return Repository.objects.filter(project_name=project_name, remote_url__icontains='github.com')


def sync_project(project_name):
    """Check every repository on a project. Returns {repo name: commits written}."""
    _running.add(project_name)
    try:
        return {r.name: sync_repo(r) for r in project_repos(project_name)}
    finally:
        _running.discard(project_name)


def is_running(project_name):
    return project_name in _running


def sync_all():
    """The scheduler's sweep: every repository that belongs to a project."""
    if not gh.is_configured():
        return
    close_old_connections()
    try:
        for rec in Repository.objects.exclude(project_name='').filter(
                remote_url__icontains='github.com'):
            try:
                made = sync_repo(rec)
                if made:
                    logger.info('Documented %s new commit(s) on %s', made, rec.name)
            except DocsError as e:
                logger.warning('Commit docs for %s: %s', rec.name, e)
    finally:
        close_old_connections()


def sync_project_in_background(project_name):
    def run():
        close_old_connections()
        try:
            sync_project(project_name)
        except DocsError as e:
            logger.warning('Commit docs for %s: %s', project_name, e)
        finally:
            close_old_connections()
    threading.Thread(target=run, name='commit-docs', daemon=True).start()
