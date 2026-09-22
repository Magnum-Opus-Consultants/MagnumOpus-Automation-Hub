"""System testing: the "Management Live Sheet" workbook, as a live module.

Each engagement used to be a separate copy of an Excel pack - one sheet per
surface under test, a legend sheet defining the status vocabularies, a notes
sheet, and a dashboard of totals typed in by hand. Copying the pack per project
meant the vocabularies drifted, and the hand-typed dashboard drifted from its
own sheets: the E-Crop v2 pack shipped "Total App Items 32" above "App PASS 36".

So nothing here is stored twice. The vocabularies are model choices, and every
dashboard number is computed from the items on each request. The workbook stays
supported at the edges only - imported to seed a project, exported to send out -
and is never the source of truth in between.
"""
import io
import json
import logging
import re

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from .models import (TestProject, TestArea, TestItem, TestNote, TestVersion,
                     TestIteration)
from .views import _require_module
from . import system_testing_export as export

logger = logging.getLogger(__name__)

MODULE = 'system_testing'

# Every readiness key that counts as "signed off". Kept as a name rather than a
# literal so the dashboard and the export cannot disagree about what a pass is.
PASS_KEY = 'pass'
PENDING_RETEST_KEY = 'rectified_requires_testing'


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _choice_keys(choices):
    return [c[0] for c in choices]


def _label_map(choices):
    """Display label -> key, for reading a workbook written by hand."""
    return {label.strip().lower(): key for key, label in choices}


# Hand-typed sheets never match the legend exactly. These are the variants seen
# in the E-Crop packs; anything unrecognised falls back to the field default
# rather than silently dropping the row.
_BUCKET_ALIASES = {
    'in scope': 'in_scope_change',
    'in-scope change': 'in_scope_change',
    'developer enhancement': 'developer_enhancement',
    'developer enhancements': 'developer_enhancement',
    'enhancement': 'developer_enhancement',
}
_DEV_ALIASES = {
    # The legend sheet itself carries this typo.
    'in progresss': 'in_progress',
    'done and internally tested': 'done_internally_tested',
    'done & internally tested': 'done_internally_tested',
    'rectified and requires testing': 'rectified_requires_testing',
}
_READY_ALIASES = {
    'requires action': 'requires_action',
    'require action': 'requires_action',
    'pass': 'pass',
    'outstanding': 'outstanding',
}
_TESTED_ALIASES = {
    'tested': 'tested',
    'not tested': 'not_tested',
    'untested': 'not_tested',
}


def _coerce(value, choices, aliases, default):
    """Map a free-text cell onto a choice key, tolerantly."""
    if value is None:
        return default
    raw = str(value).strip().lower()
    if not raw:
        return default
    direct = _label_map(choices)
    if raw in direct:
        return direct[raw]
    if raw in aliases:
        return aliases[raw]
    if raw in _choice_keys(choices):
        return raw
    return default


# ══════════════════════════════════════════════════════════════════════════════
# Rollups - the dashboard, derived
# ══════════════════════════════════════════════════════════════════════════════

def _latest(item):
    """The most recent pass on this item, across every release."""
    rounds = list(item.iterations.all())
    return rounds[-1] if rounds else None


def _rollup(iterations):
    """Counts for one release's sheet.

    A release is the unit that gets a readiness figure: its sheet holds the
    issues outstanding when it shipped plus anything found against it, and the
    percentage says how much of that build was signed off. Rolling every release
    together would double-count an issue carried forward and never let a build
    reach 100%.
    """
    rows = list(iterations)
    total = len(rows)
    counts = {key: 0 for key in _choice_keys(TestItem.READINESS_CHOICES)}
    pending = tested = 0
    for r in rows:
        if r.readiness in counts:
            counts[r.readiness] += 1
        if r.dev_status == PENDING_RETEST_KEY:
            pending += 1
        if r.tested == 'tested':
            tested += 1
    passed = counts[PASS_KEY]

    return {
        'total': total,
        'pass': passed,
        'requires_action': counts['requires_action'],
        'outstanding': counts['outstanding'],
        'pending_retest': pending,
        'tested': tested,
        'not_tested': total - tested,
        'carried_over': sum(1 for r in rows if r.number > 1),
        # Readiness is pass over total. Zero items is 0%, not 100% - an empty
        # sheet has demonstrated nothing.
        'readiness_pct': round(passed * 100.0 / total, 1) if total else 0.0,
    }


def _latest_version(area):
    """The build this app is on now. Every area has at least one."""
    versions = list(area.versions.all())
    return versions[-1] if versions else None


def _ensure_version(area, label='Initial'):
    """An area always has somewhere to put a pass.

    A sheet belongs to a release, so an app with no release recorded gets one
    rather than having items with nowhere to live.
    """
    latest = _latest_version(area)
    if latest is None:
        latest = TestVersion.objects.create(area=area, label=label, order=0)
    return latest


def _area_rollup(area):
    """An app's headline figures come from its latest release, not its history."""
    latest = _latest_version(area)
    return _rollup(latest.iterations.all()) if latest else _rollup([])


def _sum_rollups(rollups):
    out = {k: 0 for k in ('total', 'pass', 'requires_action', 'outstanding',
                          'pending_retest', 'tested', 'not_tested',
                          'carried_over')}
    for r in rollups:
        for k in out:
            out[k] += r[k]
    out['readiness_pct'] = (
        round(out['pass'] * 100.0 / out['total'], 1) if out['total'] else 0.0)
    return out


def _date(value):
    """A date from an ISO string, or None. Assigning the raw string would leave
    the field as text until the row was read back, which breaks any formatting
    done on the instance in the same request."""
    if not value:
        return None
    if hasattr(value, 'isoformat'):
        return value
    return parse_date(str(value).strip()[:10])


