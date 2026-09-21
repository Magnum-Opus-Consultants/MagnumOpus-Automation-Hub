"""Talk to GitHub: create repositories, and read their commits.

## Why not a library

Three endpoints, no pagination beyond a page size, no OAuth dance. PyGithub
would be a dependency and a vendored API surface for about eighty lines of
urllib.

## The account

The token is a fine-grained one belonging to the **user** account
`Magnum-Opus-Consultants` - not an organisation, despite the name. That
distinction decides the endpoint: a user's repositories are created at
`POST /user/repos`, an organisation's at `POST /orgs/{org}/repos`, and using
the wrong one returns a 404 that looks like a permissions problem. `_is_org()`
settles it once rather than guessing.

## Failure

Every call returns `(ok, payload)` instead of raising. A GitHub outage or a
revoked token should surface in the page as a message about GitHub, not as a
500 that looks like the platform is broken.
"""
import json
import logging
import os
import urllib.error
import urllib.request

logger = logging.getLogger(__name__)

API = 'https://api.github.com'
TIMEOUT = 25


def token():
    return os.getenv('GITHUB_TOKEN', '').strip()


def owner():
    return os.getenv('GITHUB_OWNER', '').strip()


def is_configured():
    return bool(token() and owner())


def _request(method, path, body=None):
    """One call. Returns (ok, payload); payload is the error dict on failure."""
    if not token():
        return False, {'message': 'No GitHub token is configured on this server.'}

    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f'{API}{path}', data=data, method=method,
        headers={
            'Authorization': f'Bearer {token()}',
            'Accept': 'application/vnd.github+json',
            'X-GitHub-Api-Version': '2022-11-28',
            'User-Agent': 'Sentinel',
            **({'Content-Type': 'application/json'} if data else {}),
        })
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
            raw = r.read().decode()
            return True, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        try:
            payload = json.loads(e.read().decode() or '{}')
        except ValueError:
            payload = {}
        payload.setdefault('message', f'GitHub returned {e.code}.')
        payload['status'] = e.code
        logger.warning('[github] %s %s -> %s %s', method, path, e.code,
                       payload.get('message'))
        return False, payload
    except (urllib.error.URLError, TimeoutError) as e:
        logger.warning('[github] %s %s unreachable: %s', method, path, e)
        return False, {'message': f'Could not reach GitHub: {e}'}


def _is_org():
    """Whether GITHUB_OWNER names an organisation rather than a user."""
    ok, _ = _request('GET', f'/orgs/{owner()}')
    return ok


def whoami():
    """Who the token authenticates as, for the settings page to show."""
    ok, body = _request('GET', '/user')
    if not ok:
        return False, body
    return True, {'login': body.get('login'), 'name': body.get('name'),
                  'type': body.get('type'), 'html_url': body.get('html_url')}


def list_repos(limit=100):
    ok, body = _request(
        'GET', f'/user/repos?per_page={min(limit, 100)}&sort=updated'
               '&affiliation=owner,organization_member')
    if not ok:
        return False, body
    return True, [{
        'name': r['name'],
        'full_name': r['full_name'],
        'private': r['private'],
        'url': r['html_url'],
        'default_branch': r.get('default_branch') or 'main',
        'description': r.get('description') or '',
        'pushed_at': r.get('pushed_at'),
    } for r in body]


def create_repo(name, description='', private=True, auto_init=True):
    """Make a repository on the configured account.

    `auto_init` writes a README so the repo has a commit and therefore a
    default branch - without it, the repo exists but every later call about
    its branch or commits returns "Git Repository is empty", which reads as a
    bug rather than an empty repo.
    """
    payload = {'name': name, 'description': description,
               'private': bool(private), 'auto_init': bool(auto_init)}
    path = f'/orgs/{owner()}/repos' if _is_org() else '/user/repos'
    ok, body = _request('POST', path, payload)
    if not ok:
        # GitHub reports a name clash inside `errors`, which is more use than
        # the generic "Repository creation failed" at the top level.
        detail = body.get('message', '')
        for err in body.get('errors') or []:
            if err.get('message'):
                detail = err['message']
        return False, {'message': detail or 'Could not create the repository.'}
    return True, {
        'name': body['name'],
        'full_name': body['full_name'],
        'url': body['html_url'],
        'clone_url': body['clone_url'],
        'ssh_url': body['ssh_url'],
        'private': body['private'],
        'default_branch': body.get('default_branch') or 'main',
    }


def delete_repo(full_name):
    """Delete a repository on GitHub. There is no undo, on GitHub or here.

    Needs Administration: write on the token. A 403 here almost always means
    the token was scoped without it rather than anything being wrong with the
    repository, so that case is named rather than passed through raw.
    """
    ok, body = _request('DELETE', f'/repos/{full_name}')
    if ok:
        return True, {'deleted': full_name}
    if body.get('status') == 403:
        return False, {'message': 'The GitHub token is not allowed to delete '
                                  'repositories (it needs Administration: '
                                  'write).'}
    if body.get('status') == 404:
        return False, {'message': f'"{full_name}" no longer exists on GitHub.'}
    return False, body


def put_file(full_name, path, content, message, branch=None):
    """Create or replace a single file, committing it.

    GitHub needs the current blob's sha to overwrite a file, so an existing
    one is looked up first. Without that the write is rejected as a conflict,
    which is GitHub refusing to silently discard somebody else's change.
    """
    import base64

    ok, existing = _request('GET', f'/repos/{full_name}/contents/{path}')
    payload = {
        'message': message,
        'content': base64.b64encode(content.encode()).decode(),
    }
    if branch:
        payload['branch'] = branch
    if ok and isinstance(existing, dict) and existing.get('sha'):
        payload['sha'] = existing['sha']

    ok, body = _request('PUT', f'/repos/{full_name}/contents/{path}', payload)
    if not ok:
        return False, body
    commit = body.get('commit') or {}
    return True, {'path': path, 'sha': commit.get('sha'),
                  'url': (body.get('content') or {}).get('html_url')}


def delete_file(full_name, path, message, branch=None):
    """Remove a file, committing the deletion.

    Absent files report success: the caller asked for the file to be gone, and
    it is. Treating that as an error would make tidying up a directory fail on
    whichever file somebody had already removed by hand.
    """
    ok, existing = _request('GET', f'/repos/{full_name}/contents/{path}')
    if not ok or not isinstance(existing, dict) or not existing.get('sha'):
        return True, {'path': path, 'deleted': False, 'reason': 'not present'}

    payload = {'message': message, 'sha': existing['sha']}
    if branch:
        payload['branch'] = branch
    ok, body = _request('DELETE', f'/repos/{full_name}/contents/{path}', payload)
    if not ok:
        return False, body
    return True, {'path': path, 'deleted': True,
                  'sha': (body.get('commit') or {}).get('sha')}


def get_file(full_name, path):
    """One file's text, or None if it is not there."""
    import base64

    ok, body = _request('GET', f'/repos/{full_name}/contents/{path}')
    if not ok or not isinstance(body, dict) or 'content' not in body:
        return None
    try:
        return base64.b64decode(body['content']).decode('utf-8', 'replace')
    except (ValueError, TypeError):
        return None


def list_dir(full_name, path):
    """The files in one directory, or [] if the directory is absent."""
    ok, body = _request('GET', f'/repos/{full_name}/contents/{path}')
    if not ok or not isinstance(body, list):
        return []
    return [{'name': f['name'], 'path': f['path'], 'type': f['type'],
             'size': f.get('size', 0)}
            for f in body if f.get('type') == 'file']


def list_commits(full_name, since=None, limit=100):
    """Commits on the default branch, newest first.

    `since` is an ISO instant; GitHub takes it directly and it keeps a resync
    from walking the whole history every time.
    """
    query = f'?per_page={min(limit, 100)}'
    if since:
        query += f'&since={since}'
    ok, body = _request('GET', f'/repos/{full_name}/commits{query}')
    if not ok:
        return False, body
    out = []
    for c in body:
        commit = c.get('commit') or {}
        author = commit.get('author') or {}
        message = commit.get('message') or ''
        subject, _, detail = message.partition('\n')
        out.append({
            'sha': c['sha'],
            'short_sha': c['sha'][:7],
            'subject': subject.strip(),
            'body': detail.strip(),
            'author': author.get('name') or '',
            'email': author.get('email') or '',
            'date': author.get('date'),
            'url': c.get('html_url'),
            # The GitHub login, when the commit is tied to an account - the
            # git author name is whatever was configured locally.
            'login': (c.get('author') or {}).get('login') or '',
        })
    return True, out
