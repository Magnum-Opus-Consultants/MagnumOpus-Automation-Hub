"""Model-written copy for a generated site, vetted before it is used.

The industry packs in site_content give every site of a kind the same words.
This module asks a model to write the page from the client's own answers
instead, which is what makes two freight forwarders read differently.

The model is never trusted. It is asked for one JSON object and every field is
checked before it is allowed near a page that will carry a client's name:

* Numbers are checked against the answers. A model asked to write copy for a
  logistics firm will happily produce "over 20 years in freight" because that
  is what such pages say. If a figure is not in what the client wrote, the
  field is thrown away and the pack's wording is used.
* Claims of certification, accreditation, awards and market leadership are
  refused on the same basis.
* Anything empty, over-long, or still holding a placeholder is refused.

A rejected field costs nothing: compose() has already built the pack version,
and the model's output is an overlay on top of it. So the worst case for a bad
model reply is the site we would have generated anyway.
"""
import json
import logging
import re

from . import llm

logger = logging.getLogger(__name__)

SYSTEM = """You write copy for small business websites in South Africa.

Rules, in order of importance:
1. Only state facts that appear in the client's answers. If the answers do not
   say how long they have traded, how many staff they have, what they are
   certified in, or who their clients are, you must not mention it.
2. Numbers the client stated are yours to use - quote them. Numbers they did
   not state must not appear. If a sentence needs a figure you do not have,
   rewrite the sentence so it reads correctly without one. Never simply drop
   the number and leave the sentence broken: "reports for anything over days"
   is worse than saying nothing about ageing at all.
3. No claims of being the best, leading, number one, award-winning, certified,
   accredited or ISO-anything unless the answers say so.
4. Write plainly. Short concrete sentences. No marketing filler, no "we are
   passionate about", no "solutions" where a real word will do.
5. Never mention money: no budgets, no prices, no rates, no margins. If the
   answers contain figures like that they were given to us in confidence and
   do not belong on the client's own website.
6. South African English: organise, specialise, colour, licence as a noun.
7. Sentence case for every heading: "Book a table online", never "Book A
   Table Online". Capitalise only the first word and proper nouns.
8. Address the reader as "you" and the business as "we".

Return only the JSON object asked for."""

# Field caps. A hero heading that runs to 200 characters breaks the layout it
# was written for, so length is part of validity rather than a suggestion.
LIMITS = {
    'tagline': 110, 'heading': 78, 'sub': 220, 'body': 900,
    'point': 60, 'item_title': 70, 'item_body': 180, 'cta_label': 26,
    'faq_title': 90, 'faq_body': 400,
}

_DIGITS = re.compile(r'\d[\d\s,.]*')
_BANNED = re.compile(
    r'\b(?:award[- ]?winning|awards?|iso\s?\d*|certified|certification|'
    r'accredit\w*|licen[cs]ed by|number one|no\.?\s?1|#1|market leader|'
    r'industry[- ]leading|the leading|best in|world[- ]class|guarantee\w*|'
    r'fully insured|bbbee|b-bbee|level \d)\b', re.I)
# A number removed mid-sentence rather than rewritten around. The model does
# this when told not to invent figures, and it publishes as "anything over
# days" - a broken sentence no reader would forgive.
_DROPPED_NUMBER = re.compile(
    r'\b(?:over|under|within|about|around|more than|less than|up to|from|'
    r'anything over|at least)\s+(?:days?|weeks?|months?|years?|hours?|'
    r'minutes?|clients?|customers?|staff|people|units?|vehicles?|cars?|'
    r'branches|sites?|containers?)\b', re.I)
# A currency amount on a client's own website is either a price they chose to
# publish - which belongs in a pricing block someone filled in deliberately -
# or their budget leaking out of the brief. Refused either way.
_MONEY = re.compile(
    r'(?:\bR\s?\d|\bZAR\b|\bUSD\b|\bEUR\b|[$\u20ac\u00a3]\s?\d|'
    r'\b\d[\d\s,]*\s*(?:rand|dollars?|euros?|pounds?)\b)', re.I)
_PLACEHOLDER = re.compile(
    r'lorem ipsum|\[[a-z ]+\]|\bTODO\b|insert \w+ here|your company name|xxx',
    re.I)


def _numbers(text):
    """The numbers in a string, normalised so 4 000 and 4,000 compare equal."""
    out = set()
    for m in _DIGITS.finditer(text or ''):
        n = re.sub(r'[\s,]', '', m.group()).rstrip('.')
        if n:
            out.add(n)
            # "12 years" in the answers should also license "12".
            out.add(n.lstrip('0') or '0')
    return out