def window_label(p):
    """How the testing window reads, from the dates when they are set.

    Falls back to whatever an imported pack wrote, so a project that came from a
    workbook still shows its window before anyone picks dates.
    """
    if p.window_start and p.window_end:
        if p.window_start == p.window_end:
            return p.window_start.strftime('%d %b %Y')
        if (p.window_start.year, p.window_start.month) == (p.window_end.year,
                                                           p.window_end.month):
            return (f"{p.window_start.strftime('%d')} - "
                    f"{p.window_end.strftime('%d %b %Y')}")
        return (f"{p.window_start.strftime('%d %b')} - "
                f"{p.window_end.strftime('%d %b %Y')}")
    if p.window_start:
        return f"from {p.window_start.strftime('%d %b %Y')}"
    if p.window_end:
        return f"until {p.window_end.strftime('%d %b %Y')}"
    return p.testing_window


def _versions_json(area):
    return [{'id': v.id, 'label': v.label, 'note': v.note,
             'released_on': v.released_on.isoformat() if v.released_on else None,
             'order': v.order}
            for v in area.versions.all()]


def _current_version(area):
    """The build under test right now: the last one released."""
    versions = list(area.versions.all())
    return versions[-1].label if versions else ''


def _iteration_json(r):
    return {
        'id': r.id,
        'number': r.number,
        'dev_status': r.dev_status,
        'dev_status_display': r.get_dev_status_display(),
        'tested': r.tested,
        'tested_display': r.get_tested_display(),
        'readiness': r.readiness,
        'readiness_display': r.get_readiness_display(),
        'client_feedback': r.client_feedback,
        'version': r.version_id,
        'version_label': r.version.label if r.version else '',
        'tested_on': r.tested_on.isoformat() if r.tested_on else None,
        'created_at': r.created_at.isoformat() if r.created_at else None,
    }


def _item_json(it):
    """An item, its current verdict, and every pass behind it.

    The verdict fields are flattened from the latest pass so the table can read
    them directly, while `iterations` keeps the trail of how it got there.
    """
    rounds = list(it.iterations.all())
    cur = rounds[-1] if rounds else None
    out = {
        'id': it.id,
        'issue': it.issue,
        'description': it.description,
        'bucket': it.bucket,
        'bucket_display': it.get_bucket_display(),
        'order': it.order,
        'updated_at': it.updated_at.isoformat() if it.updated_at else None,
        'iterations': [_iteration_json(r) for r in rounds],
        'iteration_count': len(rounds),
    }
    if cur:
        out.update({
            'iteration_id': cur.id,
            'dev_status': cur.dev_status,
            'dev_status_display': cur.get_dev_status_display(),
            'tested': cur.tested,
            'tested_display': cur.get_tested_display(),
            'readiness': cur.readiness,
            'readiness_display': cur.get_readiness_display(),
            'client_feedback': cur.client_feedback,
        })
    else:
        out.update({
            'iteration_id': None,
            'dev_status': 'in_progress', 'dev_status_display': 'In Progress',
            'tested': 'not_tested', 'tested_display': 'Not Tested',
            'readiness': 'requires_action',
            'readiness_display': 'REQUIRES ACTION',
            'client_feedback': '',
        })
    return out


def _sheet_json(version):
    """One release's sheet: the issues live against that build.

    An item is on a release's sheet exactly when it has a pass there, which is
    how carrying an unresolved issue forward works - the next release gets its
    own pass for the same item, and the item's trail spans both.
    """
    rows = list(version.iterations.select_related('item'))
    rows.sort(key=lambda r: (r.item.order, r.item_id))
    return {
        'version_id': version.id,
        'label': version.label,
        'note': version.note,
        'released_on': version.released_on.isoformat() if version.released_on else None,
        'rollup': _rollup(rows),
        'items': [_sheet_item_json(r) for r in rows],
    }


def _sheet_item_json(r):
    """An item as it stands on one release: the issue, plus that build's verdict."""
    it = r.item
    return {
        'id': it.id,
        'iteration_id': r.id,
        'issue': it.issue,
        'description': it.description,
        'bucket': it.bucket,
        'bucket_display': it.get_bucket_display(),
        'order': it.order,
        'updated_at': it.updated_at.isoformat() if it.updated_at else None,
        'pass_number': r.number,
        'carried_over': r.number > 1,
        'dev_status': r.dev_status,
        'dev_status_display': r.get_dev_status_display(),
        'tested': r.tested,
        'tested_display': r.get_tested_display(),
        'readiness': r.readiness,
        'readiness_display': r.get_readiness_display(),
        'client_feedback': r.client_feedback,
        # The same issue as seen on earlier builds, so a row can show where it
        # came from without another request.
        'history': [
            {'version': o.version.label, 'number': o.number,
             'readiness_display': o.get_readiness_display(),
             'dev_status_display': o.get_dev_status_display(),
             'tested_display': o.get_tested_display(),
             'client_feedback': o.client_feedback}
            for o in it.iterations.all() if o.id != r.id
        ],
    }


def _area_json(a):
    sheets = [_sheet_json(v) for v in a.versions.all()]
    latest = sheets[-1] if sheets else None
    return {
        'id': a.id,
        'name': a.name,
        'order': a.order,
        'versions': _versions_json(a),
        'current_version': _current_version(a),
        'current_version_id': latest['version_id'] if latest else None,
        'rollup': latest['rollup'] if latest else _rollup([]),
        'sheets': sheets,
    }


