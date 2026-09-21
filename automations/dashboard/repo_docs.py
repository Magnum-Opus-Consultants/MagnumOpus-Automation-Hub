"""Turn a repository's commits into documentation for its project.

## What this can and cannot do

It reads what people wrote in their commit messages and arranges it. It does
not invent a narrative: if a month's commits all say "wip", the page for that
month says "wip" three times, and that is the honest output. The fix for thin
documentation is writing better commit messages, and a tool that papered over
that would remove the only signal telling you to.

So the page reports its own quality: how many commits carry a real explanation
versus a bare subject line. That number is the thing worth acting on.

## How commits are grouped

**By month**, newest first. A release-based grouping would be better, but tags
are not used here yet; months match how the weekly report and the tracker
already think about time.

**By kind, inside a month.** Conventional prefixes (`feat:`, `fix:`, `docs:`)
are read when present, because a team that writes them has already done the
classification. Everything else lands under "Other changes" rather than being
guessed at.

## What is left out

  * **Merge commits** - "Merge pull request #42" documents git, not the work.
  * **Commits with no subject** - nothing to say about them.

Both are counted and reported, so nothing disappears silently.
"""
import re
from collections import Counter, OrderedDict

from . import github_api as gh
from .models import Repository

# Conventional-commit prefixes, mapped to headings a reader would recognise.
KINDS = OrderedDict([
    ('feat', 'New features'),
    ('fix', 'Fixes'),
    ('perf', 'Performance'),
    ('refactor', 'Refactoring'),
    ('docs', 'Documentation'),
    ('test', 'Tests'),
    ('build', 'Build and dependencies'),
    ('ci', 'CI'),
    ('chore', 'Chores'),
])
OTHER = 'Other changes'

_PREFIX = re.compile(r'^(?P<kind>[a-z]+)(?:\([^)]*\))?!?:\s*(?P<rest>.+)$', re.I)
_MERGE = re.compile(r'^Merge (pull request|branch|remote-tracking)\b', re.I)

MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
          'August', 'September', 'October', 'November', 'December']


def full_name(rec):
    """owner/repo from a stored remote URL, or None."""
    url = rec.remote_url or ''
    if 'github.com/' not in url:
        return None
    name = url.split('github.com/', 1)[1].strip('/')
    return name[:-4] if name.endswith('.git') else name


def _classify(subject):
    """(kind heading, cleaned subject). Unprefixed subjects keep their text."""
    m = _PREFIX.match(subject)
    if not m:
        return OTHER, subject
    kind = m.group('kind').lower()
    return KINDS.get(kind, OTHER), m.group('rest').strip()