# Words that carry no capital of their own. A heading where several of these
# are capitalised is Title Case, whatever the model was asked for.
_MINOR = {'a', 'an', 'and', 'as', 'at', 'but', 'by', 'for', 'from', 'in',
          'of', 'on', 'or', 'our', 'the', 'to', 'with', 'your', 'you',
          'into', 'over', 'out', 'up', 'so', 'that', 'this', 'we', 'us'}


def _words(text):
    return [w for w in (t.strip('.,:;!?()"\'\u2019\u2014-') for t in
                        (text or '').split()) if w]


def is_title_case(text, proper=()):
    """Whether a heading has been Title Cased.

    `proper` is the set of words the client capitalised themselves; capitals
    drawn from it are explained and do not count. Two signals then decide it:
    a small word capitalised anywhere but the start, which no sentence does,
    or two unexplained capitals, which is more than a real heading carries.
    """
    words = _words(text)
    if len(words) < 3:
        return False
    rest = words[1:]
    if any(w.lower() in _MINOR and w[:1].isupper() for w in rest):
        return True
    unexplained = [w for w in rest
                   if w[:1].isupper() and w.lower() not in proper]
    return len(unexplained) >= 2


class Vetter:
    """Checks one site's generated copy against what the client actually said."""

    def __init__(self, source_text):
        self.source = source_text or ''
        self.allowed_numbers = _numbers(self.source)
        self.low = self.source.lower()
        # Every word the client capitalised: their town, their trading name,
        # their suppliers. A capital from this set is theirs, not the model
        # title-casing an ordinary noun.
        self.proper = {w.lower() for w in _words(self.source)
                       if w[:1].isupper() and w.lower() not in _MINOR}
        self.rejected = []

    def _reject(self, field, why):
        self.rejected.append(f'{field} ({why})')
        return None

    def heading(self, value, field, limit_key='heading'):
        """A heading, refused if it is Title Cased.

        Refusing rather than lowercasing it: deciding which words in
        "Sunday Lunch In Parkhurst" are proper nouns is not something to
        guess at, and the pack's own heading is already sentence case.
        """
        v = self.text(value, field, limit_key)
        if v and is_title_case(v, self.proper):
            return self._reject(field, 'Title Case')
        return v

    def text(self, value, field, limit_key):
        if not isinstance(value, str):
            return self._reject(field, 'not text')
        v = ' '.join(value.split()).strip()
        if len(v) < 2:
            return self._reject(field, 'empty')
        if len(v) > LIMITS[limit_key]:
            return self._reject(field, f'{len(v)} chars over the {LIMITS[limit_key]} cap')
        if _PLACEHOLDER.search(v):
            return self._reject(field, 'placeholder text')
        money = _MONEY.search(v)
        if money:
            return self._reject(field, f'money on the page ("{money.group()}")')
        gap = _DROPPED_NUMBER.search(v)
        if gap:
            return self._reject(field, f'number dropped from "{gap.group()}"')
        # A claim the client did not make. Checked against their own words, so
        # "we are ISO 9001 certified" passes only if they said it.
        bad = _BANNED.search(v)
        if bad and bad.group().lower() not in self.low:
            return self._reject(field, f'unsupported claim "{bad.group()}"')
        invented = _numbers(v) - self.allowed_numbers
        # Ordinals and small counts inside prose are not claims: "three steps",
        # "1." Only reject digits that read as figures about the business.
        invented = {n for n in invented if len(n) > 1 or int(n) > 5}
        if invented:
            return self._reject(field, f'invented number {sorted(invented)[:3]}')
        return v

    def items(self, value, field, n_max, title_key='item_title',
              body_key='item_body', body_required=False):
        if not isinstance(value, list):
            return self._reject(field, 'not a list')
        out = []
        for i, it in enumerate(value[:n_max]):
            if not isinstance(it, dict):
                continue
            title = self.text(it.get('title'), f'{field}[{i}].title', title_key)
            if not title:
                continue
            body = self.text(it.get('body'), f'{field}[{i}].body', body_key)
            if body_required and not body:
                continue
            out.append({'title': title, 'body': body or ''})
        if len(out) < 2:
            return self._reject(field, f'only {len(out)} usable items')
        return out

    def points(self, value, field, n_max=3):
        if not isinstance(value, list):
            return self._reject(field, 'not a list')
        out = [p for p in (self.text(v, f'{field}[{i}]', 'point')
                           for i, v in enumerate(value[:n_max])) if p]
        return out or self._reject(field, 'no usable points')


# What the client told us in confidence. These answers are for quoting the
# work, not for their website, and a copywriter given them will use them - the
# first run put "we have allocated R180 000 to R250 000" into a published page.
WITHHELD = ('budget', 'spend', 'price range', 'how much', 'cost to us',
            'margin', 'markup', 'what we pay', 'purchase price', 'our rates',
            'discount', 'commission', 'salary', 'wage', 'turnover', 'profit')


