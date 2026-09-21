"""Client sites: seed from a reply, edit the blocks, publish to a live URL.

Publishing writes one static HTML file per site into a directory nginx serves.
No process runs per site, so a hundred client sites cost nothing at rest and
cannot take the platform down with them.
"""
import json
import logging
import os
import re
import socket

from django.conf import settings
from django.http import JsonResponse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import site_builder as sb
from . import site_content as sc
from . import site_stock as stock
from .models import ClientRequest, ClientSite, SiteBlock
from .views import _require_module

logger = logging.getLogger(__name__)

# Where the generated files live. Served by nginx, so it is deliberately
# separate from both MEDIA_ROOT and the private client-upload store.
SITES_ROOT = getattr(
    settings, 'CLIENT_SITES_ROOT', str(settings.BASE_DIR / 'client_sites'))
SITES_BASE_URL = getattr(
    settings, 'CLIENT_SITES_BASE_URL', 'https://workspace.moc-pty.com/sites')


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return {}


def _site_dict(site, blocks=None):
    bs = blocks if blocks is not None else list(site.blocks.all())
    return {
        'id': site.id,
        'request': site.request_id,
        'client_name': site.client_name,
        'site_name': site.site_name,
        'slug': site.slug,
        'tagline': site.tagline,
        'logo_url': site.logo_url,
        'palette': site.palette,
        'font': site.font,
        'template': site.template,
        'template_label': dict(ClientSite.TEMPLATE_CHOICES).get(site.template, ''),
        'industry': site.industry,
        'status': site.status,
        'status_display': site.get_status_display(),
        'published_url': site.published_url,
        'published_ip': site.published_ip,
        'published_at': site.published_at.isoformat() if site.published_at else None,
        'preview_url': f'/api/sites/{site.id}/preview',
        'notes': site.notes,
        'block_count': len(bs),
        'blocks': [
            {'id': b.id, 'kind': b.kind, 'label': sb.BLOCK_LIBRARY.get(b.kind, {}).get('label', b.kind),
             'order': b.order, 'is_visible': b.is_visible, 'content': b.content or {}}
            for b in bs
        ],
        'updated_at': site.updated_at.isoformat() if site.updated_at else None,
    }


def _unique_slug(name):
    base = slugify(name)[:60] or 'site'
    slug = base
    n = 2
    while ClientSite.objects.filter(slug=slug).exists():
        slug = f'{base}-{n}'[:80]
        n += 1
    return slug


# ══════════════════════════════════════════════════════════════════════════════
# Read
# ══════════════════════════════════════════════════════════════════════════════

def api_sites(request):
    err = _require_module(request, 'sites')
    if err:
        return err
    sites = ClientSite.objects.prefetch_related('blocks').exclude(status='archived')
    rows = [_site_dict(s, list(s.blocks.all())) for s in sites]
    return JsonResponse({
        'sites': rows,
        'total': len(rows),
        'published': sum(1 for r in rows if r['status'] == 'published'),
        'palettes': list(ClientSite.PALETTE_CHOICES),
        'fonts': list(ClientSite.FONT_CHOICES),
        'templates': [{'value': k, 'label': v['label'], 'blurb': v['blurb']}
                      for k, v in sb.TEMPLATES.items()],
        'stock_categories': stock.categories(),
        # The editor renders its fields from this, so the UI needs no per-block form.
        'library': [
            {'kind': k, 'label': v['label'], 'blurb': v['blurb'],
             'fields': [{'name': n, 'type': t, 'label': l} for n, t, l in v['fields']]}
            for k, v in sb.BLOCK_LIBRARY.items()
        ],
        # Replies that could seed a site but have not yet.
        'seedable': [
            {'id': r.id, 'title': r.title, 'client_name': r.client_name,
             'kind': r.kind, 'answered_count': r.answered_count}
            for r in ClientRequest.objects.filter(status='answered')
            if not r.sites.exists()
        ],
    })


@require_http_methods(["GET"])
def api_site_preview(request, pk):
    """The rendered site, straight from the database - no publish needed."""
    err = _require_module(request, 'sites')
    if err:
        return err
    site = ClientSite.objects.filter(pk=pk).first()
    if site is None:
        return JsonResponse({'detail': 'Site not found.'}, status=404)
    from django.http import HttpResponse
    # The preview references the image library at /sites/_stock/, which is
    # served from the published directory - so make sure it is there even if
    # this site has never been published.
    stock.publish_library(SITES_ROOT)
    html = sb.render_site(site, list(site.blocks.all()))
    resp = HttpResponse(html, content_type='text/html; charset=utf-8')
    # A preview of generated content should never be framed by anything else.
    resp['X-Frame-Options'] = 'SAMEORIGIN'
    return resp