def _project_json(p, areas_map=None):
    """Project header plus its derived totals.

    `areas_map` lets the list endpoint prefetch every area's items once instead
    of per project.
    """
    areas = areas_map.get(p.id, []) if areas_map is not None else list(
        p.areas.prefetch_related('items'))

    area_rows, rollups = [], []
    for a in areas:
        roll = _area_rollup(a)
        rollups.append(roll)
        area_rows.append({
            'id': a.id, 'name': a.name, 'order': a.order, 'rollup': roll,
            'versions': _versions_json(a),
            'current_version': _current_version(a),
        })

    return {
        'id': p.id,
        'name': p.name,
        'client': p.client,
        'summary': p.summary,
        'testing_window': p.testing_window,
        'window_start': p.window_start.isoformat() if p.window_start else '',
        'window_end': p.window_end.isoformat() if p.window_end else '',
        'window_label': window_label(p),
        'version_label': p.version_label,
        'is_archived': p.is_archived,
        'created_at': p.created_at.isoformat() if p.created_at else None,
        'updated_at': p.updated_at.isoformat() if p.updated_at else None,
        'areas': area_rows,
        'rollup': _sum_rollups(rollups),
    }


# ══════════════════════════════════════════════════════════════════════════════
# Vocabularies
# ══════════════════════════════════════════════════════════════════════════════

def _legend():
    """The "Legend & Criteria" sheet, as data.

    Same source the export uses, so what is on screen and what is sent to the
    client cannot drift apart.
    """
    out = []
    for heading, kind, entries in export.LEGEND:
        table, keys = export._LEGEND_FILLS[kind]
        out.append({
            'heading': heading,
            'entries': [
                {'label': label, 'definition': definition,
                 'fill': '#' + table[key][0][-6:],
                 'ink': '#' + table[key][1][-6:]}
                for (label, definition), key in zip(entries, keys)
            ],
        })
    return out


def _vocabularies():
    return {
        'legend': _legend(),
        'buckets': [{'key': k, 'label': v} for k, v in TestItem.BUCKET_CHOICES],
        'dev_statuses': [{'key': k, 'label': v} for k, v in TestItem.DEV_STATUS_CHOICES],
        'tested': [{'key': k, 'label': v} for k, v in TestItem.TESTED_CHOICES],
        'readiness': [{'key': k, 'label': v} for k, v in TestItem.READINESS_CHOICES],
    }


# ══════════════════════════════════════════════════════════════════════════════
# Projects
# ══════════════════════════════════════════════════════════════════════════════

@require_http_methods(["GET"])
def api_test_projects(request):
    """Every project with its derived totals, plus the shared vocabularies."""
    err = _require_module(request, MODULE)
    if err:
        return err

    qs = TestProject.objects.all()
    if (request.GET.get('archived') or '').strip() != '1':
        qs = qs.filter(is_archived=False)

    projects = list(qs)
    areas_map = {}
    for a in TestArea.objects.filter(
            project__in=projects).prefetch_related('items'):
        areas_map.setdefault(a.project_id, []).append(a)

    return JsonResponse({
        'projects': [_project_json(p, areas_map) for p in projects],
        'vocabularies': _vocabularies(),
    })


@require_http_methods(["GET"])
def api_test_project_detail(request, pk):
    """One project in full: areas, their items, notes and every rollup."""
    err = _require_module(request, MODULE)
    if err:
        return err

    p = TestProject.objects.filter(pk=pk).first()
    if p is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    areas = [_area_json(a) for a in p.areas.prefetch_related(
        'versions__iterations__item__iterations__version')]

    return JsonResponse({
        'project': _project_json(p),
        'areas': areas,
        'notes': [{'id': n.id, 'text': n.text, 'is_done': n.is_done,
                   'order': n.order} for n in p.notes.all()],
        'vocabularies': _vocabularies(),
    })


def _since(request):
    """The `since` timestamp, tolerating an unencoded "+" in the offset.

    A query string decodes "+" as a space, so an ISO timestamp that was not
    URL-encoded arrives as "...T10:00:00 00:00" and will not parse. Falling back
    to "everything changed" would send the whole sheet back and cause exactly
    the full re-render this endpoint exists to avoid, so the space is repaired
    before giving up.
    """
    raw = (request.GET.get('since') or '').strip()
    if not raw:
        return None
    stamp = parse_datetime(raw)
    if stamp is None and ' ' in raw:
        stamp = parse_datetime(raw.replace(' ', '+'))
    return stamp


