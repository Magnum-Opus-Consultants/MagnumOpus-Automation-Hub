"""The website generator: templates, palettes, a block library, and a renderer.

Modelled on how Odoo's website builder works - named templates that pick a
layout, a palette and a font pair; a library of pre-designed sections; and a
page stored as ordered data rather than markup. None of Odoo's code is used; it
is LGPL and this keeps the platform unencumbered.

The renderer emits ONE self-contained HTML file per site. No build step, no
framework, no JavaScript required to read the page - which means a generated
site can be served by nginx as a static file and will still work in ten years.

Four things carry the quality of the output:

* Templates decide the shape of the page and how the hero is built, so a
  logistics firm and a design studio do not come out looking identical.
* Every palette derives its own tints, gradients and dark footer from three
  hex values, so depth is consistent and no site needs hand-picked shades.
* Cards pick an icon from the words in their own title, so a services grid
  looks designed rather than generated.
* Sections alternate tone automatically, which is most of what separates a
  page that reads as "built" from one that reads as "dumped".
"""
import copy
import json
from string import Template
from xml.sax.saxutils import escape, quoteattr

# ══════════════════════════════════════════════════════════════════════════════
# Palettes
# ══════════════════════════════════════════════════════════════════════════════
# A palette declares only the decisions a human would make. Every tint, shadow
# and gradient below is derived from these, so a site cannot end up with text
# on a background someone chose later that it cannot be read against.

PALETTES = {
    'slate': {
        'brand': '#334155', 'brand_dark': '#1e293b', 'accent': '#0ea5e9',
        'ink': '#0f172a', 'muted': '#64748b', 'bg': '#ffffff',
        'wash': '#f8fafc', 'line': '#e2e8f0', 'on_brand': '#ffffff',
    },
    'ocean': {
        'brand': '#2563eb', 'brand_dark': '#1d4ed8', 'accent': '#06b6d4',
        'ink': '#0f172a', 'muted': '#64748b', 'bg': '#ffffff',
        'wash': '#f1f5f9', 'line': '#e2e8f0', 'on_brand': '#ffffff',
    },
    'forest': {
        'brand': '#15803d', 'brand_dark': '#166534', 'accent': '#65a30d',
        'ink': '#14201a', 'muted': '#5b6b60', 'bg': '#ffffff',
        'wash': '#f4f8f4', 'line': '#dfe8e0', 'on_brand': '#ffffff',
    },
    'sunset': {
        'brand': '#ea580c', 'brand_dark': '#c2410c', 'accent': '#f59e0b',
        'ink': '#231710', 'muted': '#7c6656', 'bg': '#ffffff',
        'wash': '#fff8f3', 'line': '#f0e2d6', 'on_brand': '#ffffff',
    },
    'plum': {
        'brand': '#7c3aed', 'brand_dark': '#6d28d9', 'accent': '#db2777',
        'ink': '#1e1436', 'muted': '#6b6382', 'bg': '#ffffff',
        'wash': '#faf7ff', 'line': '#e7e0f5', 'on_brand': '#ffffff',
    },
    'mono': {
        'brand': '#111111', 'brand_dark': '#000000', 'accent': '#555555',
        'ink': '#111111', 'muted': '#6b6b6b', 'bg': '#ffffff',
        'wash': '#f5f5f5', 'line': '#e3e3e3', 'on_brand': '#ffffff',
    },
}

# A Google Fonts link plus a stack that stands in if the link is blocked.
FONTS = {
    'modern': {
        'label': 'Modern',
        'link': 'https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap',
        'heading': "'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif",
        'body': "'Inter', -apple-system, 'Segoe UI', Roboto, sans-serif",
        'display_weight': '800', 'tracking': '-.028em',
    },
    'classic': {
        'label': 'Classic',
        'link': 'https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600;700'
                '&family=Source+Sans+3:wght@400;600&display=swap',
        'heading': "'Playfair Display', Georgia, serif",
        'body': "'Source Sans 3', -apple-system, 'Segoe UI', sans-serif",
        'display_weight': '700', 'tracking': '-.015em',
    },
    'technical': {
        'label': 'Technical',
        'link': 'https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600;700'
                '&family=IBM+Plex+Mono:wght@500&display=swap',
        'heading': "'IBM Plex Sans', -apple-system, sans-serif",
        'body': "'IBM Plex Sans', -apple-system, sans-serif",
        'display_weight': '700', 'tracking': '-.02em',
        'eyebrow': "'IBM Plex Mono', ui-monospace, monospace",
    },
    'friendly': {
        'label': 'Friendly',
        'link': 'https://fonts.googleapis.com/css2?family=Poppins:wght@500;600;700'
                '&family=Karla:wght@400;500;600&display=swap',
        'heading': "'Poppins', -apple-system, sans-serif",
        'body': "'Karla', -apple-system, 'Segoe UI', sans-serif",
        'display_weight': '700', 'tracking': '-.02em',
    },
}


# ══════════════════════════════════════════════════════════════════════════════
# Derived colour
# ══════════════════════════════════════════════════════════════════════════════

def _hex_to_rgb(h):
    h = (h or '#000000').lstrip('#')
    if len(h) == 3:
        h = ''.join(c * 2 for c in h)
    try:
        return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))
    except (ValueError, IndexError):
        return (0, 0, 0)


def _rgb_to_hex(rgb):
    return '#%02x%02x%02x' % tuple(max(0, min(255, round(c))) for c in rgb)


def _mix(a, b, t):
    """`t` of the way from colour a to colour b."""
    ra, rb = _hex_to_rgb(a), _hex_to_rgb(b)
    return _rgb_to_hex(tuple(x + (y - x) * t for x, y in zip(ra, rb)))


def _rgba(h, alpha):
    r, g, b = _hex_to_rgb(h)
    return f'rgba({r},{g},{b},{alpha})'


def _tokens(palette):
    """The full set of CSS values for a palette, tints and all."""
    p = dict(PALETTES.get(palette, PALETTES['slate']))
    brand, ink = p['brand'], p['ink']
    p.update({
        # Tints for badges, hovers and hairlines.
        'brand_soft': _mix(brand, '#ffffff', .92),
        'brand_edge': _mix(brand, '#ffffff', .74),
        'accent_soft': _mix(p['accent'], '#ffffff', .90),
        # A near-black that carries the brand hue, for the footer and dark bands.
        'dark': _mix(_mix(brand, '#000000', .72), ink, .35),
        'dark_soft': _mix(_mix(brand, '#000000', .5), ink, .3),
        # Hero mesh. Two washes rather than a flat fill, which is the single
        # biggest difference between a generated page and a designed one.
        'mesh_a': _rgba(brand, .16),
        'mesh_b': _rgba(p['accent'], .13),
        'shadow_sm': _rgba(ink, .05),
        'shadow_md': _rgba(ink, .08),
        'shadow_lg': _rgba(ink, .12),
        'brand_glow': _rgba(brand, .22),
        'on_dark_muted': 'rgba(255,255,255,.66)',
        'on_dark_line': 'rgba(255,255,255,.14)',
    })
    return p


# ══════════════════════════════════════════════════════════════════════════════
# Icons
# ══════════════════════════════════════════════════════════════════════════════
# 24x24, stroked, currentColor. Cards choose one from the words in their own
# title, which is what stops a services grid looking like a spreadsheet.

_I = ('<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7"'
      ' stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">%s</svg>')

ICONS = {
    'truck': _I % ('<path d="M3 7h11v9H3z"/><path d="M14 10h4l3 3v3h-7z"/>'
                   '<circle cx="7" cy="18.5" r="1.8"/><circle cx="17.5" cy="18.5" r="1.8"/>'),
    'code': _I % '<path d="M9 8l-4 4 4 4"/><path d="M15 8l4 4-4 4"/>',
    'chart': _I % ('<path d="M4 20V10"/><path d="M10 20V4"/><path d="M16 20v-7"/>'
                   '<path d="M2 20h20"/>'),
    'shield': _I % ('<path d="M12 3l7 3v6c0 4.2-2.9 7.6-7 9-4.1-1.4-7-4.8-7-9V6z"/>'
                    '<path d="M9 12l2 2 4-4"/>'),
    'users': _I % ('<circle cx="9" cy="8" r="3.2"/>'
                   '<path d="M3 20c0-3.3 2.7-5.5 6-5.5s6 2.2 6 5.5"/>'
                   '<path d="M16 5.5a3 3 0 010 5.6"/><path d="M18 20c0-2.6-1-4.3-2.5-5.2"/>'),
    'phone': _I % ('<path d="M6 3h3l2 5-2.5 1.5a11 11 0 006 6L16 13l5 2v3a2 2 0 01-2.2 2'
                   'A16 16 0 014 5.2A2 2 0 016 3z"/>'),
    'clock': _I % '<circle cx="12" cy="12" r="8.5"/><path d="M12 7.5V12l3.5 2"/>',
    'globe': _I % ('<circle cx="12" cy="12" r="8.5"/><path d="M3.5 12h17"/>'
                   '<path d="M12 3.5c2.6 2.4 4 5.4 4 8.5s-1.4 6.1-4 8.5"/>'
                   '<path d="M12 3.5c-2.6 2.4-4 5.4-4 8.5s1.4 6.1 4 8.5"/>'),
    'wrench': _I % ('<path d="M14.5 3a5.5 5.5 0 00-4.6 8.4L3 18.3 5.7 21l6.9-6.9A5.5 5.5 0'
                    '0 0020 9.5L16.8 12 12 7.2 14.5 3z"/>'),
    'cart': _I % ('<path d="M3 4h2l2.4 10.4A2 2 0 009.4 16h8.2a2 2 0 002-1.6L21 8H6"/>'
                  '<circle cx="10" cy="20" r="1.5"/><circle cx="18" cy="20" r="1.5"/>'),
    'camera': _I % ('<path d="M3 8h3l1.5-2h9L18 8h3v11H3z"/><circle cx="12" cy="13" r="3.4"/>'),
    'doc': _I % ('<path d="M6 3h8l4 4v14H6z"/><path d="M14 3v4h4"/><path d="M9 12h6"/>'
                 '<path d="M9 16h6"/>'),
    'spark': _I % ('<path d="M12 3l1.9 5.4L19 10l-5.1 1.6L12 17l-1.9-5.4L5 10l5.1-1.6z"/>'
                   '<path d="M18.5 16.5l.7 2 2 .7-2 .7-.7 2-.7-2-2-.7 2-.7z"/>'),
    'check': _I % '<circle cx="12" cy="12" r="8.5"/><path d="M8.2 12.4l2.6 2.6 5-5.4"/>',
    'pin': _I % ('<path d="M12 21s6.5-5.7 6.5-10.4A6.5 6.5 0 005.5 10.6C5.5 15.3 12 21 12 21z"/>'
                 '<circle cx="12" cy="10.4" r="2.4"/>'),
    'mail': _I % '<path d="M3 6h18v12H3z"/><path d="M3 7l9 6 9-6"/>',
    'home': _I % '<path d="M4 11l8-6.5 8 6.5V20H4z"/><path d="M10 20v-6h4v6"/>',
    'leaf': _I % '<path d="M20 4C10 4 4 9 4 16c0 2 .6 3.4.6 3.4S8 12 20 10c0 0-3 8-11 9"/>',
    'bolt': _I % '<path d="M13 3L5 14h5l-1 7 8-11h-5z"/>',
    'book': _I % ('<path d="M4 5.5A2.5 2.5 0 016.5 3H19v15H6.5A2.5 2.5 0 004 20.5z"/>'
                  '<path d="M19 18v3H6.5"/>'),
}

# Longest, most specific stems first, and matched against the whole phrase, so
# "import clearing" reaches globe rather than stopping at a generic word.
_ICON_WORDS = [
    (('freight', 'logistic', 'transport', 'courier', 'haul', 'fleet', 'deliver',
      'shipping', 'trucking', 'warehous'), 'truck'),
    (('software', 'develop', 'website', 'web app', 'mobile app', 'api',
      'integrat', 'platform', 'portal', 'code', 'automat'), 'code'),
    (('report', 'analytic', 'dashboard', 'data', 'insight', 'account',
      'financ', 'tax', 'audit', 'bookkeep', 'payroll', 'invoic'), 'chart'),
    (('secur', 'complian', 'insur', 'risk', 'protect', 'safety', 'guard',
      'warrant'), 'shield'),
    (('consult', 'advis', 'team', 'staff', 'recruit', 'human resource',
      'training', 'coach', 'mentor', 'partner'), 'users'),
    (('support', 'helpdesk', 'call cent', 'customer care', 'after-sales',
      'aftercare'), 'phone'),
    (('same day', 'same-day', 'turnaround', '24/7', '24 hour', 'schedul',
      'booking', 'appointment', 'response time'), 'clock'),
    (('import', 'export', 'customs', 'cross-border', 'internationa', 'global',
      'clearing', 'shipping line'), 'globe'),
    (('repair', 'maintain', 'maintenance', 'install', 'plumb', 'electric',
      'construct', 'renovat', 'fabricat', 'weld', 'machin', 'servicing'), 'wrench'),
    (('ecommerce', 'e-commerce', 'online store', 'shop', 'retail', 'checkout',
      'order', 'catalog', 'product range'), 'cart'),
    (('photo', 'video', 'brand', 'design', 'creative', 'content', 'social media',
      'marketing', 'campaign', 'copywrit'), 'camera'),
    (('document', 'policy', 'legal', 'contract', 'permit', 'licen',
      'certificat', 'paperwork', 'admin'), 'doc'),
    (('clean', 'hygien', 'laundry', 'sanit'), 'spark'),
    (('area', 'coverage', 'region', 'location', 'branch', 'depot', 'nationwide',
      'gauteng', 'cape town', 'durban', 'johannesburg'), 'pin'),
    (('contact', 'enquir', 'inquir', 'quote', 'get in touch', 'email'), 'mail'),
    (('property', 'home', 'household', 'residential', 'estate', 'rental'), 'home'),
    (('garden', 'landscap', 'agricultur', 'farm', 'environment', 'sustain',
      'solar', 'renewab'), 'leaf'),
    (('power', 'energy', 'speed', 'performance', 'growth'), 'bolt'),
    (('course', 'school', 'educat', 'learn', 'tutor', 'workshop', 'seminar'), 'book'),
]

# When nothing matches, cycle rather than repeat one icon fifteen times.
_ICON_CYCLE = ('spark', 'check', 'bolt', 'users', 'chart', 'globe')


def icon_for(text, index=0):
    """The icon name that best fits `text`, or a rotating default."""
    low = f' {(text or "").lower()} '
    for stems, name in _ICON_WORDS:
        if any(s in low for s in stems):
            return name
    return _ICON_CYCLE[index % len(_ICON_CYCLE)]


def _icon_svg(text, index=0):
    return ICONS.get(icon_for(text, index), ICONS['spark'])


# ══════════════════════════════════════════════════════════════════════════════
# Templates
# ══════════════════════════════════════════════════════════════════════════════
# A template is the shape of the page: which sections, in what order, and how
# the hero and the cards are built. It also carries a default palette and font
# pair, so choosing "Trades & services" is one decision, not four.
#
# hero:  split | centre | editorial | banner
# cards: icon  | plain
# heads: left  | centre

TEMPLATES = {
    'corporate': {
        'label': 'Corporate — consultancy, B2B, professional services',
        'blurb': 'Split hero, credibility numbers, services, process, contact.',
        'palette': 'ocean', 'font': 'modern',
        'hero': 'split', 'cards': 'icon', 'heads': 'left',
        'layout': ['hero', 'logos', 'about', 'services', 'stats', 'steps',
                   'features', 'gallery', 'testimonial', 'cta', 'contact'],
    },
    'service': {
        'label': 'Trades & services — local, on-site, quote-driven',
        'blurb': 'Bold centred hero, what we do, coverage, FAQ, strong contact.',
        'palette': 'slate', 'font': 'friendly',
        'hero': 'centre', 'cards': 'icon', 'heads': 'centre',
        'layout': ['hero', 'about', 'services', 'features', 'steps', 'stats',
                   'gallery', 'faq', 'cta', 'contact'],
    },
    'product': {
        'label': 'Software & product — SaaS, apps, platforms',
        'blurb': 'Hero with a product panel, features, how it works, pricing, FAQ.',
        'palette': 'plum', 'font': 'technical',
        'hero': 'split', 'cards': 'icon', 'heads': 'left',
        'layout': ['hero', 'about', 'features', 'steps', 'services', 'pricing',
                   'faq', 'cta', 'contact'],
    },
    'studio': {
        'label': 'Studio & creative — design, media, portfolio',
        'blurb': 'Editorial hero, big type, gallery, one quote, contact.',
        'palette': 'mono', 'font': 'classic',
        'hero': 'editorial', 'cards': 'plain', 'heads': 'left',
        'layout': ['hero', 'about', 'gallery', 'services', 'testimonial',
                   'cta', 'contact'],
    },
    'shop': {
        'label': 'Retail & shop — products, ranges, opening hours',
        'blurb': 'Image hero, product ranges, gallery, where to find us.',
        'palette': 'sunset', 'font': 'friendly',
        'hero': 'banner', 'cards': 'icon', 'heads': 'centre',
        'layout': ['hero', 'about', 'services', 'gallery', 'features', 'stats',
                   'cta', 'contact'],
    },
    'onepager': {
        'label': 'One-pager — a clean single page, nothing spare',
        'blurb': 'Hero, about, what we do, contact. Four sections, no filler.',
        'palette': 'slate', 'font': 'modern',
        'hero': 'centre', 'cards': 'icon', 'heads': 'centre',
        'layout': ['hero', 'about', 'services', 'cta', 'contact'],
    },
}