def build(repo_id, limit=100):
    """The documentation payload for one repository."""
    rec = Repository.objects.filter(id=repo_id).first()
    if not rec:
        return None, 'Not found.'
    name = full_name(rec)

    # Documentation written here does not need GitHub at all, so neither a
    # missing remote nor a missing token is an error any more - they just mean
    # there is no commit history to show alongside the pages.
    commits = []
    history_problem = None
    if not name:
        history_problem = 'No GitHub remote is recorded for this repository.'
    elif not gh.is_configured():
        history_problem = 'GitHub is not connected on this server.'
    else:
        ok, result = gh.list_commits(name, limit=limit)
        if ok:
            commits = result
        else:
            history_problem = result.get('message')

    pages = _read_pages(rec, name)

    months = OrderedDict()
    people = Counter()
    skipped_merges = 0
    described = 0
    counted = 0

    for c in commits:
        subject = (c.get('subject') or '').strip()
        if not subject:
            continue
        if _MERGE.match(subject):
            skipped_merges += 1
            continue

        date = c.get('date') or ''
        key = date[:7]                       # YYYY-MM
        try:
            year, month = int(key[:4]), int(key[5:7])
            label = f'{MONTHS[month - 1]} {year}'
        except (ValueError, IndexError):
            key, label = 'unknown', 'Undated'

        kind, cleaned = _classify(subject)
        body = (c.get('body') or '').strip()
        if body:
            described += 1
        counted += 1
        people[c.get('author') or 'Unknown'] += 1

        bucket = months.setdefault(key, {'key': key, 'label': label,
                                         'groups': OrderedDict(), 'count': 0})
        bucket['groups'].setdefault(kind, []).append({
            'sha': c['sha'], 'short_sha': c['short_sha'],
            'subject': cleaned, 'body': body,
            'author': c.get('author') or '', 'date': date,
            'url': c.get('url'),
        })
        bucket['count'] += 1

    # Headings in a stable order, not whichever kind happened to commit first.
    order = list(KINDS.values()) + [OTHER]
    for bucket in months.values():
        bucket['groups'] = [
            {'kind': k, 'commits': bucket['groups'][k]}
            for k in order if k in bucket['groups']
        ]

    return {
        'pages': pages,
        'repo': {'id': rec.id, 'name': rec.name, 'full_name': name,
                 'url': rec.remote_url, 'description': rec.description,
                 'branch': rec.default_branch or 'main',
                 'company': rec.company},
        'project': rec.name,
        'months': list(months.values()),
        'history_problem': history_problem,
        'totals': {
            'commits': counted,
            'described': described,
            # The number worth acting on: a low share means the history is
            # subjects only, and no tool can turn that into documentation.
            'described_pct': round(100 * described / counted) if counted else 0,
            'merges_skipped': skipped_merges,
            'contributors': [{'name': n, 'commits': c}
                             for n, c in people.most_common()],
            'reached_limit': len(commits) >= limit,
        },
    }, None


def _read_pages(rec, full_name):
    """The documentation for one repository.

    A commit log is a record of changes, not documentation - which is why the
    first cut of this page read as a changelog no matter how it was arranged.
    Actual documentation is prose somebody wrote.

    Two sources, in this order of authority:

      1. **Written here.** Pages in `RepoDoc`, edited in the platform. These
         win, because they can be corrected the moment somebody spots a
         mistake - no push access to anybody else's repository required.
      2. **The repository's own files.** README.md and docs/*.md, read live.
         Shown where nothing here overrides them, so a repo that already
         documents itself needs no re-typing.

    Ordering is what a reader wants rather than what the filesystem gives:
    the front page first, then by the order field, then by path.
    """
    pages = []
    seen = set()

    for d in rec.docs.all():
        seen.add(d.path)
        pages.append({
            'path': d.path, 'title': d.title, 'body': d.body,
            'source': 'sentinel', 'id': d.id, 'order': d.order,
            'updated_at': d.updated_at.isoformat(),
            'updated_by': d.updated_by_name,
        })

    if full_name and gh.is_configured():
        remote = []
        readme = gh.get_file(full_name, 'README.md')
        if readme and 'README.md' not in seen:
            remote.append({'path': 'README.md',
                           'title': _title_of(readme, full_name),
                           'body': readme, 'source': 'repo', 'order': -1})
        for f in sorted(gh.list_dir(full_name, 'docs'), key=lambda x: x['name']):
            if not f['name'].lower().endswith(('.md', '.markdown')):
                continue
            if f['path'] in seen:
                continue
            text = gh.get_file(full_name, f['path'])
            if text:
                remote.append({'path': f['path'],
                               'title': _title_of(text, f['name']),
                               'body': text, 'source': 'repo', 'order': 0})
        pages.extend(remote)

    # README first whatever it came from, then the explicit order, then path.
    pages.sort(key=lambda p: (p['path'] != 'README.md', p.get('order', 0),
                              p['path']))
    return pages


def _title_of(markdown, fallback):
    """The document's own H1, falling back to its filename."""
    for line in markdown.splitlines():
        if line.startswith('# '):
            return line[2:].strip()
    return fallback.rsplit('/', 1)[-1].rsplit('.', 1)[0].replace('-', ' ').title()