@require_http_methods(["GET"])
def api_test_changes(request, pk):
    """What has changed since a moment, and nothing else.

    Two people work a sheet at once - the team in the platform, the client
    through a share link - so each side has to see the other's edits. Re-fetching
    the whole project to find that out means re-rendering a table of a hundred
    rows every few seconds, which is what makes a page flicker and lose the cell
    someone is typing in.

    So this returns only the passes touched since `since`, and the current
    rollups, which are small. The caller patches those rows into what it already
    has; every other row is untouched and does not re-render. Row counts come
    back too, because an added or deleted row cannot be spotted from timestamps
    alone - if a count disagrees, the caller reloads in full.
    """
    err = _require_module(request, MODULE)
    if err:
        return err

    p = TestProject.objects.filter(pk=pk).first()
    if p is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    since = _since(request)
    now = timezone.now()

    changed, areas = [], []
    for a in p.areas.prefetch_related('versions__iterations__item__iterations__version'):
        sheets = []
        for v in a.versions.all():
            rows = sorted(v.iterations.select_related('item'),
                          key=lambda r: (r.item.order, r.item_id))
            sheets.append({
                'version_id': v.id,
                'rollup': _rollup(rows),
                'count': len(rows),
            })
            for r in rows:
                if since is None or (r.updated_at and r.updated_at > since):
                    changed.append({
                        'area_id': a.id,
                        'version_id': v.id,
                        'item': _sheet_item_json(r),
                    })
        latest = sheets[-1] if sheets else None
        areas.append({
            'id': a.id,
            'rollup': latest['rollup'] if latest else _rollup([]),
            'sheets': sheets,
        })

    return JsonResponse({
        'server_time': now.isoformat(),
        'changed': changed,
        'areas': areas,
        'project_rollup': _sum_rollups([a['rollup'] for a in areas]),
    })


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_test_project_save(request, pk=None):
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)

    p = TestProject.objects.filter(pk=pk).first() if pk else None
    if pk and p is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)
    if p is None:
        p = TestProject(created_by=request.user if request.user.is_authenticated else None)

    if 'name' in data or p.pk is None:
        name = (data.get('name') or '').strip()
        if not name:
            return JsonResponse({'detail': 'A project name is required.'}, status=400)
        clash = TestProject.objects.filter(name__iexact=name).exclude(pk=p.pk).exists()
        if clash:
            return JsonResponse(
                {'detail': f'A project named "{name}" already exists.'}, status=400)
        p.name = name

    for field in ('client', 'summary', 'testing_window', 'version_label'):
        if field in data:
            setattr(p, field, (data.get(field) or '').strip())
    for field in ('window_start', 'window_end'):
        if field in data:
            # An empty string clears the date rather than failing to parse.
            setattr(p, field, _date(data.get(field)))
    if 'is_archived' in data:
        p.is_archived = bool(data.get('is_archived'))

    p.save()

    # Apps are named per project - an E-Crop round tests "Inspector App" and
    # "Inspector Web", an FSA round tests something else entirely - so nothing is
    # seeded unless the caller says what this project is testing.
    #
    # Each app is given the build it starts on. Without one the app would open on
    # a placeholder release called "Initial", which tells nobody which build the
    # first sheet was actually run against.
    if not p.areas.exists():
        for i, entry in enumerate(data.get('areas') or []):
            # Accepts {"name": ..., "version": ...} or a bare name.
            if isinstance(entry, dict):
                name = str(entry.get('name') or '').strip()
                version = str(entry.get('version') or '').strip()
            else:
                name, version = str(entry).strip(), ''
            if not name:
                continue
            area, made = TestArea.objects.get_or_create(
                project=p, name=name[:120], defaults={'order': i})
            if made:
                TestVersion.objects.create(
                    area=area, label=(version[:80] or 'Initial'), order=0)

    return JsonResponse({'project': _project_json(p)})