# ══════════════════════════════════════════════════════════════════════════════
# Create
# ══════════════════════════════════════════════════════════════════════════════

def _seed_blocks(site, req, brief=None):
    """Build the site from the reply, through the industry content packs.

    Everything about what the page says lives in site_content: the template,
    the palette, the sections and the copy. This function only writes rows.
    """
    blocks, notes = sc.compose(req, brief=brief)
    SiteBlock.objects.bulk_create([
        SiteBlock(site=site, kind=kind, order=i * 10, content=content)
        for i, (kind, content) in enumerate(blocks)
    ])
    if notes:
        # Commercial detail and the review list, kept off the published page.
        site.notes = notes[:4000]
        site.save(update_fields=['notes'])
    return len(blocks)


@csrf_exempt
@require_http_methods(["POST"])
def api_site_create(request):
    """A blank site, or one seeded from an answered client request."""
    err = _require_module(request, 'sites')
    if err:
        return err
    data = _body(request)

    req = None
    if data.get('request'):
        req = ClientRequest.objects.filter(pk=data['request']).first()
        if req is None:
            return JsonResponse({'detail': 'That client request does not exist.'}, status=404)

    client_name = (data.get('client_name') or (req.client_name if req else '')).strip()
    site_name = (data.get('site_name')
                 or (req.title if req else '')
                 or client_name).strip()
    if not site_name:
        return JsonResponse({'detail': 'A site name is required.'}, status=400)

    # A reply decides its own template, palette and font from what the client
    # said. An explicit choice in the request body still wins, so the UI can
    # override it, but nothing has to be chosen for a site to be built.
    brief = sc.plan(req) if req is not None else None
    palette = (data.get('palette') or (brief and brief['palette']) or 'slate').strip()
    if palette not in dict(ClientSite.PALETTE_CHOICES):
        return JsonResponse({'detail': 'Unknown palette.'}, status=400)
    font = (data.get('font') or (brief and brief['font']) or 'modern').strip()
    if font not in dict(ClientSite.FONT_CHOICES):
        return JsonResponse({'detail': 'Unknown font pairing.'}, status=400)
    template = (data.get('template') or (brief and brief['template'])
                or 'corporate').strip()
    if template not in dict(ClientSite.TEMPLATE_CHOICES):
        return JsonResponse({'detail': 'Unknown template.'}, status=400)

    if brief and not client_name:
        client_name = brief['business']
    site = ClientSite.objects.create(
        request=req,
        client_name=client_name or site_name,
        site_name=(brief['business'] if brief else site_name)[:200],
        slug=_unique_slug(data.get('slug') or (brief['business'] if brief else site_name)),
        tagline=((data.get('tagline') or '').strip()
                 or (brief['tagline'] if brief else ''))[:300],
        palette=palette, font=font, template=template,
        industry=(brief['industry'] if brief else ''),
        created_by=request.user if request.user.is_authenticated else None,
    )

    if req is not None:
        n = _seed_blocks(site, req, brief=brief)
        logger.info('[sites] seeded %s with %s blocks from request %s (%s/%s)',
                    site.slug, n, req.id, brief['industry'], template)
    else:
        blocks = []
        for i, kind in enumerate(sb.layout_for(template)):
            blocks.append(SiteBlock(site=site, kind=kind, order=i * 10,
                                    content=sb.new_block_content(kind)))
        SiteBlock.objects.bulk_create(blocks)

    return JsonResponse(_site_dict(site), status=201)


# ══════════════════════════════════════════════════════════════════════════════
# Edit
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_site_update(request, pk):
    err = _require_module(request, 'sites')
    if err:
        return err
    site = ClientSite.objects.filter(pk=pk).first()
    if site is None:
        return JsonResponse({'detail': 'Site not found.'}, status=404)
    data = _body(request)

    fields = []
    for f, cap in (('client_name', 200), ('site_name', 200),
                   ('tagline', 300), ('notes', 4000)):
        if f in data:
            setattr(site, f, (data.get(f) or '').strip()[:cap])
            fields.append(f)
    if 'logo_url' in data:
        url = (data.get('logo_url') or '').strip()
        if url and not url.lower().startswith(('http://', 'https://')):
            return JsonResponse({'detail': 'logo_url must start with http:// or https://'},
                                status=400)
        site.logo_url = url
        fields.append('logo_url')
    for f, choices in (('palette', ClientSite.PALETTE_CHOICES),
                       ('font', ClientSite.FONT_CHOICES),
                       ('template', ClientSite.TEMPLATE_CHOICES)):
        if f in data:
            if data[f] not in dict(choices):
                return JsonResponse({'detail': f'Unknown {f}.'}, status=400)
            setattr(site, f, data[f])
            fields.append(f)

    if not fields:
        return JsonResponse({'detail': 'Nothing to update.'}, status=400)
    site.save(update_fields=fields + ['updated_at'])
    return JsonResponse(_site_dict(site))


