"""Recording what people and agents do, and reading it back.

## The one rule

**Recording must never break the thing being recorded.** Every call here is
wrapped: if writing the entry fails, the task still saves and the repository
still gets created. An audit trail that can take the feature down with it is a
worse trade than a missing line in a feed, so `record()` logs and returns
rather than raising.

## What gets recorded

Actions somebody took, not state the system computed. "Ethan completed task
'K9 Report'" is an event; "5 tasks are overdue" is a query, and belongs in a
report. The test is whether a person did it on purpose.
"""
import logging

from django.db.models import Q

from .models import Activity

logger = logging.getLogger(__name__)


def record(request, verb, object_type, *, obj=None, label='', detail='',
           project='', object_id=None):
    """Write one entry. Never raises.

    `request` supplies the actor. A token-authenticated call carries the token
    on `request.api_token`, set by the public API's auth, so an agent's work is
    marked as such instead of looking like the user sat down and did it.
    """
    try:
        user = getattr(request, 'user', None)
        if user is not None and not getattr(user, 'is_authenticated', False):
            user = None

        token = getattr(request, 'api_token', None)
        if token is not None and user is None:
            user = token.user

        Activity.objects.create(
            actor=user,
            actor_name=_name_of(user),
            verb=verb,
            object_type=object_type,
            object_id=object_id if object_id is not None else getattr(obj, 'id', None),
            object_label=(label or str(obj or ''))[:300],
            detail=detail[:300],
            project=project[:200],
            source='api' if token is not None else 'web',
            via=(token.name if token is not None else '')[:120],
        )
    except Exception:                                    # noqa: BLE001
        # Deliberately broad: see the module docstring. Nothing about writing
        # an audit line is worth failing a user's action over.
        logger.exception('[activity] could not record %s %s', verb, object_type)


def _name_of(user):
    if user is None:
        return ''
    return (user.get_full_name() or user.username or '')[:150]


def feed(*, limit=50, actor=None, object_type='', since=None, search=''):
    """Recent entries, newest first, as dicts ready to serialise."""
    qs = Activity.objects.select_related('actor')
    if actor:
        # Either a username or a display name - callers asking "what did Ethan
        # do" have one or the other, rarely an id.
        qs = qs.filter(Q(actor__username__iexact=actor)
                       | Q(actor_name__icontains=actor))
    if object_type:
        qs = qs.filter(object_type=object_type)
    if since:
        qs = qs.filter(created_at__gte=since)
    if search:
        qs = qs.filter(Q(object_label__icontains=search)
                       | Q(detail__icontains=search)
                       | Q(project__icontains=search))
    return [_out(a) for a in qs[:max(1, min(limit, 500))]]


def _out(a):
    return {
        'id': a.id,
        'sentence': a.sentence(),
        'actor': a.actor_name,
        'username': a.actor.username if a.actor else '',
        'verb': a.verb,
        'object_type': a.object_type,
        'object_id': a.object_id,
        'object_label': a.object_label,
        'detail': a.detail,
        'project': a.project,
        'source': a.source,
        'via': a.via,
        'at': a.created_at.isoformat(),
    }


def summary(entries):
    """Group a feed into one line per person: "Ethan added 3 tasks, completed 1".

    This is the shape a question like "what did the team do today" actually
    wants - a list of forty individual lines is the same information, but
    nobody reads it.
    """
    people = {}
    for e in entries:
        who = e['actor'] or 'Someone'
        bucket = people.setdefault(who, {'actor': who, 'count': 0, 'by_verb': {},
                                         'latest': e['at'], 'items': []})
        bucket['count'] += 1
        bucket['by_verb'][(e['verb'], e['object_type'])] = \
            bucket['by_verb'].get((e['verb'], e['object_type']), 0) + 1
        # The same task edited five times should not fill the line with five
        # copies of its name.
        if len(bucket['items']) < 5 and e['object_label'] \
                and e['object_label'] not in bucket['items']:
            bucket['items'].append(e['object_label'])

    out = []
    for b in people.values():
        parts = [f'{verb} {n} {_plural(obj, n)}'
                 for (verb, obj), n in sorted(
                     b['by_verb'].items(), key=lambda x: (_VERB_ORDER.get(x[0][0], 9),
                                                          x[0][1]))]
        out.append({
            **b,
            # Tuple keys do not survive JSON; the readable sentence is the point.
            'by_verb': {f'{v} {o}': n for (v, o), n in b['by_verb'].items()},
            'sentence': f'{b["actor"]} {_join(parts)}',
        })
    return sorted(out, key=lambda b: -b['count'])


# Read in the order work happens, not by how many of each there were - so the
# same person's line has the same shape every day.
_VERB_ORDER = {'created': 0, 'updated': 1, 'completed': 2, 'reopened': 3,
               'sent': 4, 'imported': 5, 'deleted': 6}


def _plural(noun, n):
    if n == 1:
        return noun
    return noun + ('es' if noun.endswith(('s', 'x', 'ch')) else 's')


def _join(parts):
    """"a, b and c" - an Oxford-comma-free list, because it is read aloud."""
    if len(parts) <= 1:
        return parts[0] if parts else 'did nothing'
    return f'{", ".join(parts[:-1])} and {parts[-1]}'