@csrf_exempt
@require_http_methods(["POST"])
def api_test_project_duplicate(request, pk):
    """Start a fresh round against the same system, as its own entry.

    A system is tested more than once - E-Crop is a project that gets retested
    when a new build lands - and each round has to keep its own verdicts, so a
    retest is a new project rather than an edit of the old one. The apps and the
    things to check carry over; the verdicts do not, because nothing in the new
    round has been tested yet.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    source = TestProject.objects.filter(pk=pk).first()
    if source is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    data = _body(request)
    name = (data.get('name') or '').strip()
    if not name:
        return JsonResponse({'detail': 'Name the new round.'}, status=400)
    if TestProject.objects.filter(name__iexact=name).exists():
        return JsonResponse(
            {'detail': f'A project named "{name}" already exists.'}, status=400)

    include_items = data.get('include_items', True)
    # Carrying the verdicts over would show a round as passed before it has been
    # run, so they reset unless the caller explicitly asks to keep them.
    reset = data.get('reset_status', True)

    with transaction.atomic():
        clone = TestProject.objects.create(
            name=name,
            client=source.client,
            summary=source.summary,
            testing_window=(data.get('testing_window') or '').strip(),
            window_start=_date(data.get('window_start')),
            window_end=_date(data.get('window_end')),
            version_label=(data.get('version_label') or '').strip(),
            created_by=request.user if request.user.is_authenticated else None)

        for a in source.areas.prefetch_related('items'):
            new_area = TestArea.objects.create(
                project=clone, name=a.name, order=a.order)
            target = None
            # A new round is run against a new build, so the old chain does not
            # carry over unless this is a straight copy rather than a retest.
            if not reset:
                TestVersion.objects.bulk_create([
                    TestVersion(area=new_area, label=v.label, note=v.note,
                                released_on=v.released_on, order=v.order)
                    for v in a.versions.all()
                ])
            if not include_items:
                continue
            for it in a.items.prefetch_related('iterations'):
                copy = TestItem.objects.create(
                    area=new_area, order=it.order, issue=it.issue,
                    description=it.description, bucket=it.bucket)
                if reset:
                    # A new round starts the trail over: the item is carried
                    # across as something still to check, on pass 1 of whatever
                    # build this round begins on.
                    if target is None:
                        target = _ensure_version(
                            new_area,
                            (data.get('version_label') or '').strip() or 'Initial')
                    TestIteration.objects.create(
                        item=copy, number=1, version=target)
                else:
                    by_label = {v.label: v for v in new_area.versions.all()}
                    TestIteration.objects.bulk_create([
                        TestIteration(
                            item=copy, number=r.number, dev_status=r.dev_status,
                            tested=r.tested, readiness=r.readiness,
                            client_feedback=r.client_feedback,
                            tested_on=r.tested_on,
                            version=by_label.get(r.version.label)
                            or _ensure_version(new_area))
                        for r in it.iterations.select_related('version')
                    ])

        # Open enhancements are still open against the new round.
        for n in source.notes.filter(is_done=False):
            TestNote.objects.create(project=clone, text=n.text, order=n.order)

    return JsonResponse({'project': _project_json(clone)})


@csrf_exempt
@require_http_methods(["DELETE", "POST"])
def api_test_project_delete(request, pk):
    err = _require_module(request, MODULE)
    if err:
        return err
    p = TestProject.objects.filter(pk=pk).first()
    if p is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)
    p.delete()
    return JsonResponse({'ok': True})


# ══════════════════════════════════════════════════════════════════════════════
# Areas
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_test_area_save(request, pk=None):
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)

    a = TestArea.objects.filter(pk=pk).first() if pk else None
    if pk and a is None:
        return JsonResponse({'detail': 'Area not found.'}, status=404)

    if a is None:
        p = TestProject.objects.filter(pk=data.get('project')).first()
        if p is None:
            return JsonResponse({'detail': 'Project not found.'}, status=404)
        a = TestArea(project=p, order=p.areas.count())

    if 'name' in data or a.pk is None:
        name = (data.get('name') or '').strip()
        if not name:
            return JsonResponse({'detail': 'An area name is required.'}, status=400)
        if TestArea.objects.filter(
                project=a.project, name__iexact=name).exclude(pk=a.pk).exists():
            return JsonResponse(
                {'detail': f'This project already has an area named "{name}".'},
                status=400)
        a.name = name
    if 'order' in data:
        a.order = int(data.get('order') or 0)

    a.save()

    # An initial build can be given when the app is created; later ones are
    # released through the versions endpoint so the chain is kept in order.
    first = (data.get('version_label') or '').strip()
    if not a.versions.exists():
        TestVersion.objects.create(area=a, label=first[:80] or 'Initial', order=0)

    return JsonResponse({'area': _area_json(a)})


@csrf_exempt
@require_http_methods(["POST"])
def api_test_version_create(request, pk):
    """Release a new build, carrying the unresolved issues onto its sheet.

    Anything that did not reach PASS on the outgoing build is still outstanding
    when the new one ships, so it opens on the new sheet as the next pass of the
    same issue - which is what makes the readiness figure per release mean
    something, and saves retyping the backlog every time a build lands. Issues
    that passed are done and stay behind on the sheet that signed them off.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    a = TestArea.objects.filter(pk=pk).first()
    if a is None:
        return JsonResponse({'detail': 'App not found.'}, status=404)

    data = _body(request)
    label = (data.get('label') or '').strip()
    if not label:
        return JsonResponse({'detail': 'Give the build a version.'}, status=400)
    if a.versions.filter(label__iexact=label).exists():
        return JsonResponse(
            {'detail': f'{a.name} already has a version "{label}".'}, status=400)

    previous = _latest_version(a)
    carry = data.get('carry_over', True)

    with transaction.atomic():
        v = TestVersion.objects.create(
            area=a, label=label[:80], note=(data.get('note') or '').strip()[:300],
            released_on=data.get('released_on') or None,
            order=a.versions.count())

        carried = 0
        if previous and carry:
            for r in previous.iterations.select_related('item'):
                if r.readiness == PASS_KEY:
                    continue
                TestIteration.objects.create(
                    item=r.item,
                    version=v,
                    number=r.number + 1,
                    # The fix is what the new build is for, so the carried row
                    # opens as ready to re-check rather than as a fresh finding.
                    dev_status='rectified_requires_testing',
                    tested='not_tested',
                    readiness='requires_action',
                    client_feedback='')
                carried += 1

    return JsonResponse({
        'area': _area_json(a),
        'version': {'id': v.id, 'label': v.label, 'note': v.note,
                    'released_on': v.released_on.isoformat() if v.released_on else None,
                    'order': v.order},
        'carried_over': carried,
    })


@csrf_exempt
@require_http_methods(["DELETE", "POST"])
def api_test_version_delete(request, pk):
    err = _require_module(request, MODULE)
    if err:
        return err
    v = TestVersion.objects.filter(pk=pk).first()
    if v is None:
        return JsonResponse({'detail': 'Version not found.'}, status=404)
    area = v.area
    v.delete()
    return JsonResponse({'ok': True, 'current_version': _current_version(area)})


@csrf_exempt
@require_http_methods(["DELETE", "POST"])
def api_test_area_delete(request, pk):
    err = _require_module(request, MODULE)
    if err:
        return err
    a = TestArea.objects.filter(pk=pk).first()
    if a is None:
        return JsonResponse({'detail': 'Area not found.'}, status=404)
    a.delete()
    return JsonResponse({'ok': True})