@csrf_exempt
@require_http_methods(["POST"])
def api_block_save(request, pk):
    """Add a block, or update one. `block` present means update."""
    err = _require_module(request, 'sites')
    if err:
        return err
    site = ClientSite.objects.filter(pk=pk).first()
    if site is None:
        return JsonResponse({'detail': 'Site not found.'}, status=404)
    data = _body(request)

    if data.get('block'):
        b = site.blocks.filter(pk=data['block']).first()
        if b is None:
            return JsonResponse({'detail': 'Block not found.'}, status=404)
        if 'content' in data:
            if not isinstance(data['content'], dict):
                return JsonResponse({'detail': 'content must be an object.'}, status=400)
            # Only keys the library declares, so the renderer never meets a
            # field it does not know.
            allowed = {n for n, _, _ in sb.BLOCK_LIBRARY.get(b.kind, {}).get('fields', [])}
            b.content = {k: v for k, v in data['content'].items() if k in allowed}
        if 'is_visible' in data:
            b.is_visible = bool(data['is_visible'])
        if 'order' in data:
            try:
                b.order = int(data['order'])
            except (TypeError, ValueError):
                return JsonResponse({'detail': 'order must be a number.'}, status=400)
        b.save()
        site.save(update_fields=['updated_at'])
        return JsonResponse(_site_dict(site))

    kind = (data.get('kind') or '').strip()
    if kind not in sb.BLOCK_LIBRARY:
        return JsonResponse(
            {'detail': 'kind must be one of: ' + ', '.join(sb.BLOCK_LIBRARY) + '.'},
            status=400)
    last = site.blocks.order_by('-order').first()
    SiteBlock.objects.create(
        site=site, kind=kind,
        order=(last.order + 10) if last else 0,
        content=sb.new_block_content(kind))
    site.save(update_fields=['updated_at'])
    return JsonResponse(_site_dict(site), status=201)


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_block_delete(request, pk, block):
    err = _require_module(request, 'sites')
    if err:
        return err
    site = ClientSite.objects.filter(pk=pk).first()
    if site is None:
        return JsonResponse({'detail': 'Site not found.'}, status=404)
    n, _ = site.blocks.filter(pk=block).delete()
    if not n:
        return JsonResponse({'detail': 'Block not found.'}, status=404)
    site.save(update_fields=['updated_at'])
    return JsonResponse(_site_dict(site))


@csrf_exempt
@require_http_methods(["POST"])
def api_blocks_reorder(request, pk):
    """Reorder by a list of block ids."""
    err = _require_module(request, 'sites')
    if err:
        return err
    site = ClientSite.objects.filter(pk=pk).first()
    if site is None:
        return JsonResponse({'detail': 'Site not found.'}, status=404)
    ids = _body(request).get('order') or []
    if not isinstance(ids, list):
        return JsonResponse({'detail': 'order must be a list of block ids.'}, status=400)
    owned = {b.id: b for b in site.blocks.all()}
    for i, bid in enumerate(ids):
        b = owned.get(bid)
        if b:
            b.order = i * 10
            b.save(update_fields=['order'])
    site.save(update_fields=['updated_at'])
    return JsonResponse(_site_dict(site))


# ══════════════════════════════════════════════════════════════════════════════
# Publish
# ══════════════════════════════════════════════════════════════════════════════

def _host_ip():
    """The address this server is reachable on.

    gethostbyname(gethostname()) returns 127.0.1.1 on Debian, which is a
    loopback alias and no use to anyone asking where a site is served from.
    Opening a UDP socket towards a public address sends no packets but makes
    the kernel choose the outbound interface, whose address is the useful one.
    """
    override = getattr(settings, 'PLATFORM_PUBLIC_IP', '')
    if override:
        return override
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(('1.1.1.1', 80))
        return s.getsockname()[0]
    except OSError:
        return ''
    finally:
        s.close()


