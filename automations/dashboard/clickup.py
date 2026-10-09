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
import re
import threading
import time

import requests
from django.db import close_old_connections, connections
from django.utils import timezone

logger = logging.getLogger(__name__)

API = 'https://api.clickup.com/api/v2'
TIMEOUT = 20

# What each tracker status *means*, independent of what any particular ClickUp
# list happens to call its columns.
#
# A hardcoded map does not survive contact with real lists: ClickUp lets every
# list define its own statuses, and the Candidate Portal list uses "portal
# backlog / building portal / testing access / ready to launch / launched",
# which shares not one name with the workspace defaults. So a tracker status is
# resolved against the statuses of the list being written to, by name where the
# names agree and by ClickUp's own open/custom/closed typing where they do not.
#
# INTENT is that meaning: where in the arc of work this status sits.
NOT_STARTED, ACTIVE, BLOCKED, DONE, DROPPED = (
    'not_started', 'active', 'blocked', 'done', 'dropped')

INTENT = {
    'backlog': NOT_STARTED,
    'todo': NOT_STARTED,
    'in_progress': ACTIVE,
    'in_progress_guidance': BLOCKED,
    'review': ACTIVE,
    'review_pending': ACTIVE,
    'discrepancy': BLOCKED,
    'on_hold': BLOCKED,
    'cancelled': DROPPED,
    'done': DONE,
}

# Tried before falling back to typing, so a list that does use familiar words
# gets the obvious column rather than merely a plausible one.
SYNONYMS = {
    'backlog': ('to do', 'todo', 'backlog', 'open', 'new'),
    'todo': ('to do', 'todo', 'open', 'planning', 'next'),
    'in_progress': ('in progress', 'doing', 'active', 'building', 'wip'),
    'in_progress_guidance': ('at risk', 'blocked', 'guidance required',
                             'waiting', 'on hold'),
    'review': ('review', 'in review', 'testing', 'qa', 'update required'),
    'review_pending': ('review', 'in review', 'testing', 'qa',
                       'update required'),
    'discrepancy': ('at risk', 'update required', 'blocked', 'review'),
    'on_hold': ('on hold', 'hold', 'paused', 'blocked', 'at risk'),
    'cancelled': ('cancelled', 'canceled', 'dropped', 'wont do', "won't do"),
    'done': ('complete', 'completed', 'done', 'launched', 'closed', 'live'),
}


# ClickUp priorities are 1 urgent .. 4 low.
PRIORITY_MAP = {'critical': 1, 'high': 2, 'medium': 3, 'low': 4}


def in_background(work):
    """Run `work` on a thread that can actually reach the database.

    Django ties a connection to the thread that opened it and only tidies them
    up around a request. A background thread therefore starts with whatever it
    inherited - on the scheduler's long-lived thread that is a connection the
    server closed hours ago, which is why every pull failed with "connection
    already closed" and the inbound sync never ran on the server at all.

    close_old_connections() discards anything unusable so Django opens a fresh
    one; closing at the end stops a short-lived thread leaving a connection
    behind on every push.
    """
    def run():
        close_old_connections()
        try:
            work()
        finally:
            connections.close_all()
    return run


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


# Statuses change rarely and are needed on every push, so they are held briefly
# rather than fetched each time. Short enough that editing a list's columns is
# picked up within the minute.
_STATUS_CACHE = {}
_STATUS_TTL = 60


def list_statuses(list_id):
    """The statuses this list actually offers, newest-known first."""
    hit = _STATUS_CACHE.get(list_id)
    if hit and (time.time() - hit[0]) < _STATUS_TTL:
        return hit[1]
    data = _request('GET', f'/list/{list_id}')
    rows = [
        {'status': st['status'],
         'type': st.get('type', 'custom'),
         'order': st.get('orderindex', 0)}
        for st in (data.get('statuses') or [])
    ]
    rows.sort(key=lambda r: r['order'])
    _STATUS_CACHE[list_id] = (time.time(), rows)
    return rows