# ══════════════════════════════════════════════════════════════════════════════
# Items
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_test_item_save(request, pk=None):
    """Create or update an item, writing verdicts onto its latest pass.

    Editing an item corrects the pass in progress; it does not open a new one.
    Recording a fresh result after a fix is what `api_test_iteration_create`
    is for, so a correction never silently erases the trail.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)

    it = TestItem.objects.filter(pk=pk).first() if pk else None
    if pk and it is None:
        return JsonResponse({'detail': 'Item not found.'}, status=404)

    if it is None:
        area = TestArea.objects.filter(pk=data.get('area')).first()
        if area is None:
            return JsonResponse({'detail': 'Area not found.'}, status=404)
        it = TestItem(area=area, order=area.items.count())

    if 'issue' in data or it.pk is None:
        issue = (data.get('issue') or '').strip()
        if not issue:
            return JsonResponse({'detail': 'An issue title is required.'}, status=400)
        it.issue = issue

    for field in ('description',):
        if field in data:
            setattr(it, field, (data.get(field) or '').strip())

    # Written through the same coercion the import uses, so a value typed in the
    # UI and a value read from a sheet land on identical keys.
    if 'bucket' in data:
        it.bucket = _coerce(data.get('bucket'), TestItem.BUCKET_CHOICES,
                            _BUCKET_ALIASES, it.bucket or 'in_scope_change')
    if 'order' in data:
        it.order = int(data.get('order') or 0)

    it.save()

    # An edit targets the pass the caller was looking at, so correcting a row
    # on an older release does not silently rewrite the current build.
    cur = None
    if data.get('iteration'):
        cur = TestIteration.objects.filter(
            pk=data.get('iteration'), item=it).first()
    if cur is None:
        cur = _latest(it)
    if cur is None:
        cur = TestIteration(item=it, number=1,
                            version=_ensure_version(it.area))

    if 'dev_status' in data:
        cur.dev_status = _coerce(data.get('dev_status'), TestItem.DEV_STATUS_CHOICES,
                                 _DEV_ALIASES, cur.dev_status or 'in_progress')
    if 'tested' in data:
        cur.tested = _coerce(data.get('tested'), TestItem.TESTED_CHOICES,
                             _TESTED_ALIASES, cur.tested or 'not_tested')
    if 'readiness' in data:
        cur.readiness = _coerce(data.get('readiness'), TestItem.READINESS_CHOICES,
                                _READY_ALIASES, cur.readiness or 'requires_action')
    if 'client_feedback' in data:
        cur.client_feedback = (data.get('client_feedback') or '').strip()
    cur.save()

    it.refresh_from_db()
    return JsonResponse({
        'item': _item_json(it),
        'rollup': _area_rollup(it.area),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_test_iteration_create(request, pk):
    """Record a fresh pass over an item after it has been actioned.

    An item that came back REQUIRES ACTION gets fixed and checked again; this
    opens the next pass rather than overwriting the last, so the sheet shows
    both what was found and that it was re-verified. The new pass starts from
    the previous verdict's development status, since that is usually what moved.
    """
    err = _require_module(request, MODULE)
    if err:
        return err
    it = TestItem.objects.filter(pk=pk).first()
    if it is None:
        return JsonResponse({'detail': 'Item not found.'}, status=404)

    data = _body(request)
    previous = _latest(it)
    number = (previous.number + 1) if previous else 1

    # A retest without a new build stays on the build it was run against;
    # carrying an issue to the *next* build is what releasing a version does.
    version = None
    if data.get('version'):
        version = TestVersion.objects.filter(
            pk=data.get('version'), area=it.area).first()
    if version is None:
        version = previous.version if previous else _ensure_version(it.area)

    r = TestIteration.objects.create(
        item=it,
        number=number,
        version=version,
        dev_status=_coerce(data.get('dev_status'), TestItem.DEV_STATUS_CHOICES,
                           _DEV_ALIASES, 'rectified_requires_testing'),
        tested=_coerce(data.get('tested'), TestItem.TESTED_CHOICES,
                       _TESTED_ALIASES, 'not_tested'),
        readiness=_coerce(data.get('readiness'), TestItem.READINESS_CHOICES,
                          _READY_ALIASES, 'requires_action'),
        client_feedback=(data.get('client_feedback') or '').strip(),
        tested_on=data.get('tested_on') or None)

    it.refresh_from_db()
    return JsonResponse({
        'item': _item_json(it),
        'iteration': _iteration_json(r),
        'rollup': _area_rollup(it.area),
    })


@csrf_exempt
@require_http_methods(["DELETE", "POST"])
def api_test_iteration_delete(request, pk):
    """Remove a pass. The one before it becomes the item's verdict again."""
    err = _require_module(request, MODULE)
    if err:
        return err
    r = TestIteration.objects.filter(pk=pk).first()
    if r is None:
        return JsonResponse({'detail': 'Iteration not found.'}, status=404)
    item = r.item
    if item.iterations.count() <= 1:
        return JsonResponse(
            {'detail': 'An item keeps at least one pass. Delete the item instead.'},
            status=400)
    r.delete()
    # Renumber so the trail reads 1, 2, 3 with no gaps.
    for i, row in enumerate(item.iterations.all(), start=1):
        if row.number != i:
            row.number = i
            row.save(update_fields=['number'])
    item.refresh_from_db()
    return JsonResponse({
        'item': _item_json(item),
        'rollup': _area_rollup(item.area),
    })


@csrf_exempt
@require_http_methods(["DELETE", "POST"])
def api_test_item_delete(request, pk):
    err = _require_module(request, MODULE)
    if err:
        return err
    it = TestItem.objects.filter(pk=pk).first()
    if it is None:
        return JsonResponse({'detail': 'Item not found.'}, status=404)
    area = it.area
    it.delete()
    return JsonResponse({'ok': True, 'rollup': _area_rollup(area)})


# ══════════════════════════════════════════════════════════════════════════════
# Notes
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_test_note_save(request, pk=None):
    err = _require_module(request, MODULE)
    if err:
        return err
    data = _body(request)

    n = TestNote.objects.filter(pk=pk).first() if pk else None
    if pk and n is None:
        return JsonResponse({'detail': 'Note not found.'}, status=404)
    if n is None:
        p = TestProject.objects.filter(pk=data.get('project')).first()
        if p is None:
            return JsonResponse({'detail': 'Project not found.'}, status=404)
        n = TestNote(project=p, order=p.notes.count())

    if 'text' in data or n.pk is None:
        text = (data.get('text') or '').strip()
        if not text:
            return JsonResponse({'detail': 'Note text is required.'}, status=400)
        n.text = text
    if 'is_done' in data:
        n.is_done = bool(data.get('is_done'))
    n.save()
    return JsonResponse({'note': {'id': n.id, 'text': n.text,
                                  'is_done': n.is_done, 'order': n.order}})


@csrf_exempt
@require_http_methods(["DELETE", "POST"])
def api_test_note_delete(request, pk):
    err = _require_module(request, MODULE)
    if err:
        return err
    n = TestNote.objects.filter(pk=pk).first()
    if n is None:
        return JsonResponse({'detail': 'Note not found.'}, status=404)
    n.delete()
    return JsonResponse({'ok': True})