def publish_site(site):
    """Render a site to disk and record where it went.

    Shared by the API and the auto-builder, so a site published by a client's
    reply lands byte-identically to one published by hand.

    Returns (ok, detail). The stock library is copied alongside on every
    publish: a page is never written with image URLs that do not resolve.
    """
    blocks = list(site.blocks.all())
    if not any(b.is_visible for b in blocks):
        return False, 'This site has no visible sections, so there is nothing to publish.'

    # Relative asset paths: the folder written here has to work under
    # /sites/<slug>/ and still work if it is copied somewhere else.
    html = sb.render_site(site, blocks, relative_assets=True)
    target_dir = os.path.join(SITES_ROOT, site.slug)
    try:
        os.makedirs(target_dir, exist_ok=True)
        stock.publish_library(SITES_ROOT)
        # Write then replace, so a visitor mid-request never sees a half file.
        tmp = os.path.join(target_dir, 'index.html.tmp')
        with open(tmp, 'w', encoding='utf-8') as fh:
            fh.write(html)
        os.replace(tmp, os.path.join(target_dir, 'index.html'))
    except OSError as e:
        logger.exception('[sites] could not write %s', target_dir)
        return False, f'Could not write the site to disk: {e}'

    ip = _host_ip()

    site.status = 'published'
    site.published_url = f'{SITES_BASE_URL.rstrip("/")}/{site.slug}/'
    site.published_ip = ip
    site.published_at = timezone.now()
    site.save(update_fields=['status', 'published_url', 'published_ip',
                             'published_at', 'updated_at'])
    logger.info('[sites] published %s -> %s (%s bytes)',
                site.slug, site.published_url, len(html))
    return True, len(html)


@csrf_exempt
@require_http_methods(["POST"])
def api_site_publish(request, pk):
    """Render the site to disk and return its live URL and host IP."""
    err = _require_module(request, 'sites')
    if err:
        return err
    site = ClientSite.objects.filter(pk=pk).first()
    if site is None:
        return JsonResponse({'detail': 'Site not found.'}, status=404)
    ok, detail = publish_site(site)
    if not ok:
        return JsonResponse({'detail': detail},
                            status=400 if 'no visible' in str(detail) else 500)
    return JsonResponse({**_site_dict(site), 'bytes': detail})


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_site_delete(request, pk):
    """Take a site down and remove it. The generated file goes too."""
    err = _require_module(request, 'sites')
    if err:
        return err
    site = ClientSite.objects.filter(pk=pk).first()
    if site is None:
        return JsonResponse({'detail': 'Site not found.'}, status=404)
    path = os.path.join(SITES_ROOT, site.slug, 'index.html')
    removed = False
    try:
        if os.path.isfile(path):
            os.remove(path)
            removed = True
        d = os.path.dirname(path)
        if os.path.isdir(d) and not os.listdir(d):
            os.rmdir(d)
    except OSError:
        logger.warning('[sites] could not remove files for %s', site.slug)
    slug = site.slug
    site.delete()
    return JsonResponse({'ok': True, 'deleted': slug, 'files_removed': removed})


# ══════════════════════════════════════════════════════════════════════════════
# Serving the generated files
# ══════════════════════════════════════════════════════════════════════════════

@require_http_methods(["GET", "HEAD"])
def serve_site_file(request, rest=''):
    """Serve a published site, or a file from the shared image library.

    In production nginx has a location for /sites/ and never reaches Django.
    This exists so the same URLs resolve locally - without it a preview shows
    the layout with every photograph broken, which is exactly the thing you
    need to see before publishing.

    Published sites are public by design, so this is not behind the module
    permission check. What it will not do is leave its own directory.
    """
    import mimetypes

    from django.http import FileResponse, Http404, HttpResponseNotModified

    rel = (rest or '').strip('/')
    root = os.path.realpath(SITES_ROOT)
    target = os.path.realpath(os.path.join(root, rel))
    # Containment, checked on the resolved path: ".." and symlinks both end up
    # somewhere real, and somewhere real is what has to be inside the root.
    if target != root and not target.startswith(root + os.sep):
        raise Http404
    if os.path.isdir(target):
        target = os.path.join(target, 'index.html')
    if not os.path.isfile(target):
        raise Http404

    ctype = mimetypes.guess_type(target)[0] or 'application/octet-stream'
    resp = FileResponse(open(target, 'rb'), content_type=ctype)
    # Generated pages change when someone republishes; the images never do.
    if rel.startswith('_stock/'):
        resp['Cache-Control'] = 'public, max-age=604800'
    else:
        resp['Cache-Control'] = 'public, max-age=60'
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp
