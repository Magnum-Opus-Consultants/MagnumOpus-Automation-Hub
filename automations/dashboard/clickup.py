"""Mirror Project Tracker tasks into ClickUp.

One way, deliberately. The tracker is where the work is planned and the status
is set; ClickUp is where the rest of the business looks. Pushing one way means
there is never a question of which side won, and a ClickUp edit that gets
overwritten on the next push is the documented behaviour rather than a bug.

Three rules shape everything here:

* A save must never fail because ClickUp is unreachable. Pushes happen after
  the response is on its way, and a failure marks the task dirty instead of
  raising. The scheduled retry picks it up.
* Only linked projects sync. A project with no `clickup_list_id` is skipped
  entirely, so turning this on cannot fill somebody's board with tasks they
  did not ask for.
* The token is read from the environment, never stored in the database or the
  repository, and never returned by any endpoint.
"""
import logging
import os
import threading

import requests
from django.utils import timezone

logger = logging.getLogger(__name__)

API = 'https://api.clickup.com/api/v2'
TIMEOUT = 20

# ClickUp's own statuses, as configured on every space in this workspace:
#   to do, planning, in progress, at risk, update required, on hold,
#   complete, cancelled
#
# The tracker draws finer distinctions than ClickUp does, and the qualified
# states are the point of it: "completed, review pending" and "completed,
# addressing a data discrepancy" are the difference between work being done and
# work being accepted. ClickUp has no equivalent, so they map to "update
# required" rather than "complete" - showing them as complete over there is
# exactly the misreport the tracker exists to avoid.
STATUS_MAP = {
    'backlog': 'to do',
    'todo': 'to do',
    'in_progress': 'in progress',
    'in_progress_guidance': 'at risk',
    'review': 'update required',
    'review_pending': 'update required',
    'discrepancy': 'update required',
    'on_hold': 'on hold',
    'cancelled': 'cancelled',
    'done': 'complete',
}

# ClickUp priorities are 1 urgent .. 4 low.
PRIORITY_MAP = {'critical': 1, 'high': 2, 'medium': 3, 'low': 4}


class ClickUpError(RuntimeError):
    """A push did not happen. Carries a message fit to show in the UI."""


def token():
    """The API token, or '' when the integration is not configured."""
    return (os.getenv('CLICKUP_API_TOKEN') or '').strip()


def configured():
    return bool(token())


def _request(method, path, **kwargs):
    tok = token()
    if not tok:
        raise ClickUpError(
            'No ClickUp token. Set CLICKUP_API_TOKEN in the .env file.')
    try:
        resp = requests.request(
            method, f'{API}{path}',
            headers={'Authorization': tok, 'Content-Type': 'application/json'},
            timeout=TIMEOUT, **kwargs)
    except requests.RequestException as exc:
        raise ClickUpError(f'Could not reach ClickUp: {exc}') from exc

    if resp.status_code == 401:
        raise ClickUpError('ClickUp rejected the token. It may have been '
                           'regenerated - update CLICKUP_API_TOKEN.')
    if resp.status_code == 429:
        raise ClickUpError('ClickUp rate limit reached. The retry will pick '
                           'this up.')
    if resp.status_code >= 400:
        detail = ''
        try:
            detail = resp.json().get('err') or resp.text[:200]
        except ValueError:
            detail = resp.text[:200]
        raise ClickUpError(f'ClickUp returned {resp.status_code}: {detail}')

    if not resp.content:
        return {}
    try:
        return resp.json()
    except ValueError:
        return {}


# ══════════════════════════════════════════════════════════════════════════════
# Reading the workspace, for the list picker
# ══════════════════════════════════════════════════════════════════════════════

def workspace_tree():
    """Spaces, their folders and every list, for choosing where a project goes.

    One call per space and folder level - ClickUp has no endpoint that returns
    the whole tree - so this is cached by the caller rather than fetched on
    every page load.
    """
    teams = _request('GET', '/team').get('teams', [])
    out = []
    for team in teams:
        spaces = _request('GET', f"/team/{team['id']}/space?archived=false")
        space_rows = []
        for sp in spaces.get('spaces', []):
            lists = []
            folders = _request('GET', f"/space/{sp['id']}/folder?archived=false")
            for f in folders.get('folders', []):
                for l in f.get('lists', []):
                    lists.append({'id': l['id'],
                                  'name': f"{f['name']} / {l['name']}"})
            loose = _request('GET', f"/space/{sp['id']}/list?archived=false")
            for l in loose.get('lists', []):
                lists.append({'id': l['id'], 'name': l['name']})
            space_rows.append({'id': sp['id'], 'name': sp['name'],
                               'lists': lists})
        out.append({'id': team['id'], 'name': team['name'],
                    'spaces': space_rows})
    return out


# ══════════════════════════════════════════════════════════════════════════════
# Pushing a task
# ══════════════════════════════════════════════════════════════════════════════

def _list_for(task):
    """The ClickUp list this task belongs in, or '' when it is not linked."""
    if not task.project_name:
        return ''
    # Imported here rather than at module scope to keep this module importable
    # from models-adjacent code without a circular import.
    from .models import ProjectMeta
    meta = ProjectMeta.objects.filter(name=task.project_name).first()
    return (meta.clickup_list_id or '') if meta else ''


def _payload(task):
    body = {
        'name': task.title[:255],
        'description': task.description or '',
        'status': STATUS_MAP.get(task.status, 'to do'),
        'priority': PRIORITY_MAP.get(task.priority),
    }
    # ClickUp takes epoch milliseconds, and rejects a null due date differently
    # from an absent one, so absent is what we send when there is no date.
    if task.end_date:
        body['due_date'] = int(
            timezone.datetime.combine(
                task.end_date, timezone.datetime.min.time()).timestamp() * 1000)
    if task.start_date:
        body['start_date'] = int(
            timezone.datetime.combine(
                task.start_date, timezone.datetime.min.time()).timestamp() * 1000)
    return body


def push_task(task):
    """Create or update this task's twin. Raises ClickUpError on failure.

    Returns False when there is nothing to do - an unlinked project, or the
    integration switched off - which is not an error and should not be recorded
    as one.
    """
    if not configured():
        return False
    list_id = _list_for(task)
    if not list_id:
        return False

    body = _payload(task)
    if task.clickup_task_id:
        _request('PUT', f'/task/{task.clickup_task_id}', json=body)
    else:
        created = _request('POST', f'/list/{list_id}/task', json=body)
        task.clickup_task_id = created.get('id', '')

    task.clickup_synced_at = timezone.now()
    task.clickup_dirty = False
    task.clickup_error = ''
    task.save(update_fields=['clickup_task_id', 'clickup_synced_at',
                             'clickup_dirty', 'clickup_error'])
    return True


def delete_task_id(clickup_task_id):
    """Remove a twin whose tracker task has been deleted."""
    if not configured() or not clickup_task_id:
        return False
    _request('DELETE', f'/task/{clickup_task_id}')
    return True


# ══════════════════════════════════════════════════════════════════════════════
# Fire and forget, plus the retry that makes it safe
# ══════════════════════════════════════════════════════════════════════════════

def push_soon(task):
    """Push without making the caller wait, and without letting it fail.

    The request that saved the task has already done its job; a slow or broken
    ClickUp must not turn that into an error for the person who pressed save.
    A failure is written onto the task so the UI can show it and the scheduled
    retry can pick it up.
    """
    if not configured():
        return
    task_id = task.pk

    # Marked dirty *before* the push, not only when one fails. A background
    # thread can die without running its own error handling - the process
    # exits, or gunicorn recycles the worker mid-request - and a task that was
    # never marked would then never be retried, which is the one way this
    # design could lose an update silently. Dirty-first means the worst case is
    # a redundant push, not a missing one.
    from .models import ProjectTask
    ProjectTask.objects.filter(pk=task_id).update(clickup_dirty=True)

    def run():
        rec = ProjectTask.objects.filter(pk=task_id).first()
        if rec is None:
            return
        try:
            push_task(rec)
        except ClickUpError as exc:
            ProjectTask.objects.filter(pk=task_id).update(
                clickup_dirty=True, clickup_error=str(exc)[:500])
            logger.warning('ClickUp push failed for task %s: %s', task_id, exc)
        except Exception:
            ProjectTask.objects.filter(pk=task_id).update(
                clickup_dirty=True,
                clickup_error='Unexpected error pushing to ClickUp.')
            logger.exception('ClickUp push crashed for task %s', task_id)

    threading.Thread(target=run, daemon=True).start()


def mark_dirty(task):
    """Record that a task needs pushing, without pushing it yet."""
    from .models import ProjectTask
    ProjectTask.objects.filter(pk=task.pk).update(clickup_dirty=True)


def retry_dirty(limit=50):
    """Push everything still waiting. Returns (pushed, failed).

    Run on a schedule, so a ClickUp outage costs a delay rather than a lost
    update. Bounded per run to stay inside the rate limit.
    """
    if not configured():
        return 0, 0
    from .models import ProjectTask

    pushed = failed = 0
    stale = (ProjectTask.objects
             .filter(clickup_dirty=True)
             .exclude(project_name='')
             .order_by('clickup_synced_at')[:limit])
    for rec in stale:
        try:
            if push_task(rec):
                pushed += 1
        except ClickUpError as exc:
            failed += 1
            ProjectTask.objects.filter(pk=rec.pk).update(
                clickup_error=str(exc)[:500])
        except Exception:
            failed += 1
            logger.exception('ClickUp retry crashed for task %s', rec.pk)
    if pushed or failed:
        logger.info('ClickUp retry: %s pushed, %s failed', pushed, failed)
    return pushed, failed