# ══════════════════════════════════════════════════════════════════════════════
# Workbook import
# ══════════════════════════════════════════════════════════════════════════════

_HEADER_HINTS = ('day', 'issue', 'description')


def _find_header_row(ws, limit=12):
    """Row index whose cells look like the sheet's column headings.

    The packs put a banner above the headings, and not always on the same row,
    so the header is located by content rather than assumed to be row 1.
    """
    for r in range(1, min(limit, ws.max_row) + 1):
        values = [str(c).strip().lower() if c is not None else ''
                  for c in next(ws.iter_rows(min_row=r, max_row=r, values_only=True))]
        hits = sum(1 for h in _HEADER_HINTS if h in values)
        if hits >= 2:
            return r, values
    return None, []


def _column_index(headers, *needles):
    for i, h in enumerate(headers):
        for n in needles:
            if n in h:
                return i
    return None


def _title_from(description, limit=90):
    """A short title for an item whose Issue cell was left blank."""
    text = ' '.join((description or '').split())
    if len(text) <= limit:
        return text
    cut = text[:limit]
    space = cut.rfind(' ')
    return (cut[:space] if space > 40 else cut).rstrip(' ,;:.') + '...'


def _parse_sheet(ws):
    """Return (rows, skipped) for a testing sheet, or (None, 0) if it isn't one."""
    header_row, headers = _find_header_row(ws)
    if header_row is None:
        return None, 0

    idx = {
        'issue': _column_index(headers, 'issue'),
        'description': _column_index(headers, 'description'),
        'bucket': _column_index(headers, 'bucket', 'feedback bucket'),
        'dev_status': _column_index(headers, 'development feedback', 'status'),
        # "Client Test / Review Status" now, "Tested / Reviewed" in older
        # packs - both carry "review", neither collides with another column.
        'tested': _column_index(headers, 'tested', 'review'),
        'readiness': _column_index(headers, 'readiness'),
        'client_feedback': _column_index(headers, 'comment', 'feedback / comments'),
    }

    def cell(row, key):
        i = idx.get(key)
        if i is None or i >= len(row):
            return ''
        v = row[i]
        return '' if v is None else str(v).strip()

    rows, skipped = [], 0
    for raw in ws.iter_rows(min_row=header_row + 1, values_only=True):
        if raw is None or all(c is None or str(c).strip() == '' for c in raw):
            continue
        issue = cell(raw, 'issue')
        description = cell(raw, 'description')
        if not issue and not description:
            # A spacer row - nothing to hang an item on.
            skipped += 1
            continue
        if not issue:
            # Testers routinely leave Issue blank and write the whole item into
            # Description. These are real items - the E-Crop pack has four, and
            # dropping them is what made its own dashboard read 32 items above
            # 36 passes. Title them from the description instead.
            issue = _title_from(description)
        rows.append({
            'issue': issue[:300],
            'description': description,
            'bucket': _coerce(cell(raw, 'bucket'), TestItem.BUCKET_CHOICES,
                              _BUCKET_ALIASES, 'in_scope_change'),
            'dev_status': _coerce(cell(raw, 'dev_status'), TestItem.DEV_STATUS_CHOICES,
                                  _DEV_ALIASES, 'in_progress'),
            'tested': _coerce(cell(raw, 'tested'), TestItem.TESTED_CHOICES,
                              _TESTED_ALIASES, 'not_tested'),
            'readiness': _coerce(cell(raw, 'readiness'), TestItem.READINESS_CHOICES,
                                 _READY_ALIASES, 'requires_action'),
            'client_feedback': cell(raw, 'client_feedback'),
        })
    return rows, skipped


def _parse_notes(ws):
    """The notes sheet: a numbered list of parked enhancements."""
    out = []
    for raw in ws.iter_rows(values_only=True):
        cells = [str(c).strip() for c in raw if c is not None and str(c).strip()]
        if not cells:
            continue
        # Drop the "Nr | Enhancements" heading and the bare numbering column.
        text = cells[-1]
        if text.lower() in ('enhancments', 'enhancements', 'nr'):
            continue
        if re.fullmatch(r'\d+', text):
            continue
        out.append(text)
    return out


def _header_text(ws, limit=6):
    """Free text above the table - the pack title, window and blurb."""
    lines = []
    for raw in ws.iter_rows(min_row=1, max_row=min(limit, ws.max_row), values_only=True):
        for c in raw:
            if c is not None and str(c).strip():
                lines.append(str(c).strip())
    return lines



def _versions_for(area_name, banner):
    """Pull this app's chain of builds out of the dashboard banner.

    The banner reads like "Inspector App Version : 2.1.5 -> New Version : 2.1.6
    -> New Version : 2.1.8" - four builds shipped while testing was still
    running - so it yields a version per build, in order, rather than one label.
    Only the segment naming this app is read, so a two-app pack does not give
    both apps the same chain.
    """
    if not banner or not area_name:
        return []
    low = banner.lower()
    idx = low.find(area_name.lower())
    if idx < 0:
        return []
    tail = banner[idx + len(area_name):]
    # Anything that looks like a dotted or plain build number, in order.
    found, seen = [], set()
    for m in re.finditer(r'\b\d+(?:\.\d+)+\b|\bv\d+(?:\.\d+)*\b', tail):
        label = m.group(0)
        if label not in seen:
            seen.add(label)
            found.append(label)
    return found