def _visible_pairs(found):
    """The answers the copywriter is allowed to see."""
    out = []
    for q, a in found.get('_pairs', []):
        low = f'{q} {a}'.lower()
        if any(w in low for w in WITHHELD):
            continue
        out.append((q, a))
    return out


def _prompt(business, pack, found):
    """Everything the model is allowed to know, and what to produce."""
    from . import site_builder as sb

    qa = '\n'.join(f'Q: {q}\nA: {a}' for q, a in _visible_pairs(found))
    services_hint = ', '.join(t for t, _ in pack['services'][:6])
    layouts = ', '.join(f'{k} ({v["blurb"]})' for k, v in sb.TEMPLATES.items())
    palettes = ', '.join(sb.PALETTES)
    return f"""Business name: {business}
Trade: {pack['label']}

The client answered a question sheet. These are their exact words:

{qa}

Write the copy for their one-page website. Return this JSON object exactly,
with no extra keys:

{{
  "layout": "one of: {layouts}",
  "palette": "one of: {palettes}",
  "tagline": "one line under 110 chars for the browser tab and search results",
  "hero": {{
    "eyebrow": "2-4 words naming the trade",
    "heading": "the headline, under 78 chars, a promise not a description",
    "sub": "one or two sentences saying who it is for and what they get",
    "points": ["three short proof points, under 60 chars each"]
  }},
  "about": {{
    "heading": "a heading, may use the business name",
    "body": "two short paragraphs separated by a blank line, about who they are and who they serve"
  }},
  "services": {{
    "heading": "a heading",
    "sub": "one line, or an empty string",
    "items": [{{"title": "service name", "body": "one concrete sentence about it"}}]
  }},
  "features": {{
    "heading": "a heading about why a customer would choose them",
    "items": [{{"title": "the reason, a short phrase", "body": "one sentence"}}]
  }},
  "steps": {{
    "heading": "a heading about how working with them runs",
    "items": [{{"title": "the step", "body": "one sentence"}}]
  }},
  "faq": {{
    "items": [{{"title": "a question a real customer would ask", "body": "the answer"}}]
  }},
  "cta": {{
    "heading": "under 78 chars, asking for the next step",
    "sub": "one line",
    "cta_label": "2-4 words on a button"
  }},
  "contact": {{
    "heading": "a heading",
    "body": "one line inviting them to make contact"
  }}
}}

Give 4 to 6 services, 4 features, 4 steps and 4 to 5 FAQ items. If the client
listed their services, use their names for them.

Headings must say something. "Our Services", "About Us", "Why Choose Us" and
"Contact Us" are wasted lines - name the trade or the business or the benefit
instead. For reference, businesses in
this trade typically offer: {services_hint}. Do not claim anything about this
business that is not in their answers above.

Pick the layout that suits what they described and a palette that suits the
trade - restrained for professional services, warmer for retail and food."""




REFINE_SYSTEM = """You are editing website copy that has already been drafted.

Your job is to make it specific and to cut everything that could appear on any
other company's website. Apply the same rules as the draft: no facts, figures,
certifications or money that are not in the client's answers.

What to change:
* Any sentence that would read the same for a competitor - rewrite it around
  something this client actually said, or cut it.
* Headings like "Our Services" or "Why Choose Us" - name the trade, the place
  or the benefit instead.
* Filler: "solutions", "cutting-edge", "passionate", "seamless", "leverage",
  "state-of-the-art", "one-stop", "we pride ourselves".
* Long sentences. Two short ones read better than one clause-heavy one.
* Title Case headings. Every heading is sentence case: capitalise the first
  word and proper nouns, nothing else.

Keep the JSON shape exactly as given, including every key. Return only JSON."""


def _refine_prompt(business, found, draft):
    qa = '\n'.join(f'Q: {q}\nA: {a}' for q, a in _visible_pairs(found))
    body = json.dumps({k: v for k, v in draft.items() if not k.startswith('_')},
                      indent=1, ensure_ascii=False)
    return f"""Business: {business}

What the client said, in their words:

{qa}

The current draft of their website copy:

{body}

Return the same JSON object, edited. Every line should be something only this
business could say."""