def resolve_status(tracker_status, statuses):
    """Which of this list's statuses best expresses a tracker status.

    Returns None when the list offers nothing honest, in which case the push
    leaves the status alone rather than guessing.

    Name first, so a list using ordinary words gets the obvious column. Then
    ClickUp's own typing: `open` is where work starts, `closed` is where it
    ends, and the custom columns in between are the middle of the arc.

    Two rules exist because the obvious version got them wrong:

    * Names are matched on whole words. Matching on any substring made "todo"
      choose "ready to launch", because the synonym "ready" is a prefix of it.
    * Cancelled work is never mapped onto a `closed` column by typing alone. On
      a list whose only closed column is "launched", that reported dropped work
      as shipped - the same misreport, in the other direction, as marking
      review-pending work complete.
    """
    if not statuses:
        return None
    by_name = {r['status'].strip().lower(): r['status'] for r in statuses}

    def whole_word(needle, haystack):
        return re.search(rf'(?<![a-z0-9]){re.escape(needle)}(?![a-z0-9])',
                         haystack) is not None

    for want in SYNONYMS.get(tracker_status, ()):
        if want in by_name:
            return by_name[want]
        for name, original in by_name.items():
            if whole_word(want, name):
                return original

    intent = INTENT.get(tracker_status, NOT_STARTED)
    opens = [r for r in statuses if r['type'] == 'open']
    closed = [r for r in statuses if r['type'] == 'closed']
    middle = [r for r in statuses if r['type'] not in ('open', 'closed')]

    if intent == DROPPED:
        # No column means cancelled here. Saying "launched" would be a lie, and
        # saying "backlog" would undo real progress, so the status is left as
        # it is and only the rest of the task is updated.
        return None
    if intent == DONE:
        return (closed or statuses[-1:])[0]['status']
    if intent == NOT_STARTED:
        return (opens or statuses[:1])[0]['status']
    # Active and blocked both mean "underway". Blocked has no column of its own
    # on a list like this, and the earlier version chose the *last* middle
    # column for it, which read as nearly finished. The first one is the honest
    # choice: work has started, nothing more is claimed.
    return (middle or opens or statuses[:1])[0]['status']


def _payload(task, list_id):
    body = {
        'name': task.title[:255],
        'description': task.description or '',
        'priority': PRIORITY_MAP.get(task.priority),
    }
    status = resolve_status(task.status, list_statuses(list_id))
    if status:
        body['status'] = status
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

    body = _payload(task, list_id)
    wanted = assignee_ids(task)

    if task.clickup_task_id:
        # Updating takes a diff, not a list - sending a list silently does
        # nothing, which is why assignment appeared to work on create and not
        # on edit. Whoever is on the task there but not here is removed, so the
        # tracker stays the authority on who is doing the work.
        current = []
        try:
            now = _request('GET', f'/task/{task.clickup_task_id}')
            current = [str(a['id']) for a in (now.get('assignees') or [])]
        except ClickUpError:
            current = []
        add = [i for i in wanted if i not in current]
        rem = [i for i in current if i not in wanted]
        if add or rem:
            body['assignees'] = {'add': add, 'rem': rem}
        _request('PUT', f'/task/{task.clickup_task_id}', json=body)
    else:
        if wanted:
            body['assignees'] = wanted
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

    threading.Thread(target=in_background(run), daemon=True).start()


# ══════════════════════════════════════════════════════════════════════════════
# People
# ══════════════════════════════════════════════════════════════════════════════
# A tracker account is a username; a ClickUp member is an email address. Nothing
# guarantees the same person has both, or that the two agree, so assignment is
# matched on the one thing they can share - the email - and falls back to a
# mapping somebody sets by hand.
#
# When no match can be found the ClickUp task is left unassigned rather than
# given to whoever happens to be first. An unassigned task is obviously
# incomplete; a task assigned to the wrong person looks finished and is acted on
# by the wrong people.

_MEMBER_CACHE = {}
_MEMBER_TTL = 300


def members():
    """Everyone in the ClickUp workspace: [{id, email, name}]."""
    hit = _MEMBER_CACHE.get('all')
    if hit and (time.time() - hit[0]) < _MEMBER_TTL:
        return hit[1]
    rows = []
    for team in _request('GET', '/team').get('teams', []):
        for m in team.get('members', []):
            u = m.get('user') or {}
            if u.get('id') is None:
                continue
            rows.append({
                'id': str(u['id']),
                'email': (u.get('email') or '').strip().lower(),
                'name': u.get('username') or u.get('email') or str(u['id']),
            })
    _MEMBER_CACHE['all'] = (time.time(), rows)
    return rows


def clickup_id_for_user(user):
    """This person's ClickUp member id, or '' if they have no counterpart.

    An explicit mapping wins over the email, because it was set by somebody who
    knew; the email is only a guess that happens to be usually right.
    """
    profile = getattr(user, 'profile', None)
    explicit = (getattr(profile, 'clickup_user_id', '') or '').strip()
    if explicit:
        return explicit
    email = (user.email or '').strip().lower()
    if not email:
        return ''
    for m in members():
        if m['email'] and m['email'] == email:
            return m['id']
    return ''


def assignee_ids(task):
    """ClickUp member ids for whoever this task is assigned to here."""
    out = []
    for user in task.assigned_users.all():
        cid = clickup_id_for_user(user)
        if cid and cid not in out:
            out.append(cid)
    return out


def user_for_clickup_id(cid):
    """The tracker account for a ClickUp member, or None."""
    from django.contrib.auth.models import User
    cid = str(cid)
    hit = User.objects.filter(profile__clickup_user_id=cid).first()
    if hit:
        return hit
    for m in members():
        if m['id'] == cid and m['email']:
            return User.objects.filter(email__iexact=m['email']).first()
    return None


# ══════════════════════════════════════════════════════════════════════════════
# Pulling tasks created in ClickUp
# ══════════════════════════════════════════════════════════════════════════════
# Work gets filed on both sides: planned here, but raised in ClickUp by whoever
# is in ClickUp at the time. A task added there now appears in its project here.
#
# Only creation is pulled. Editing an existing task from ClickUp as well would
# put the two systems in a fight over the same row - the push would send it
# back, the pull would read it again - and nothing in the design says which
# should win. The tracker stays the source of truth for a task that already
# exists; ClickUp can only add.


# Set while a pull is writing, so the post_save signal does not push the row
# straight back to where it came from. Thread-local because the pull runs on a
# background thread while requests are being served on others.
_quiet = threading.local()


class suppress_push:
    """Writes inside this block do not trigger a push back to ClickUp."""

    def __enter__(self):
        _quiet.on = True
        return self

    def __exit__(self, *exc):
        _quiet.on = False
        return False


def push_suppressed():
    return getattr(_quiet, 'on', False)


# Which tracker status a ClickUp column means. The reverse of resolve_status,
# and necessarily coarser: a list with five bespoke columns cannot say which of
# the tracker's ten states it meant, so this picks the honest general one and
# lets somebody refine it here if they care.
def reverse_status(name, statuses):
    low = (name or '').strip().lower()
    typed = {r['status'].strip().lower(): r['type'] for r in (statuses or [])}
    kind = typed.get(low, 'custom')

    if kind == 'closed':
        return 'done'
    if kind == 'open':
        return 'backlog'
    for word, tracker in (
            ('review', 'review'), ('test', 'review'), ('qa', 'review'),
            ('hold', 'on_hold'), ('block', 'on_hold'), ('risk', 'on_hold'),
            ('cancel', 'cancelled'),
    ):
        if word in low:
            return tracker
    return 'in_progress'


REVERSE_PRIORITY = {1: 'critical', 2: 'high', 3: 'medium', 4: 'low'}