@csrf_exempt
@require_http_methods(["POST"])
def api_test_import(request):
    """Seed a project from a Management Live Sheet workbook.

    Multipart upload: `file` is the .xlsx, `name` optionally overrides the
    project name. Every sheet that carries Day/Issue/Description columns becomes
    an area; a sheet named like notes becomes the notes list. The workbook's own
    dashboard sheet is deliberately ignored - its totals are what this module
    exists to stop maintaining by hand.
    """
    err = _require_module(request, MODULE)
    if err:
        return err

    upload = request.FILES.get('file')
    if upload is None:
        return JsonResponse({'detail': 'Attach an .xlsx file as "file".'}, status=400)
    if not upload.name.lower().endswith(('.xlsx', '.xlsm')):
        return JsonResponse(
            {'detail': 'That is not an Excel workbook (.xlsx).'}, status=400)

    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(upload.read()), data_only=True)
    except Exception as exc:
        logger.warning('system testing import failed to open workbook: %s', exc)
        return JsonResponse(
            {'detail': f'Could not read that workbook: {exc}'}, status=400)

    name = (request.POST.get('name') or '').strip()
    if not name:
        name = re.sub(r'\.xlsx?$', '', upload.name, flags=re.I).strip()
    if TestProject.objects.filter(name__iexact=name).exists():
        return JsonResponse(
            {'detail': f'A project named "{name}" already exists. '
                       f'Give the import a different name.'}, status=400)

    # Pull the window and blurb off whatever sheet carries the pack header.
    window, summary, version = '', '', ''
    for ws in wb.worksheets:
        for line in _header_text(ws):
            low = line.lower()
            if 'testing window' in low:
                # "Testing Window: 14 - 18 September | Inspector App Version: 2.1.5"
                parts = re.split(r'\s*\|\s*', line)
                for part in parts:
                    if 'window' in part.lower():
                        window = part.split(':', 1)[-1].strip()
                    elif 'version' in part.lower():
                        version = part.strip()
            elif 'consolidates' in low or 'this pack' in low:
                summary = line
        if window:
            break

    areas_created, items_created, skipped_total, notes_created = 0, 0, 0, 0

    with transaction.atomic():
        project = TestProject.objects.create(
            name=name, testing_window=window, version_label=version,
            summary=summary,
            created_by=request.user if request.user.is_authenticated else None)

        for ws in wb.worksheets:
            title = (ws.title or '').strip()
            low = title.lower()

            if 'note' in low:
                for i, text in enumerate(_parse_notes(ws)):
                    TestNote.objects.create(project=project, text=text, order=i)
                    notes_created += 1
                continue
            # The legend restates the choices this module already defines, and
            # the dashboard is derived here, so neither is imported.
            if 'legend' in low or 'criteria' in low or 'dashboard' in low:
                continue

            rows, skipped = _parse_sheet(ws)
            if not rows:
                continue
            # The packs put each app's build in the dashboard banner rather
            # than on its own sheet ("Inspector App Version : 2.1.5"), so pull
            # it back out per area.
            area = TestArea.objects.create(
                project=project, name=title[:120], order=areas_created)
            for i, label in enumerate(_versions_for(title, version)):
                TestVersion.objects.create(area=area, label=label[:80], order=i)
            # The workbook records one snapshot, and its verdicts are the final
            # ones, so the sheet lands on the last build in the chain.
            sheet_version = _ensure_version(area)
            areas_created += 1
            skipped_total += skipped
            for i, row in enumerate(rows):
                verdict = {k: row.pop(k) for k in
                           ('dev_status', 'tested', 'readiness', 'client_feedback')}
                item = TestItem.objects.create(area=area, order=i, **row)
                # The sheet records one round of testing, so each imported row
                # arrives as that item's first pass.
                TestIteration.objects.create(
                    item=item, number=1, version=sheet_version, **verdict)
            items_created += len(rows)

        if areas_created == 0:
            # Nothing usable - don't leave an empty shell behind.
            transaction.set_rollback(True)
            return JsonResponse(
                {'detail': 'No testing sheets found in that workbook. A sheet '
                           'needs Day, Issue and Description columns.'}, status=400)

    return JsonResponse({
        'project': _project_json(project),
        'imported': {
            'areas': areas_created,
            'items': items_created,
            'notes': notes_created,
            'skipped_rows': skipped_total,
        },
    })


# ══════════════════════════════════════════════════════════════════════════════
# Export - Excel and PDF
# ══════════════════════════════════════════════════════════════════════════════
# Both formats are built by system_testing_export, which carries the palette and
# layout read back off the original workbook, so the two stay in step.

def _export_context(pk):
    p = TestProject.objects.filter(pk=pk).first()
    if p is None:
        return None, None, None
    areas = list(p.areas.prefetch_related('versions__iterations__item'))
    return p, areas, list(p.notes.all())


@require_http_methods(["GET"])
def api_test_export(request, pk):
    """The client pack as .xlsx, styled like the sheet it replaces."""
    err = _require_module(request, MODULE)
    if err:
        return err
    p, areas, notes = _export_context(pk)
    if p is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    data = export.build_workbook(p, areas, notes, _rollup, _sum_rollups)
    resp = HttpResponse(
        data,
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    resp['Content-Disposition'] = \
        f'attachment; filename="{export.safe_filename(p.name, "xlsx")}"'
    return resp


@require_http_methods(["GET"])
def api_test_export_pdf(request, pk):
    """The same pack as PDF, for sending to a client who will not open Excel."""
    err = _require_module(request, MODULE)
    if err:
        return err
    p, areas, notes = _export_context(pk)
    if p is None:
        return JsonResponse({'detail': 'Project not found.'}, status=404)

    data = export.build_pdf(p, areas, notes, _rollup, _sum_rollups)
    resp = HttpResponse(data, content_type='application/pdf')
    resp['Content-Disposition'] = \
        f'attachment; filename="{export.safe_filename(p.name, "pdf")}"'
    return resp
