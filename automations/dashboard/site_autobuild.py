"""Build a client's site the moment their answers arrive.

The point of this module is that nobody presses a button. A client submits the
question sheet and a draft site is built and published on its own, with the
link emailed over. That is the whole ask: "it comes in and gets made without
you touching it".

Three ways in:

* autobuild_async, from the reply itself, on a background thread - writing the
  copy is a model call and the client is not made to wait on it
* an hourly sweep, for the reply that arrived while something here was broken:
  a deploy, a full disk, a brief that raised
* autobuild, synchronously, for a build asked for from the UI

Both are idempotent: a request that already has a site is skipped, so the
sweep can run for ever without producing duplicates.

Nothing here is allowed to cost a reply. The answers are already saved before
this is called, and every failure is logged and swallowed - a client must never
see an error because our generator fell over on their brief.
"""
import logging
import threading

from django.utils.text import slugify

from . import site_content as sc
from .models import ClientRequest, ClientSite, SiteBlock

logger = logging.getLogger(__name__)


def _unique_slug(name):
    base = slugify(name)[:60] or 'site'
    slug, n = base, 2
    while ClientSite.objects.filter(slug=slug).exists():
        slug = f'{base}-{n}'[:80]
        n += 1
    return slug


def build_from_request(req, publish=True, created_by=None):
    """Create, seed and publish a site for an answered request.

    Returns the ClientSite, or None if there was nothing to do. Raises nothing
    the caller has to handle - see `autobuild` for the guarded entry point.
    """
    if req.status != 'answered' or not (req.answers or {}):
        return None
    existing = req.sites.first()
    if existing is not None:
        return existing

    brief = sc.plan(req)
    site = ClientSite.objects.create(
        request=req,
        client_name=brief['business'][:200],
        site_name=brief['business'][:200],
        slug=_unique_slug(brief['business']),
        tagline=brief['tagline'][:300],
        palette=brief['palette'], font=brief['font'],
        template=brief['template'], industry=brief['industry'],
        created_by=created_by,
    )

    blocks, notes = sc.compose(req, brief=brief)
    SiteBlock.objects.bulk_create([
        SiteBlock(site=site, kind=kind, order=i * 10, content=content)
        for i, (kind, content) in enumerate(blocks)
    ])
    if notes:
        site.notes = notes[:4000]
        site.save(update_fields=['notes'])

    logger.info('[autobuild] %s: %s sections, %s/%s, from request %s',
                site.slug, len(blocks), brief['industry'], brief['template'], req.id)

    if publish:
        # Imported here, not at module scope: sites_api reaches views for its
        # permission helper, and this module is imported from the public reply
        # handler. Keeping it local means no import order to get wrong.
        from .sites_api import publish_site
        ok, detail = publish_site(site)
        if not ok:
            logger.error('[autobuild] %s built but not published: %s',
                         site.slug, detail)
    return site


def autobuild(req, created_by=None):
    """The guarded entry point. Never raises, never blocks the reply."""
    try:
        return build_from_request(req, created_by=created_by)
    except Exception:                                            # noqa: BLE001
        # The answers are saved and the notification still goes out. A site
        # that failed to build is picked up by the next sweep.
        logger.exception('[autobuild] could not build a site for request %s', req.id)
        return None


def autobuild_async(req):
    """Build in the background and email the link when it is done.

    Returns whether a thread was started, not whether a site was built - the
    caller is a client's form submit and has nothing useful to do with the
    outcome.

    The thread closes its inherited database connection on the way in and out:
    a connection opened in the request is not the thread's to use, and one
    opened by the thread must not be left for the next request to find.
    """
    if req.status != 'answered' or req.sites.exists():
        return False

    req_id = req.id

    def _run():
        from django.db import connection
        connection.close()
        try:
            fresh = ClientRequest.objects.filter(pk=req_id).first()
            if fresh is None:
                return
            site = autobuild(fresh)
            if site is None:
                return
            from .client_requests import _email_site_ready
            ok, msg = _email_site_ready(fresh, site)
            if not ok:
                logger.error('[autobuild] %s built but the notice failed: %s',
                             site.slug, msg)
        except Exception:                                        # noqa: BLE001
            logger.exception('[autobuild] background build failed for %s', req_id)
        finally:
            connection.close()

    threading.Thread(target=_run, name=f'autobuild-{req_id}',
                     daemon=True).start()
    logger.info('[autobuild] building a site for request %s in the background',
                req_id)
    return True


def sweep(limit=10):
    """Build sites for any answered replies that do not have one yet.

    The safety net behind the live path. Capped per run because rendering and
    writing a site costs real work and this shares a process with the report
    syncs.
    """
    pending = [r for r in ClientRequest.objects.filter(status='answered')
               .order_by('-answered_at')[:60] if not r.sites.exists()]
    built = []
    for req in pending[:limit]:
        site = autobuild(req)
        if site is not None:
            built.append(site.slug)
    if built:
        logger.info('[autobuild] sweep built %s site(s): %s',
                    len(built), ', '.join(built))
    return built