DEFAULT_TEMPLATE = 'corporate'
TEMPLATE_CHOICES = [(k, v['label']) for k, v in TEMPLATES.items()]


def template_for(kind='', text=''):
    """Pick a template from what the client actually said they wanted.

    `kind` is the request type on the record; `text` is every answer joined.
    Keyword-matched rather than asked, because the whole point is that a reply
    turns into a site without anyone choosing anything.
    """
    low = f' {(text or "").lower()} '

    def has(*stems):
        return any(s in low for s in stems)

    if has('saas', 'web app', 'mobile app', 'platform', 'dashboard', 'login',
           'user accounts', 'subscription', 'api', 'crm', 'erp', 'portal',
           'booking system', 'management system'):
        return 'product'
    if has('online store', 'ecommerce', 'e-commerce', 'shop', 'checkout',
           'product range', 'stock', 'retail', 'basket', 'catalogue'):
        return 'shop'
    if has('portfolio', 'gallery', 'photograph', 'design studio', 'agency',
           'creative', 'artist', 'film', 'brand identity', 'interior'):
        return 'studio'
    if has('plumb', 'electric', 'builder', 'construction', 'repair', 'install',
           'maintenance', 'cleaning', 'landscap', 'pest', 'towing', 'mechanic',
           'on-site', 'callout', 'call-out'):
        return 'service'
    if has('consult', 'advisory', 'accounting', 'legal', 'audit', 'logistics',
           'freight', 'clearing', 'b2b', 'corporate', 'enterprise', 'tender'):
        return 'corporate'
    if (kind or '').lower() == 'website' and len(low) < 400:
        return 'onepager'
    return DEFAULT_TEMPLATE


# ══════════════════════════════════════════════════════════════════════════════
# Block library
# ══════════════════════════════════════════════════════════════════════════════
# Each entry declares the fields a block holds and what a fresh one starts as.
# `fields` drives the editor in the UI, so adding a block type here is all it
# takes for it to become editable - no form to hand-write.
#
# Field types: text, textarea, url, list (list of strings),
#              items (list of {title, body} pairs)

BLOCK_LIBRARY = {
    'hero': {
        'label': 'Hero',
        'blurb': 'The first thing a visitor sees: headline, one line, a button.',
        'fields': [
            ('eyebrow', 'text', 'Small label above the headline'),
            ('heading', 'text', 'Headline'),
            ('sub', 'textarea', 'Supporting line'),
            ('cta_label', 'text', 'Button text'),
            ('cta_href', 'url', 'Button link'),
            ('alt_label', 'text', 'Second button text'),
            ('alt_href', 'url', 'Second button link'),
            ('points', 'list', 'Ticks under the buttons'),
            ('image', 'url', 'Image or background URL'),
        ],
        'default': {
            'eyebrow': '',
            'heading': 'A headline that says what you do',
            'sub': 'One sentence explaining who it is for and why it matters.',
            'cta_label': 'Get in touch',
            'cta_href': '#contact',
            'alt_label': '', 'alt_href': '',
            'points': [],
            'image': '',
        },
    },
    'about': {
        'label': 'About',
        'blurb': 'A paragraph or two of context.',
        'fields': [
            ('eyebrow', 'text', 'Small label'),
            ('heading', 'text', 'Heading'),
            ('body', 'textarea', 'Body'),
            ('points', 'list', 'Ticked points beside it'),
            ('image', 'url', 'Image URL'),
        ],
        'default': {
            'eyebrow': '',
            'heading': 'About us',
            'body': 'Who you are, what you do, and what makes it worth choosing.',
            'points': [],
            'image': '',
        },
    },
    'services': {
        'label': 'Services',
        'blurb': 'What you offer, as a grid of cards with icons.',
        'fields': [
            ('eyebrow', 'text', 'Small label'),
            ('heading', 'text', 'Heading'),
            ('sub', 'textarea', 'Line under the heading'),
            ('items', 'items', 'Services'),
        ],
        'default': {
            'eyebrow': 'What we do',
            'heading': 'Services',
            'sub': '',
            'items': [
                {'title': 'First service', 'body': 'A line about it.'},
                {'title': 'Second service', 'body': 'A line about it.'},
                {'title': 'Third service', 'body': 'A line about it.'},
            ],
        },
    },
    'features': {
        'label': 'Why us',
        'blurb': 'Points in your favour, as a list with ticks.',
        'fields': [
            ('eyebrow', 'text', 'Small label'),
            ('heading', 'text', 'Heading'),
            ('sub', 'textarea', 'Line under the heading'),
            ('items', 'items', 'Points'),
        ],
        'default': {
            'eyebrow': 'Why us',
            'heading': 'What you get working with us',
            'sub': '',
            'items': [
                {'title': 'Reason one', 'body': 'Say it plainly.'},
                {'title': 'Reason two', 'body': 'Say it plainly.'},
            ],
        },
    },
    'steps': {
        'label': 'How it works',
        'blurb': 'A numbered process, three or four steps.',
        'fields': [
            ('eyebrow', 'text', 'Small label'),
            ('heading', 'text', 'Heading'),
            ('items', 'items', 'Steps'),
        ],
        'default': {
            'eyebrow': 'How it works',
            'heading': 'Getting started takes three steps',
            'items': [
                {'title': 'Tell us what you need',
                 'body': 'A call or an email is enough to start.'},
                {'title': 'We come back with a plan and a price',
                 'body': 'In writing, with nothing hidden in it.'},
                {'title': 'We get it done',
                 'body': 'And stay reachable afterwards.'},
            ],
        },
    },
    'stats': {
        'label': 'Numbers',
        'blurb': 'Three or four figures worth stating.',
        'fields': [
            ('heading', 'text', 'Heading'),
            ('items', 'items', 'Figures (title = the number)'),
        ],
        'default': {
            'heading': '',
            'items': [
                {'title': '10+', 'body': 'Years doing this'},
                {'title': '250', 'body': 'Projects delivered'},
                {'title': '24/7', 'body': 'Support'},
            ],
        },
    },
    'logos': {
        'label': 'Trust strip',
        'blurb': 'A quiet row of client names or credentials under the hero.',
        'fields': [
            ('heading', 'text', 'Lead-in line'),
            ('items_list', 'list', 'Names'),
        ],
        'default': {'heading': '', 'items_list': []},
    },
    'gallery': {
        'label': 'Gallery',
        'blurb': 'A grid of images.',
        'fields': [
            ('eyebrow', 'text', 'Small label'),
            ('heading', 'text', 'Heading'),
            ('images', 'list', 'Image URLs'),
        ],
        'default': {'eyebrow': '', 'heading': 'Our work', 'images': []},
    },
    'testimonial': {
        'label': 'Testimonial',
        'blurb': 'One quote, attributed. Left out unless there is a real one.',
        'fields': [
            ('quote', 'textarea', 'Quote'),
            ('name', 'text', 'Who said it'),
            ('role', 'text', 'Their role or company'),
        ],
        'default': {'quote': '', 'name': '', 'role': ''},
    },
    'pricing': {
        'label': 'Pricing',
        'blurb': 'Packages, as columns.',
        'fields': [
            ('eyebrow', 'text', 'Small label'),
            ('heading', 'text', 'Heading'),
            ('sub', 'textarea', 'Line under the heading'),
            ('items', 'items', 'Packages (title = name and price)'),
        ],
        'default': {
            'eyebrow': 'Pricing',
            'heading': 'Straightforward pricing',
            'sub': '',
            'items': [
                {'title': 'Starter', 'body': 'What is included.'},
                {'title': 'Standard', 'body': 'What is included.'},
            ],
        },
    },
    'faq': {
        'label': 'FAQ',
        'blurb': 'Questions and answers, as accordions. No JavaScript.',
        'fields': [
            ('eyebrow', 'text', 'Small label'),
            ('heading', 'text', 'Heading'),
            ('items', 'items', 'Questions (title = the question)'),
        ],
        'default': {
            'eyebrow': 'FAQ',
            'heading': 'Questions we get asked',
            'items': [{'title': 'A question', 'body': 'The answer.'}],
        },
    },
    'text': {
        'label': 'Text',
        'blurb': 'A plain section of prose.',
        'fields': [
            ('eyebrow', 'text', 'Small label'),
            ('heading', 'text', 'Heading'),
            ('body', 'textarea', 'Body'),
        ],
        'default': {'eyebrow': '', 'heading': '', 'body': ''},
    },
    'cta': {
        'label': 'Call to action',
        'blurb': 'A band that asks for the next step.',
        'fields': [
            ('heading', 'text', 'Heading'),
            ('sub', 'text', 'Supporting line'),
            ('cta_label', 'text', 'Button text'),
            ('cta_href', 'url', 'Button link'),
        ],
        'default': {
            'heading': 'Ready to start?',
            'sub': 'Tell us what you need and we will come back to you.',
            'cta_label': 'Contact us',
            'cta_href': '#contact',
        },
    },
    'contact': {
        'label': 'Contact',
        'blurb': 'How to reach you, with the email as a real button.',
        'fields': [
            ('eyebrow', 'text', 'Small label'),
            ('heading', 'text', 'Heading'),
            ('body', 'textarea', 'Intro line'),
            ('email', 'text', 'Email'),
            ('phone', 'text', 'Phone'),
            ('address', 'textarea', 'Address'),
            ('hours', 'text', 'Opening hours'),
        ],
        'default': {
            'eyebrow': 'Contact',
            'heading': 'Get in touch',
            'body': 'We usually reply within one working day.',
            'email': '', 'phone': '', 'address': '', 'hours': '',
        },
    },
}

