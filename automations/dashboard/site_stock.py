"""The shared stock image library.

One copy of each image, served from /sites/_stock/, referenced by every
generated site. Downloaded rather than hotlinked so a published client site
cannot break because a photographer deleted a file, and shared rather than
copied per site so the disk cost is fixed instead of growing with each client.

Everything here degrades to nothing: if the library is absent or empty, the
pickers return '' and the renderer falls back to its drawn hero panel and drops
the gallery. That is deliberate - the library can be built, rebuilt or replaced
without touching a line of generator code.
"""
import json
import logging
import os
import shutil
from functools import lru_cache

from django.conf import settings

logger = logging.getLogger(__name__)

# Where the library lives in the repo, and where it is published to.
ASSETS_ROOT = os.path.join(os.path.dirname(__file__), 'assets', 'stock')
PUBLIC_PREFIX = '/sites/_stock'


@lru_cache(maxsize=1)
def manifest():
    """The library index, or an empty one. Cached for the process."""
    try:
        with open(os.path.join(ASSETS_ROOT, 'manifest.json'), encoding='utf-8') as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return {'images': []}
    # Only entries whose file is actually on disk: a manifest that outlives its
    # images would otherwise put broken <img> tags on a live client site.
    kept = [m for m in (data.get('images') or [])
            if os.path.isfile(os.path.join(ASSETS_ROOT, m.get('file', '')))]
    data['images'] = kept
    return data


def reset_cache():
    manifest.cache_clear()


def categories():
    return sorted({m['category'] for m in manifest()['images']})


def _url(entry):
    # Root-relative, so the same value works in the preview (served by Django)
    # and in the published page (served by nginx) without knowing the host.
    return f'{PUBLIC_PREFIX}/{entry["file"]}'


def pick(category, count=1, widest_first=False, skip=()):
    """Up to `count` image URLs from a category.

    `widest_first` for a hero, where resolution shows; source order otherwise,
    which keeps a gallery looking chosen rather than sorted.
    """
    rows = [m for m in manifest()['images'] if m['category'] == category]
    if not rows:
        rows = [m for m in manifest()['images'] if m['category'] == 'generic']
    if widest_first:
        rows = sorted(rows, key=lambda m: -m.get('width', 0))
    out, taken = [], set(skip)
    for m in rows:
        url = _url(m)
        if url in taken:
            continue
        out.append(url)
        taken.add(url)
        if len(out) >= count:
            break
    return out


def hero(category):
    got = pick(category, 1, widest_first=True)
    return got[0] if got else ''


def gallery(category, count=3, skip=()):
    return pick(category, count, skip=skip)


def credits(urls):
    """Provenance for the images a site uses, for the internal notes.

    The licences in use need no attribution, but a published page should still
    be answerable: this is what goes in the site's notes so anyone reviewing it
    can see where a photograph came from.
    """
    by_url = {_url(m): m for m in manifest()['images']}
    out = []
    for u in urls:
        m = by_url.get(u)
        if not m:
            continue
        who = m.get('photographer') or m.get('creator') or 'unknown'
        out.append(f'{os.path.basename(m["file"])}: {who} '
                   f'({m.get("licence") or "see manifest"})')
    return out


def publish_library(sites_root):
    """Copy the library into the directory nginx serves, if it is not there.

    Called on publish rather than on deploy: a site is never written without
    the images it references being reachable, and a library rebuilt in the repo
    reaches live pages the next time anything is published.
    """
    src = ASSETS_ROOT
    if not os.path.isdir(src):
        return 0
    dest = os.path.join(sites_root, '_stock')
    copied = 0
    for root, _dirs, files in os.walk(src):
        rel = os.path.relpath(root, src)
        target = dest if rel == '.' else os.path.join(dest, rel)
        os.makedirs(target, exist_ok=True)
        for f in files:
            s, d = os.path.join(root, f), os.path.join(target, f)
            try:
                if (not os.path.exists(d)
                        or os.path.getsize(s) != os.path.getsize(d)
                        or os.path.getmtime(s) > os.path.getmtime(d)):
                    shutil.copy2(s, d)
                    copied += 1
            except OSError:
                logger.warning('[sites] could not copy stock file %s', f)
    if copied:
        logger.info('[sites] published %s stock files to %s', copied, dest)
    return copied