def _vet(raw, source):
    """Vet one candidate. Returns (copy, rejected, how much survived)."""
    from . import site_builder as sb

    v = Vetter(source)

    def sec(name):
        d = raw.get(name)
        return d if isinstance(d, dict) else {}

    hero, about, serv = sec('hero'), sec('about'), sec('services')
    feat, steps, faq = sec('features'), sec('steps'), sec('faq')
    cta, contact = sec('cta'), sec('contact')

    out = {
        'tagline': v.text(raw.get('tagline'), 'tagline', 'tagline'),
        'hero': {
            'eyebrow': v.text(hero.get('eyebrow'), 'hero.eyebrow', 'point'),
            'heading': v.heading(hero.get('heading'), 'hero.heading'),
            'sub': v.text(hero.get('sub'), 'hero.sub', 'sub'),
            'points': v.points(hero.get('points'), 'hero.points'),
        },
        'about': {
            'heading': v.heading(about.get('heading'), 'about.heading'),
            'body': v.text(about.get('body'), 'about.body', 'body'),
        },
        'services': {
            'heading': v.heading(serv.get('heading'), 'services.heading'),
            'sub': v.text(serv.get('sub'), 'services.sub', 'sub'),
            'items': v.items(serv.get('items'), 'services.items', 6),
        },
        'features': {
            'heading': v.heading(feat.get('heading'), 'features.heading'),
            'items': v.items(feat.get('items'), 'features.items', 4),
        },
        'steps': {
            'heading': v.heading(steps.get('heading'), 'steps.heading'),
            'items': v.items(steps.get('items'), 'steps.items', 4),
        },
        'faq': {
            'items': v.items(faq.get('items'), 'faq.items', 6,
                             title_key='faq_title', body_key='faq_body',
                             body_required=True),
        },
        'cta': {
            'heading': v.heading(cta.get('heading'), 'cta.heading'),
            'sub': v.text(cta.get('sub'), 'cta.sub', 'sub'),
            'cta_label': v.text(cta.get('cta_label'), 'cta.cta_label', 'cta_label'),
        },
        'contact': {
            'heading': v.heading(contact.get('heading'), 'contact.heading'),
            'body': v.text(contact.get('body'), 'contact.body', 'sub'),
        },
    }

    # The presentation choices, only if they name something that exists. An
    # invented template name leaves the keyword choice in place.
    layout = str(raw.get('layout') or '').strip().lower()
    palette = str(raw.get('palette') or '').strip().lower()
    if layout in sb.TEMPLATES:
        out['layout'] = layout
    if palette in sb.PALETTES:
        out['palette'] = palette

    # Drop everything that failed, so an overlay never blanks a pack field.
    out = {k: ({kk: vv for kk, vv in val.items() if vv} if isinstance(val, dict)
               else val)
           for k, val in out.items()}
    out = {k: val for k, val in out.items() if val}

    kept = sum(len(val) if isinstance(val, dict) else 1 for val in out.values())
    return out, v.rejected, kept


def write(business, pack, found, notes=None):
    """Model-written copy for one site, or None.

    Two calls: one to draft the page from the answers, one to edit its own
    draft into something only this business could have said. Both are vetted
    and the better-surviving one is used, so the second call can only help.

    Returns a dict keyed by section holding the fields that passed vetting.
    compose() overlays whatever comes back onto the pack version, so a partial
    result is useful and a missing one is harmless.
    """
    if not llm.available():
        return None

    draft = llm.generate_json(_prompt(business, pack, found), system=SYSTEM,
                              temperature=0.6)
    if not isinstance(draft, dict):
        return None

    # Vetted against the client's own words plus the business name, so their
    # own numbers and their own claims survive.
    source = business + ' ' + ' '.join(
        f'{q} {a}' for q, a in found.get('_pairs', []))

    best, rejected, kept = _vet(draft, source)
    used_model = draft.get('_model', '')
    passes = 1

    refined = llm.generate_json(_refine_prompt(business, found, draft),
                                system=REFINE_SYSTEM, temperature=0.35)
    if isinstance(refined, dict):
        r_out, r_rejected, r_kept = _vet(refined, source)
        # Only if the edit did not cost us fields. An editing pass that trims
        # the page down is not an improvement to the page.
        if r_kept >= kept:
            best, rejected, kept = r_out, r_rejected, r_kept
            used_model = refined.get('_model', used_model)
            passes = 2
        else:
            logger.info('[site-copy] refinement discarded: %s fields vs %s',
                        r_kept, kept)

    best['_model'] = used_model
    best['_rejected'] = rejected
    logger.info('[site-copy] %s: %s fields kept over %s pass(es), %s rejected, by %s',
                business, kept, passes, len(rejected), used_model)
    if rejected:
        logger.info('[site-copy] rejected: %s', '; '.join(rejected[:8]))
    if notes is not None:
        notes.append(
            f'Copy written by {used_model}'
            + (' and edited by a second pass' if passes == 2 else '')
            + (f', {len(rejected)} field(s) fell back to the standard wording'
               if rejected else ''))
    return best