# The order a fresh site is assembled in when no template is chosen.
DEFAULT_LAYOUT = TEMPLATES[DEFAULT_TEMPLATE]['layout']


def layout_for(template):
    return list(TEMPLATES.get(template, TEMPLATES[DEFAULT_TEMPLATE])['layout'])


def new_block_content(kind):
    """A fresh copy of a block's defaults, safe to mutate."""
    return copy.deepcopy(BLOCK_LIBRARY.get(kind, {}).get('default', {}))


# ══════════════════════════════════════════════════════════════════════════════
# Rendering helpers
# ══════════════════════════════════════════════════════════════════════════════

def _e(v):
    return escape('' if v is None else str(v))


def _attr(v):
    return quoteattr('' if v is None else str(v))


def _safe_href(v, fallback='#contact'):
    """Only hrefs that cannot execute anything.

    Answers arrive from strangers and a reference link goes straight into the
    page, so `javascript:` and `data:` are refused outright rather than
    escaped: escaping makes them inert in an attribute, not in a URL scheme.
    """
    v = (v or '').strip()
    if not v:
        return fallback
    if v.lower().startswith(('http://', 'https://', 'mailto:', 'tel:', '#', '/')):
        return v
    return fallback


def _safe_img(v):
    """An image URL, or nothing. Same reasoning as _safe_href."""
    v = (v or '').strip()
    return v if v.lower().startswith(('http://', 'https://', '/')) else ''


def _p(text):
    """Plain text to paragraphs, preserving intentional breaks."""
    blocks = [b.strip() for b in str(text or '').split('\n\n') if b.strip()]
    return ''.join('<p>' + _e(b).replace('\n', '<br>') + '</p>' for b in blocks)


def _items(c):
    out = []
    for it in (c.get('items') or []):
        if isinstance(it, dict) and (it.get('title') or it.get('body')):
            out.append({'title': (it.get('title') or '').strip(),
                        'body': (it.get('body') or '').strip()})
    return out


def _head(c, ctx, tag='h2'):
    """Eyebrow, heading and sub-line as one aligned group."""
    parts = []
    if (c.get('eyebrow') or '').strip():
        parts.append(f'<p class="eyebrow">{_e(c["eyebrow"])}</p>')
    if (c.get('heading') or '').strip():
        parts.append(f'<{tag}>{_e(c["heading"])}</{tag}>')
    if (c.get('sub') or '').strip():
        parts.append(f'<p class="lead">{_e(c["sub"])}</p>')
    if not parts:
        return ''
    align = ' centre' if ctx['heads'] == 'centre' else ''
    return f'<header class="sec-head{align}">{"".join(parts)}</header>'


def _btn(label, href, cls='btn', fallback='#contact'):
    label = (label or '').strip()
    if not label:
        return ''
    return f'<a class="{cls}" href={_attr(_safe_href(href, fallback))}>{_e(label)}</a>'


def _ticks(values):
    lis = ''.join(f'<li>{ICONS["check"]}<span>{_e(v)}</span></li>'
                  for v in (values or []) if str(v).strip())
    return f'<ul class="ticks">{lis}</ul>' if lis else ''


def _section(inner, ctx, cls='', ident=''):
    i = f' id={_attr(ident)}' if ident else ''
    classes = ' '.join(x for x in ('sec', ctx.get('tone', ''), cls) if x)
    return f'<section class="{classes}"{i}><div class="wrap">{inner}</div></section>'


# ══════════════════════════════════════════════════════════════════════════════
# Block renderers
# ══════════════════════════════════════════════════════════════════════════════

def _render_hero(c, site, ctx):
    variant = ctx['hero']
    img = _safe_img(c.get('image'))

    eyebrow = (f'<p class="eyebrow">{_e(c["eyebrow"])}</p>'
               if (c.get('eyebrow') or '').strip() else '')
    heading = f'<h1>{_e(c.get("heading"))}</h1>'
    sub = (f'<p class="lead">{_e(c["sub"])}</p>'
           if (c.get('sub') or '').strip() else '')
    buttons = (_btn(c.get('cta_label'), c.get('cta_href'))
               + _btn(c.get('alt_label'), c.get('alt_href'), cls='btn btn-ghost'))
    actions = f'<div class="actions">{buttons}</div>' if buttons else ''
    points = _ticks(c.get('points'))
    text = f'{eyebrow}{heading}{sub}{actions}{points}'

    if variant == 'banner' and img:
        # Full-bleed photograph. Two stops in the overlay rather than one, so
        # the text keeps its contrast and the image still reads lower down.
        return (f'<section class="sec hero hero-banner" id="top" '
                f'style="background-image:linear-gradient('
                f'rgba(8,12,20,.72),rgba(8,12,20,.45)),url({_e(img)})">'
                f'<div class="wrap"><div class="hero-text">{text}</div></div></section>')

    if variant == 'editorial':
        return (f'<section class="sec hero hero-editorial" id="top"><div class="wrap">'
                f'<div class="hero-text">{eyebrow}{heading}</div>'
                f'<div class="rule"></div>'
                f'<div class="hero-editorial-foot">{sub}{actions}</div>'
                f'{points}</div></section>')

    if variant == 'split':
        # The panel is drawn in CSS when there is no photograph, so the hero is
        # never a wall of text and never waits on an asset the client has not
        # sent yet.
        aside = (f'<div class="hero-media"><img src={_attr(img)} alt=""></div>'
                 if img else _hero_panel(site, c))
        return (f'<section class="sec hero hero-split" id="top"><div class="wrap">'
                f'<div class="hero-grid"><div class="hero-text">{text}</div>'
                f'{aside}</div></div></section>')

    return (f'<section class="sec hero hero-centre" id="top"><div class="wrap">'
            f'<div class="hero-text">{text}</div></div></section>')


def _hero_panel(site, c):
    """A stand-in visual: the business name set as a mark, over a soft card."""
    name = (site.site_name or site.client_name or '').strip()
    lines = [str(p).strip() for p in (c.get('points') or []) if str(p).strip()][:3]
    rows = ''.join(f'<li>{ICONS["check"]}<span>{_e(l)}</span></li>' for l in lines)
    body = f'<ul class="panel-list">{rows}</ul>' if rows else ''
    return (f'<div class="hero-panel" aria-hidden="true">'
            f'<div class="panel-card">'
            f'<div class="panel-top"><span class="mark">{_e(_initials(name))}</span>'
            f'<span class="panel-name">{_e(name)}</span></div>'
            f'{body}<div class="panel-bars"><i></i><i></i><i></i></div>'
            f'</div></div>')


def _render_about(c, site, ctx):
    img = _safe_img(c.get('image'))
    aside = (f'<div class="media"><img src={_attr(img)} alt="" loading="lazy"></div>'
             if img else '')
    prose = f'<div class="prose">{_p(c.get("body"))}</div>{_ticks(c.get("points"))}'
    inner = _head(c, ctx) + (f'<div class="split">{prose}{aside}</div>' if aside
                             else f'<div class="prose-wide">{prose}</div>')
    return _section(inner, ctx, ident='about')


def _cards(items, kind='icon'):
    out = []
    for i, it in enumerate(items):
        body = f'<p>{_e(it["body"])}</p>' if it['body'] else ''
        if kind == 'plain':
            out.append(f'<article class="card card-plain" style="--i:{i}">'
                       f'<h3>{_e(it["title"])}</h3>{body}</article>')
        else:
            out.append(f'<article class="card" style="--i:{i}">'
                       f'<span class="card-icon">'
                       f'{_icon_svg(it["title"] or it["body"], i)}</span>'
                       f'<h3>{_e(it["title"])}</h3>{body}</article>')
    if not out:
        return ''
    cols = ('grid-1' if len(out) == 1
            else 'grid-2' if len(out) in (2, 4) else 'grid-3')
    return f'<div class="grid {cols}">{"".join(out)}</div>'


def _render_services(c, site, ctx):
    items = _items(c)
    if not items:
        return ''
    return _section(_head(c, ctx) + _cards(items, ctx['cards']), ctx, ident='services')


def _render_features(c, site, ctx):
    items = _items(c)
    if not items:
        return ''
    rows = ''.join(
        f'<li style="--i:{i}"><span class="tick">{ICONS["check"]}</span>'
        f'<div><h3>{_e(it["title"])}</h3>'
        + (f'<p>{_e(it["body"])}</p>' if it['body'] else '')
        + '</div></li>'
        for i, it in enumerate(items))
    return _section(_head(c, ctx) + f'<ul class="feature-list">{rows}</ul>',
                    ctx, cls='features')


def _render_steps(c, site, ctx):
    items = _items(c)
    if not items:
        return ''
    rows = ''.join(
        f'<li style="--i:{i}"><span class="step-no">{i + 1}</span>'
        f'<h3>{_e(it["title"])}</h3>'
        + (f'<p>{_e(it["body"])}</p>' if it['body'] else '')
        + '</li>'
        for i, it in enumerate(items))
    return _section(_head(c, ctx) + f'<ol class="steps">{rows}</ol>', ctx, cls='stepped')


def _render_stats(c, site, ctx):
    items = _items(c)
    if not items:
        return ''
    head = (f'<header class="sec-head centre"><h2>{_e(c["heading"])}</h2></header>'
            if (c.get('heading') or '').strip() else '')
    cards = ''.join(
        f'<article class="stat" style="--i:{i}">'
        f'<span class="figure">{_e(it["title"])}</span>'
        f'<span class="figure-label">{_e(it["body"])}</span></article>'
        for i, it in enumerate(items))
    cols = ('grid-1' if len(items) == 1
            else 'grid-2' if len(items) in (2, 4) else 'grid-3')
    # Always on the dark band: numbers are the one thing worth interrupting the
    # page's rhythm for.
    return (f'<section class="sec dark stats"><div class="wrap">{head}'
            f'<div class="grid {cols}">{cards}</div></div></section>')


def _render_logos(c, site, ctx):
    names = [str(v).strip() for v in (c.get('items_list') or []) if str(v).strip()]
    if not names:
        return ''
    lead = (f'<p class="strip-lead">{_e(c["heading"])}</p>'
            if (c.get('heading') or '').strip() else '')
    pills = ''.join(f'<span class="pill">{_e(n)}</span>' for n in names[:8])
    return (f'<section class="strip"><div class="wrap">{lead}'
            f'<div class="pills">{pills}</div></div></section>')


def _render_gallery(c, site, ctx):
    urls = [u for u in (_safe_img(x) for x in (c.get('images') or [])) if u]
    if not urls:
        return ''
    figs = ''.join(
        f'<figure style="--i:{i}"><img src={_attr(u)} alt="" loading="lazy"></figure>'
        for i, u in enumerate(urls))
    return _section(_head(c, ctx) + f'<div class="gallery">{figs}</div>',
                    ctx, ident='work')


def _render_testimonial(c, site, ctx):
    quote = (c.get('quote') or '').strip()
    # No quote, no section. An invented testimonial is worse than none, and a
    # placeholder one gets published by accident.
    if not quote:
        return ''
    who = ' — '.join(x for x in ((c.get('name') or '').strip(),
                                 (c.get('role') or '').strip()) if x)
    cite = f'<cite>{_e(who)}</cite>' if who else ''
    return _section(f'<blockquote><span class="quote-mark">&ldquo;</span>'
                    f'<p>{_e(quote)}</p>{cite}</blockquote>', ctx, cls='quote')


def _render_pricing(c, site, ctx):
    items = _items(c)
    if not items:
        return ''
    cards = []
    for i, it in enumerate(items):
        # The middle column is the one people pick, so it is the one that looks
        # picked.
        feat = ' featured' if len(items) >= 3 and i == 1 else ''
        lines = [l.strip(' -•\t') for l in it['body'].split('\n')
                 if l.strip(' -•\t')]
        body = ((f'<ul class="ticks">'
                 + ''.join(f'<li>{ICONS["check"]}<span>{_e(l)}</span></li>' for l in lines)
                 + '</ul>') if len(lines) > 1 else f'<p>{_e(it["body"])}</p>')
        cards.append(f'<article class="price{feat}" style="--i:{i}">'
                     f'<h3>{_e(it["title"])}</h3>{body}'
                     f'<a class="btn btn-quiet" href="#contact">Enquire</a></article>')
    cols = 'grid-2' if len(cards) == 2 else 'grid-3'
    return _section(_head(c, ctx) + f'<div class="grid {cols}">{"".join(cards)}</div>',
                    ctx, ident='pricing')


def _render_faq(c, site, ctx):
    items = _items(c)
    if not items:
        return ''
    rows = ''.join(
        f'<details{" open" if i == 0 else ""}><summary>{_e(it["title"])}'
        f'<span class="chev"></span></summary>'
        f'<div class="answer">{_p(it["body"])}</div></details>'
        for i, it in enumerate(items))
    return _section(_head(c, ctx) + f'<div class="faq">{rows}</div>', ctx, ident='faq')


def _render_text(c, site, ctx):
    if not (c.get('body') or '').strip() and not (c.get('heading') or '').strip():
        return ''
    return _section(_head(c, ctx)
                    + f'<div class="prose-wide"><div class="prose">'
                      f'{_p(c.get("body"))}</div></div>', ctx)


def _render_cta(c, site, ctx):
    inner = (f'<h2>{_e(c.get("heading"))}</h2>'
             + (f'<p class="lead">{_e(c["sub"])}</p>' if (c.get('sub') or '').strip() else '')
             + f'<div class="actions">'
               f'{_btn(c.get("cta_label"), c.get("cta_href"), cls="btn btn-invert")}'
               f'</div>')
    return f'<section class="sec band"><div class="wrap">{inner}</div></section>'


def _render_contact(c, site, ctx):
    email = (c.get('email') or '').strip()
    phone = (c.get('phone') or '').strip()
    rows = []
    if email:
        rows.append((ICONS['mail'], 'Email',
                     f'<a href="mailto:{_e(email)}">{_e(email)}</a>'))
    if phone:
        rows.append((ICONS['phone'], 'Phone',
                     f'<a href="tel:{_e(phone.replace(" ", ""))}">{_e(phone)}</a>'))
    if (c.get('address') or '').strip():
        rows.append((ICONS['pin'], 'Address', _e(c['address']).replace('\n', '<br>')))
    if (c.get('hours') or '').strip():
        rows.append((ICONS['clock'], 'Hours', _e(c['hours'])))

    cards = ''.join(
        f'<div class="contact-card" style="--i:{i}">'
        f'<span class="card-icon">{ic}</span>'
        f'<span class="contact-label">{lbl}</span>'
        f'<span class="contact-value">{val}</span></div>'
        for i, (ic, lbl, val) in enumerate(rows))
    action = (f'<div class="actions"><a class="btn" href="mailto:{_e(email)}">'
              f'Send an email</a></div>' if email else '')
    inner = (_head(c, ctx)
             + f'<div class="prose-wide"><div class="prose">{_p(c.get("body"))}</div></div>'
             + (f'<div class="contact-grid">{cards}</div>' if cards else '')
             + action)
    return _section(inner, ctx, ident='contact')


RENDERERS = {
    'hero': _render_hero, 'about': _render_about, 'services': _render_services,
    'features': _render_features, 'steps': _render_steps, 'stats': _render_stats,
    'logos': _render_logos, 'gallery': _render_gallery,
    'testimonial': _render_testimonial, 'pricing': _render_pricing,
    'faq': _render_faq, 'text': _render_text, 'cta': _render_cta,
    'contact': _render_contact,
}

# Sections whose background is part of their design, so the alternating rhythm
# skips them instead of fighting them.
_FIXED_TONE = {'hero', 'stats', 'cta', 'logos'}


# ══════════════════════════════════════════════════════════════════════════════
# Stylesheet
# ══════════════════════════════════════════════════════════════════════════════
# Written with $tokens rather than str.format braces, so the CSS below reads as
# CSS instead of as escaped punctuation.

_CSS = Template("""
*,*::before,*::after{box-sizing:border-box}
:root{
  color-scheme:light;
  --brand:$brand; --brand-dark:$brand_dark; --accent:$accent;
  --brand-soft:$brand_soft; --brand-edge:$brand_edge;
  --ink:$ink; --muted:$muted; --bg:$bg; --wash:$wash; --line:$line;
  --on-brand:$on_brand; --dark:$dark; --dark-soft:$dark_soft;
  --sh-sm:0 1px 2px $shadow_sm; --sh-md:0 6px 20px -6px $shadow_md;
  --sh-lg:0 24px 48px -20px $shadow_lg;
  --r:14px; --r-lg:20px;
  --pad:clamp(56px,6vw,88px);
}
html{scroll-behavior:smooth;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
  font-family:$body_font;font-size:17px;line-height:1.65;
  -webkit-font-smoothing:antialiased;text-rendering:optimizeLegibility}
h1,h2,h3{font-family:$heading_font;line-height:1.14;margin:0 0 .5em;
  letter-spacing:$tracking;text-wrap:balance}
h1{font-size:clamp(2.15rem,1.2rem + 3.4vw,3.75rem);font-weight:$display_weight}
h2{font-size:clamp(1.6rem,1.1rem + 1.7vw,2.5rem);font-weight:$display_weight}
h3{font-size:1.09rem;font-weight:600;line-height:1.35;margin-bottom:.3em;
  letter-spacing:-.01em}
p{margin:0 0 1em}
a{color:var(--brand);text-underline-offset:3px}
img{max-width:100%;height:auto;display:block}
ul,ol{margin:0;padding:0;list-style:none}
::selection{background:var(--brand);color:var(--on-brand)}
:focus-visible{outline:2px solid var(--brand);outline-offset:3px;border-radius:4px}

.wrap{max-width:1120px;margin:0 auto;padding:0 clamp(20px,4vw,32px)}
.sec{padding:var(--pad) 0;position:relative}
.sec.wash{background:var(--wash)}
.lead{font-size:1.1rem;line-height:1.6;color:var(--muted);max-width:62ch;margin:0}
.eyebrow{margin:0 0 14px;font-family:$eyebrow_font;font-size:.72rem;font-weight:600;
  letter-spacing:.13em;text-transform:uppercase;color:var(--brand)}

/* Section headers */
.sec-head{max-width:64ch;margin:0 0 clamp(34px,4vw,52px)}
.sec-head h2{margin:0 0 .35em}
.sec-head.centre{margin-left:auto;margin-right:auto;text-align:center}
.sec-head.centre .lead{margin:0 auto}

/* Nav */
.nav{position:sticky;top:0;z-index:20;background:$nav_bg;
  border-bottom:1px solid var(--line)}
@supports (backdrop-filter:blur(10px)){
  .nav{backdrop-filter:saturate(1.6) blur(12px)}
}
.nav .wrap{display:flex;align-items:center;gap:18px;min-height:66px}
.brand{display:flex;align-items:center;gap:11px;font-family:$heading_font;
  font-weight:700;font-size:1.06rem;color:var(--ink);text-decoration:none;
  letter-spacing:-.02em}
.brand img{height:34px;width:auto;border-radius:8px}
.brand .mark{display:grid;place-items:center;width:34px;height:34px;border-radius:10px;
  background:linear-gradient(140deg,var(--brand),var(--accent));color:var(--on-brand);
  font-size:.8rem;font-weight:700;letter-spacing:.02em;box-shadow:var(--sh-sm);
  flex:0 0 34px}
.nav nav{margin-left:auto;display:flex;align-items:center;gap:clamp(14px,2vw,28px)}
.nav nav a{color:var(--muted);text-decoration:none;font-size:.94rem;font-weight:500;
  transition:color .15s}
.nav nav a:hover{color:var(--ink)}
.nav .nav-cta{background:var(--brand);color:var(--on-brand);padding:9px 18px;
  border-radius:999px;font-weight:600;font-size:.9rem;box-shadow:var(--sh-sm);
  transition:background .15s,transform .15s}
.nav .nav-cta:hover{background:var(--brand-dark);color:var(--on-brand);
  transform:translateY(-1px)}
@media(max-width:720px){.nav nav a:not(.nav-cta){display:none}}

/* Buttons */
.actions{display:flex;flex-wrap:wrap;gap:12px;margin-top:30px}
.btn{display:inline-flex;align-items:center;justify-content:center;
  background:var(--brand);color:var(--on-brand);padding:14px 30px;border-radius:999px;
  text-decoration:none;font-weight:600;font-size:1rem;letter-spacing:-.01em;
  box-shadow:0 8px 20px -10px $brand_glow;
  transition:background .16s,transform .16s,box-shadow .16s}
.btn:hover{background:var(--brand-dark);transform:translateY(-2px);
  box-shadow:0 14px 26px -12px $brand_glow}
.btn-ghost{background:transparent;color:var(--ink);box-shadow:none;
  border:1px solid var(--line)}
.btn-ghost:hover{background:var(--wash);color:var(--ink);border-color:var(--brand-edge)}
.btn-invert{background:var(--bg);color:var(--brand);box-shadow:var(--sh-md)}
.btn-invert:hover{background:var(--bg);color:var(--brand-dark)}
.btn-quiet{background:var(--brand-soft);color:var(--brand-dark);box-shadow:none;
  padding:11px 22px;font-size:.94rem;margin-top:18px}
.btn-quiet:hover{background:var(--brand-edge);color:var(--brand-dark)}

/* Hero */
.hero{padding:clamp(64px,7vw,112px) 0 clamp(56px,6vw,96px);isolation:isolate;
  overflow:hidden}
.hero::before{content:"";position:absolute;inset:-30% -10% auto -10%;height:150%;
  z-index:-1;
  background:
    radial-gradient(46% 52% at 78% 12%,$mesh_b 0%,transparent 70%),
    radial-gradient(52% 58% at 12% 0%,$mesh_a 0%,transparent 72%),
    linear-gradient(180deg,var(--wash) 0%,var(--bg) 82%)}
.hero h1{margin:0 0 20px;max-width:22ch}
.hero .lead{font-size:clamp(1.06rem,1rem + .35vw,1.25rem);max-width:56ch}
.hero-centre{text-align:center}
.hero-centre .hero-text{max-width:44rem;margin:0 auto}
.hero-centre h1{max-width:none}
.hero-centre .lead{margin:0 auto}
.hero-centre .actions,.hero-centre .ticks{justify-content:center}

.hero-grid{display:grid;gap:clamp(36px,5vw,64px);align-items:center}
@media(min-width:900px){.hero-grid{grid-template-columns:1.05fr .95fr}}
.hero-media img{border-radius:var(--r-lg);box-shadow:var(--sh-lg);width:100%;
  aspect-ratio:4/3;object-fit:cover}

.hero-banner{color:#fff;background-size:cover;background-position:center;
  padding:clamp(90px,12vw,168px) 0}
.hero-banner::before{display:none}
.hero-banner h1,.hero-banner .lead{color:#fff}
.hero-banner .lead{opacity:.9}
.hero-banner .eyebrow{color:#fff;opacity:.85}
.hero-banner .btn-ghost{color:#fff;border-color:rgba(255,255,255,.45)}
.hero-banner .btn-ghost:hover{background:rgba(255,255,255,.12);color:#fff}
.hero-banner .ticks li{color:#fff}
.hero-banner .hero-text{max-width:46rem}

.hero-editorial h1{font-size:clamp(2.4rem,1rem + 5.4vw,4.6rem);max-width:24ch}
.hero-editorial .rule{height:1px;background:var(--line);margin:clamp(28px,4vw,44px) 0}
.hero-editorial-foot{display:grid;gap:24px}
@media(min-width:820px){
  .hero-editorial-foot{grid-template-columns:1.4fr .6fr;align-items:end}
  .hero-editorial-foot .actions{margin-top:0;justify-content:flex-end}
}

.ticks{display:flex;flex-wrap:wrap;gap:10px 26px;margin-top:28px}
.ticks li{display:flex;align-items:flex-start;gap:8px;font-size:.95rem;
  color:var(--muted);font-weight:500}
.ticks svg{width:18px;height:18px;flex:0 0 18px;margin-top:2px;color:var(--brand)}

/* The drawn stand-in panel, for when the client has sent no imagery. */
.panel-card{background:var(--bg);border:1px solid var(--line);border-radius:var(--r-lg);
  padding:26px;box-shadow:var(--sh-lg);transform:rotate(-1.2deg)}
.panel-top{display:flex;align-items:center;gap:12px;padding-bottom:18px;
  border-bottom:1px solid var(--line);margin-bottom:18px}
.panel-top .mark{display:grid;place-items:center;width:40px;height:40px;flex:0 0 40px;
  border-radius:12px;background:linear-gradient(140deg,var(--brand),var(--accent));
  color:var(--on-brand);font-weight:700;font-size:.9rem;font-family:$heading_font}
.panel-name{font-family:$heading_font;font-weight:700;letter-spacing:-.02em}
.panel-list li{display:flex;align-items:flex-start;gap:10px;padding:9px 0;
  font-size:.95rem;color:var(--muted)}
.panel-list svg{width:18px;height:18px;flex:0 0 18px;margin-top:2px;color:var(--brand)}
.panel-bars{display:flex;gap:8px;margin-top:18px}
.panel-bars i{height:8px;border-radius:999px;background:var(--brand-soft);flex:1}
.panel-bars i:first-child{background:var(--brand);flex:2}
.panel-bars i:nth-child(2){background:var(--brand-edge)}

/* Trust strip */
.strip{border-block:1px solid var(--line);background:var(--bg);padding:26px 0}
.strip-lead{margin:0 0 14px;font-size:.78rem;letter-spacing:.12em;
  text-transform:uppercase;color:var(--muted);text-align:center}
.pills{display:flex;flex-wrap:wrap;gap:10px;justify-content:center}
.pill{border:1px solid var(--line);border-radius:999px;padding:7px 16px;
  font-size:.88rem;font-weight:600;color:var(--muted);background:var(--wash)}

/* Grids and cards */
.grid{display:grid;gap:clamp(16px,2vw,22px)}
/* One item centres rather than sitting in the first of three columns, which is
   what a single stated figure did on the dark band. */
.grid-1{max-width:34rem;margin-inline:auto}
@media(min-width:620px){.grid-2,.grid-3{grid-template-columns:repeat(2,1fr)}}
@media(min-width:960px){.grid-3{grid-template-columns:repeat(3,1fr)}}
.card{background:var(--bg);border:1px solid var(--line);border-radius:var(--r);
  padding:clamp(22px,2.4vw,28px);box-shadow:var(--sh-sm);
  transition:transform .18s,box-shadow .18s,border-color .18s}
.card:hover{transform:translateY(-3px);box-shadow:var(--sh-md);
  border-color:var(--brand-edge)}
.card p{color:var(--muted);margin:0;font-size:.97rem}
.card-icon{display:grid;place-items:center;width:44px;height:44px;border-radius:12px;
  background:var(--brand-soft);color:var(--brand);margin-bottom:16px}
.card-icon svg{width:22px;height:22px}
.card-plain{border:0;box-shadow:none;background:transparent;padding:2px 0 2px 20px;
  border-left:2px solid var(--brand-edge)}
.card-plain:hover{transform:none;box-shadow:none}

/* Why us */
.feature-list{display:grid;gap:clamp(20px,2.4vw,30px)}
@media(min-width:760px){.feature-list{grid-template-columns:repeat(2,1fr)}}
.feature-list li{display:flex;gap:14px;align-items:flex-start}
.feature-list .tick{display:grid;place-items:center;flex:0 0 32px;width:32px;height:32px;
  border-radius:50%;background:var(--brand);color:var(--on-brand);margin-top:2px}
.feature-list .tick svg{width:17px;height:17px}
.feature-list h3{margin:0 0 .25em}
.feature-list p{margin:0;color:var(--muted);font-size:.97rem}

/* Steps */
.steps{display:grid;gap:clamp(22px,3vw,34px)}
@media(min-width:820px){.steps{grid-template-columns:repeat(auto-fit,minmax(210px,1fr))}}
.steps li{position:relative;padding-top:6px}
@media(min-width:820px){
  .steps li:not(:last-child)::after{content:"";position:absolute;left:56px;top:28px;
    right:-16px;height:1px;
    background:linear-gradient(90deg,var(--brand-edge),transparent)}
}
.step-no{display:grid;place-items:center;width:44px;height:44px;border-radius:50%;
  background:var(--brand);color:var(--on-brand);font-family:$heading_font;
  font-weight:700;font-size:1.05rem;margin-bottom:18px;
  box-shadow:0 8px 18px -10px $brand_glow}
.steps h3{margin:0 0 .3em}
.steps p{margin:0;color:var(--muted);font-size:.97rem;max-width:34ch}

/* Numbers, on the dark band */
.sec.dark{background:
    radial-gradient(60% 100% at 85% 0%,$mesh_a 0%,transparent 68%),
    linear-gradient(160deg,var(--dark) 0%,var(--dark-soft) 100%);
  color:#fff}
.sec.dark h2{color:#fff}
.stats .grid{gap:clamp(24px,3vw,40px);text-align:center}
.stat{display:flex;flex-direction:column;gap:6px}
.figure{font-family:$heading_font;font-size:clamp(2.2rem,1.4rem + 2.2vw,3.2rem);
  font-weight:$display_weight;line-height:1;letter-spacing:-.03em;
  background:linear-gradient(176deg,#fff 42%,rgba(255,255,255,.78));
  -webkit-background-clip:text;background-clip:text;color:transparent}
.figure-label{font-size:.92rem;color:$on_dark_muted;font-weight:500}

/* Gallery */
.gallery{display:grid;gap:14px;grid-template-columns:repeat(auto-fit,minmax(250px,1fr))}
.gallery figure{margin:0;overflow:hidden;border-radius:var(--r);box-shadow:var(--sh-sm)}
.gallery img{width:100%;aspect-ratio:4/3;object-fit:cover;transition:transform .35s}
.gallery figure:hover img{transform:scale(1.04)}

/* Quote */
.quote blockquote{margin:0;max-width:54ch;padding-left:clamp(20px,3vw,32px);
  border-left:3px solid var(--brand)}
.quote .quote-mark{display:none}
.quote p{font-family:$heading_font;
  font-size:clamp(1.3rem,1rem + 1.2vw,2rem);line-height:1.36;font-weight:600;
  letter-spacing:-.02em;margin:0}
.quote cite{display:block;margin-top:22px;font-family:$body_font;font-size:.94rem;
  font-style:normal;font-weight:600;color:var(--muted)}

/* Pricing */
.price{background:var(--bg);border:1px solid var(--line);border-radius:var(--r);
  padding:clamp(24px,2.6vw,32px);display:flex;flex-direction:column;
  box-shadow:var(--sh-sm)}
.price h3{font-size:1.3rem}
.price p{color:var(--muted)}
.price .ticks{flex-direction:column;gap:10px;margin-top:6px;flex:1}
.price .btn-quiet{margin-top:auto;align-self:flex-start}
.price.featured{border-color:var(--brand);box-shadow:var(--sh-md);position:relative}
.price.featured::before{content:"Most chosen";position:absolute;top:-11px;left:24px;
  background:var(--brand);color:var(--on-brand);font-size:.7rem;font-weight:700;
  letter-spacing:.08em;text-transform:uppercase;padding:4px 12px;border-radius:999px}

/* FAQ */
.faq{max-width:60rem;border-top:1px solid var(--line)}
.faq details{border-bottom:1px solid var(--line)}
.faq summary{cursor:pointer;list-style:none;display:flex;align-items:center;
  justify-content:space-between;gap:16px;padding:20px 2px;font-weight:600;
  font-family:$heading_font;font-size:1.04rem;letter-spacing:-.01em}
.faq summary::-webkit-details-marker{display:none}
.faq summary:hover{color:var(--brand)}
.chev{flex:0 0 12px;width:12px;height:12px;border-right:2px solid var(--muted);
  border-bottom:2px solid var(--muted);transform:rotate(45deg);
  transition:transform .2s;margin-right:4px}
.faq details[open] .chev{transform:rotate(225deg)}
.answer{padding:0 2px 22px;color:var(--muted);max-width:70ch}
.answer p:last-child{margin:0}

/* Prose */
.split{display:grid;gap:clamp(28px,4vw,52px);align-items:start}
@media(min-width:880px){.split{grid-template-columns:1.15fr .85fr}}
.media img{border-radius:var(--r-lg);box-shadow:var(--sh-md);width:100%;
  aspect-ratio:4/3;object-fit:cover}
.prose{color:var(--muted);max-width:66ch;font-size:1.03rem}
.prose p:last-child{margin-bottom:0}
.prose-wide{max-width:70ch}
.sec-head.centre + .prose-wide{margin:0 auto;text-align:center}

/* CTA band */
.band{background:linear-gradient(135deg,var(--brand) 0%,var(--brand-dark) 58%,
  var(--dark) 100%);color:var(--on-brand);text-align:center;overflow:hidden}
.band::after{content:"";position:absolute;inset:auto -20% -60% -20%;height:120%;
  background:radial-gradient(50% 60% at 50% 0%,rgba(255,255,255,.16),transparent 70%);
  pointer-events:none}
.band h2{color:var(--on-brand);margin:0 0 .4em;position:relative}
.band .lead{color:rgba(255,255,255,.88);margin:0 auto;position:relative}
.band .actions{justify-content:center;position:relative}

/* Contact */
.contact-grid{display:grid;gap:16px;margin-top:8px}
@media(min-width:620px){
  .contact-grid{grid-template-columns:repeat(auto-fit,minmax(238px,1fr))}
}
.contact-card{background:var(--bg);border:1px solid var(--line);border-radius:var(--r);
  padding:22px;display:flex;flex-direction:column;gap:4px;box-shadow:var(--sh-sm);
  text-align:left}
.contact-label{font-size:.72rem;letter-spacing:.12em;text-transform:uppercase;
  color:var(--muted);font-weight:600}
.contact-value{font-weight:600;font-size:1rem;overflow-wrap:anywhere;line-height:1.45}
.contact-value a{text-decoration:none}
.contact-value a:hover{text-decoration:underline}
.sec-head.centre ~ .actions{justify-content:center}

/* Footer */
.foot{background:var(--dark);color:$on_dark_muted;padding:clamp(44px,5vw,64px) 0 28px;
  font-size:.92rem}
.foot-top{display:grid;gap:26px;padding-bottom:28px;
  border-bottom:1px solid $on_dark_line}
@media(min-width:760px){.foot-top{grid-template-columns:1.4fr 1fr;align-items:start}}
.foot-brand{display:flex;align-items:center;gap:11px;color:#fff;
  font-family:$heading_font;font-weight:700;font-size:1.1rem;letter-spacing:-.02em}
.foot-brand .mark{display:grid;place-items:center;width:34px;height:34px;flex:0 0 34px;
  border-radius:10px;background:linear-gradient(140deg,var(--brand),var(--accent));
  color:var(--on-brand);font-size:.8rem}
.foot-brand img{height:34px;width:auto;border-radius:8px}
.foot-tag{margin:12px 0 0;max-width:44ch}
.foot-links{display:flex;flex-wrap:wrap;gap:10px 24px}
@media(min-width:760px){.foot-links{justify-content:flex-end}}
.foot-links a{color:$on_dark_muted;text-decoration:none}
.foot-links a:hover{color:#fff}
.foot-base{display:flex;flex-wrap:wrap;gap:8px 20px;justify-content:space-between;
  padding-top:22px;font-size:.84rem}

/* Motion. Opt-in, on load only: no JavaScript to go wrong. */
@media(prefers-reduced-motion:no-preference){
  .card,.stat,.steps li,.feature-list li,.gallery figure,.contact-card{
    animation:rise .55s cubic-bezier(.22,.68,.35,1) backwards;
    animation-delay:calc(var(--i,0) * 70ms)}
  @keyframes rise{from{opacity:0;transform:translateY(14px)}}
  .hero-text>*{animation:rise .6s cubic-bezier(.22,.68,.35,1) backwards}
  .hero-text>*:nth-child(2){animation-delay:60ms}
  .hero-text>*:nth-child(3){animation-delay:120ms}
  .hero-text>*:nth-child(4){animation-delay:180ms}
  .panel-card{animation:rise .7s cubic-bezier(.22,.68,.35,1) 120ms backwards}
}

@media print{
  .nav,.band,.btn{display:none}
  .sec{padding:18px 0;break-inside:avoid}
  body{font-size:12pt}
}
""")


def _css(palette, font):
    p = _tokens(palette)
    f = FONTS.get(font, FONTS['modern'])
    return _CSS.substitute(
        p,
        body_font=f['body'],
        heading_font=f['heading'],
        eyebrow_font=f.get('eyebrow', f['body']),
        display_weight=f['display_weight'],
        tracking=f['tracking'],
        nav_bg=_rgba(p['bg'], .86),
    )


# ══════════════════════════════════════════════════════════════════════════════
# Page
# ══════════════════════════════════════════════════════════════════════════════

# Anchors offered in the nav, in the order they should appear.
_NAV = [
    ('about', 'About', '#about'),
    ('services', 'Services', '#services'),
    ('gallery', 'Work', '#work'),
    ('pricing', 'Pricing', '#pricing'),
    ('faq', 'FAQ', '#faq'),
]


def _initials(name):
    parts = [w for w in (name or '').split() if w[:1].isalnum()]
    return ''.join(w[0] for w in parts[:2]).upper() or 'MO'


def _json_ld(site, blocks):
    """Structured data, so the page is legible to search engines on day one."""
    contact = next((b.content or {} for b in blocks if b.kind == 'contact'), {})
    data = {
        '@context': 'https://schema.org',
        '@type': 'Organization',
        'name': site.client_name or site.site_name,
        'description': site.tagline or '',
        'url': site.published_url or '',
        'logo': _safe_img(site.logo_url),
        'email': (contact.get('email') or '').strip(),
        'telephone': (contact.get('phone') or '').strip(),
    }
    if (contact.get('address') or '').strip():
        data['address'] = {'@type': 'PostalAddress',
                           'streetAddress': contact['address'].strip()}
    payload = json.dumps({k: v for k, v in data.items() if v}, ensure_ascii=False)
    # json.dumps does not escape angle brackets, and this lands inside a
    # <script> element: a client name containing "</script>" would otherwise
    # close the block and everything after it would be parsed as markup.
    return (payload.replace('<', r'\u003c')
                   .replace('>', r'\u003e')
                   .replace('&', r'\u0026'))