def _date_from_ms(value):
    """ClickUp sends dates as epoch milliseconds, as a string, or not at all."""
    if value in (None, '', 0, '0'):
        return None
    try:
        return timezone.datetime.fromtimestamp(int(value) / 1000).date()
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def pull_list(meta):
    """Create tracker tasks for anything in this project's ClickUp list we do
    not already have. Returns how many were added."""
    from .models import ProjectTask

    data = _request(
        'GET', f'/list/{meta.clickup_list_id}/task'
               '?archived=false&include_closed=true&subtasks=true')
    remote = data.get('tasks', [])
    removed = reap_deleted(meta, [r['id'] for r in remote])
    if not remote:
        return 0, removed

    known = set(ProjectTask.objects
                .exclude(clickup_task_id='')
                .values_list('clickup_task_id', flat=True))
    statuses = list_statuses(meta.clickup_list_id)

    added = 0
    for row in remote:
        if row['id'] in known:
            continue
        people = [u for u in (user_for_clickup_id(a['id'])
                              for a in (row.get('assignees') or [])) if u]
        with suppress_push():
            rec = ProjectTask.objects.create(
                title=(row.get('name') or 'Untitled')[:255],
                description=row.get('description') or '',
                status=reverse_status(row['status']['status'], statuses),
                priority=REVERSE_PRIORITY.get(
                    int((row.get('priority') or {}).get('id', 3) or 3), 'medium'),
                project_name=meta.name,
                # Dates were going out but never coming back, so anything given
                # a due date in ClickUp arrived here with none.
                start_date=_date_from_ms(row.get('start_date')),
                end_date=_date_from_ms(row.get('due_date')),
                clickup_task_id=row['id'],
                clickup_synced_at=timezone.now(),
                clickup_dirty=False,
            )
            if people:
                rec.assigned_users.set(people)
        added += 1
        logger.info('Pulled ClickUp task %s into %s', row['id'], meta.name)
    return added, removed


def task_is_gone(clickup_task_id):
    """True only when ClickUp says that task no longer exists.

    Absence from a list is not proof of deletion - a task moved to another list
    disappears from this one exactly the same way. Deleting the tracker's copy
    on that evidence would destroy real work over a drag-and-drop, so the task
    is asked for directly and only a 404 counts.
    """
    try:
        _request('GET', f'/task/{clickup_task_id}')
        return False
    except ClickUpError as exc:
        return '404' in str(exc)


def reap_deleted(meta, remote_ids):
    """Remove tracker tasks whose ClickUp twin has been deleted.

    Returns how many went. Only tasks this project put in ClickUp are
    considered - one that was never pushed has no twin to lose.
    """
    from .models import ProjectTask

    candidates = (ProjectTask.objects
                  .filter(project_name=meta.name)
                  .exclude(clickup_task_id='')
                  .exclude(clickup_task_id__in=remote_ids))
    removed = 0
    for rec in candidates:
        if not task_is_gone(rec.clickup_task_id):
            # Still exists somewhere else in ClickUp - moved, not deleted.
            continue
        with suppress_push():
            rec.delete()
        removed += 1
        logger.info('Removed %s: its ClickUp task %s was deleted',
                    rec.title, rec.clickup_task_id)
    return removed


def pull_all():
    """Every linked project. Returns (added, removed, failed_projects)."""
    if not configured():
        return 0, 0, 0
    from .models import ProjectMeta

    added = removed = failed = 0
    for meta in ProjectMeta.objects.exclude(clickup_list_id=''):
        try:
            got, gone = pull_list(meta)
            added += got
            removed += gone
        except ClickUpError as exc:
            failed += 1
            logger.warning('ClickUp pull failed for %s: %s', meta.name, exc)
        except Exception:
            failed += 1
            logger.exception('ClickUp pull crashed for %s', meta.name)
    return added, removed, failed


def pull_soon():
    """Ask ClickUp for new tasks now, without making the caller wait.

    Opening the ClickUp page is a good moment to check: somebody looking at the
    sync is the person most likely to have just added something over there.
    """
    if not configured():
        return
    threading.Thread(target=in_background(pull_all), daemon=True).start()


def push_project_soon(project_name):
    """Push a whole project's backlog in the background.

    Linking a project queues every task it already has. Waiting for the next
    five-minute sweep to notice is what made a manual "sync now" feel
    necessary, so linking starts the work immediately instead.
    """
    if not configured():
        return

    def run():
        from .models import ProjectTask
        ids = list(ProjectTask.objects
                   .filter(project_name=project_name, clickup_dirty=True)
                   .values_list('pk', flat=True))
        for pk in ids:
            rec = ProjectTask.objects.filter(pk=pk).first()
            if rec is None:
                continue
            try:
                push_task(rec)
            except ClickUpError as exc:
                ProjectTask.objects.filter(pk=pk).update(
                    clickup_error=str(exc)[:500])
                logger.warning('ClickUp push failed for task %s: %s', pk, exc)
            except Exception:
                logger.exception('ClickUp push crashed for task %s', pk)

    threading.Thread(target=in_background(run), daemon=True).start()


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