# Where the shared image library is addressed from. The canonical form is
# stored in the blocks; a published folder gets the relative form so the folder
# works both under /sites/<slug>/ and anywhere else it is put.
STOCK_PREFIX = '/sites/_stock/'
STOCK_RELATIVE = '../_stock/'


def render_site(site, blocks, relative_assets=False):
    """Return the complete HTML for a site as one self-contained document.

    `relative_assets` for a page being written to disk under its own folder.
    The preview leaves it off, because the preview is served from /api/ and has
    to address the library absolutely.
    """
    template = TEMPLATES.get(getattr(site, 'template', '') or DEFAULT_TEMPLATE,
                             TEMPLATES[DEFAULT_TEMPLATE])
    f = FONTS.get(site.font, FONTS['modern'])
    visible = [b for b in blocks if b.is_visible and b.kind in RENDERERS]
    kinds = {b.kind for b in visible}

    # Sections alternate tone, skipping the ones whose background is their own
    # design. Done here rather than in each renderer so the rhythm survives any
    # reordering asked for later.
    body, tone_i = [], 0
    for i, b in enumerate(visible):
        ctx = {'hero': template['hero'], 'cards': template['cards'],
               'heads': template['heads'], 'index': i, 'tone': ''}
        if b.kind not in _FIXED_TONE:
            ctx['tone'] = 'wash' if tone_i % 2 else ''
            tone_i += 1
        html = RENDERERS[b.kind](b.content or {}, site, ctx)
        if html:
            body.append(html)

    nav_links = ''.join(f'<a href={_attr(h)}>{_e(l)}</a>'
                        for k, l, h in _NAV if k in kinds)
    foot_links = nav_links
    if 'contact' in kinds:
        nav_links += '<a class="nav-cta" href="#contact">Get in touch</a>'
        foot_links += '<a href="#contact">Contact</a>'

    name = site.client_name or site.site_name
    # Through _safe_img like every other URL: logo_url is validated on the way
    # in by the API, but a site can also be seeded or edited by other paths and
    # the renderer is the last place that can refuse a scheme.
    logo = _safe_img(site.logo_url)
    mark = (f'<img src={_attr(logo)} alt="">' if logo
            else f'<span class="mark">{_e(_initials(name))}</span>')
    # A tagline written for this client often opens with their own name, and
    # prefixing it again produced "East Rand Plumbing — East Rand Plumbing |
    # Same-day quotes..." in the browser tab and the search result.
    if site.tagline and site.tagline.lower().startswith(site.site_name.lower()[:18]):
        title = site.tagline
    elif site.tagline:
        title = f'{site.site_name} — {site.tagline}'
    else:
        title = site.site_name
    desc = site.tagline or f'{name} — official website.'
    brand_hex = PALETTES.get(site.palette, PALETTES['slate'])['brand']

    from django.utils import timezone
    year = timezone.now().year

    canonical = (f'<link rel="canonical" href={_attr(site.published_url)}>'
                 if site.published_url else '')
    og_url = (f'<meta property="og:url" content={_attr(site.published_url)}>'
              if site.published_url else '')
    tagline_p = (f'<p class="foot-tag">{_e(site.tagline)}</p>'
                 if site.tagline else '')

    doc = f"""<!DOCTYPE html>
<html lang="en"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{_e(title)}</title>
<meta name="description" content={_attr(desc)}>
<meta name="theme-color" content={_attr(brand_hex)}>
{canonical}
<meta property="og:type" content="website">
<meta property="og:title" content={_attr(title)}>
<meta property="og:description" content={_attr(desc)}>
<meta property="og:site_name" content={_attr(name)}>
{og_url}
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href={_attr(f['link'])}>
<style>{_css(site.palette, site.font)}</style>
<script type="application/ld+json">{_json_ld(site, visible)}</script>
</head><body>

<header class="nav"><div class="wrap">
  <a class="brand" href="#top">{mark}<span>{_e(site.site_name)}</span></a>
  <nav>{nav_links}</nav>
</div></header>

<main>
{''.join(body)}
</main>

<footer class="foot"><div class="wrap">
  <div class="foot-top">
    <div>
      <span class="foot-brand">{mark}<span>{_e(site.site_name)}</span></span>
      {tagline_p}
    </div>
    <div class="foot-links">{foot_links}</div>
  </div>
  <div class="foot-base">
    <span>&copy; {year} {_e(name)}. All rights reserved.</span>
    <span>Built by Magnum Opus Consultants</span>
  </div>
</div></footer>

</body></html>
"""
    if relative_assets:
        doc = doc.replace(STOCK_PREFIX, STOCK_RELATIVE)
    return doc
