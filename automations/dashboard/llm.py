"""One JSON call, several models, and a fallback that needs no network.

Written for a free API tier, which means the failure modes are the design:

* 429 - the daily or per-minute quota is spent. Cool the model off and move
  down the chain. Different models have separate quotas, so this genuinely
  buys more capacity rather than just retrying the same wall.
* 503 - "high demand". Transient, so a short cooldown and the next model.
* 404 - the model was retired. Google removes models from the free tier
  without notice (gemini-2.5-flash-lite went "no longer available to new
  users" mid-build), so a 404 parks that name for a day rather than retrying
  it on every request for the rest of the month.

The cooldowns are what stop a spent quota costing a round trip on every single
request for the rest of the day. They live in the process, so a restart
re-probes - which is right, because a daily quota does reset.

Nothing here is allowed to be load-bearing. `generate_json` returns None when
every model is unavailable, and every caller must already work without it.
"""
import json
import logging
import threading
import time

import requests
from django.conf import settings

logger = logging.getLogger(__name__)

ENDPOINT = ('https://generativelanguage.googleapis.com/v1beta/models/'
            '{model}:generateContent')

# Best first. A model that is cooling off is skipped, so listing the strongest
# first costs nothing once its quota is known to be spent.
#
# Pro leads deliberately. On a free-tier project Pro answers 429 on the first
# request and the chain falls straight through to flash, so nothing is lost by
# asking - and on a project with billing enabled this is the difference between
# copy that reads as written and copy that reads as generated.
DEFAULT_MODELS = [
    'gemini-3.1-pro-preview',
    'gemini-pro-latest',
    'gemini-3.8-flash',
    'gemini-3.7-flash',
    'gemini-3.5-flash',
    'gemini-flash-latest',
    'gemini-2.5-flash',
    'gemini-flash-lite-latest',
]

# How long a model sits out, by what went wrong.
COOLDOWN = {
    'quota': 20 * 60,        # a per-minute cap clears fast, a daily one does not
    'overloaded': 3 * 60,
    'retired': 24 * 60 * 60,
    'error': 5 * 60,
}

_lock = threading.Lock()
_cooldowns = {}              # model -> unix time it becomes usable again
_last_used = {'model': '', 'at': 0.0}


def models():
    configured = getattr(settings, 'GEMINI_MODELS', '') or ''
    names = [m.strip() for m in configured.split(',') if m.strip()]
    return names or DEFAULT_MODELS


def _key():
    return getattr(settings, 'GEMINI_API_KEY', '') or ''


def available():
    """Whether a copy-writing call is worth attempting at all."""
    if not _key():
        return False
    now = time.time()
    with _lock:
        return any(_cooldowns.get(m, 0) <= now for m in models())


def _park(model, reason):
    until = time.time() + COOLDOWN.get(reason, COOLDOWN['error'])
    with _lock:
        _cooldowns[model] = until
    logger.warning('[llm] %s parked for %s (%s)', model, reason,
                   time.strftime('%H:%M', time.localtime(until)))


def status():
    """What the chain looks like right now, for the health page."""
    now = time.time()
    with _lock:
        rows = [{'model': m,
                 'ready': _cooldowns.get(m, 0) <= now,
                 'ready_in': max(0, int(_cooldowns.get(m, 0) - now))}
                for m in models()]
        return {'configured': bool(_key()), 'models': rows,
                'last_used': dict(_last_used)}


def _classify(resp):
    """Which cooldown a response earns."""
    if resp.status_code == 429:
        return 'quota'
    if resp.status_code == 404:
        return 'retired'
    if resp.status_code in (500, 502, 503, 504):
        return 'overloaded'
    return 'error'


def generate_json(prompt, *, temperature=0.65, max_tokens=16384, timeout=180,
                  system=None):
    """Ask for JSON and return it parsed, or None if no model could answer.

    JSON is requested through responseMimeType rather than by asking nicely in
    the prompt, so the reply does not arrive wrapped in a code fence.
    """
    key = _key()
    if not key:
        return None

    body = {
        'contents': [{'role': 'user', 'parts': [{'text': prompt}]}],
        'generationConfig': {
            'temperature': temperature,
            'maxOutputTokens': max_tokens,
            'responseMimeType': 'application/json',
        },
    }
    if system:
        body['systemInstruction'] = {'parts': [{'text': system}]}

    now = time.time()
    for model in models():
        with _lock:
            if _cooldowns.get(model, 0) > now:
                continue
        try:
            resp = requests.post(
                ENDPOINT.format(model=model),
                headers={'x-goog-api-key': key, 'Content-Type': 'application/json'},
                json=body, timeout=timeout)
        except requests.RequestException as e:
            logger.warning('[llm] %s unreachable: %s', model, e)
            _park(model, 'error')
            continue

        if resp.status_code != 200:
            reason = _classify(resp)
            detail = ''
            try:
                detail = (resp.json().get('error', {}).get('message') or '')[:120]
            except ValueError:
                detail = resp.text[:120]
            logger.warning('[llm] %s -> %s %s: %s', model, resp.status_code,
                           reason, detail)
            _park(model, reason)
            continue

        try:
            data = resp.json()
            cand = (data.get('candidates') or [{}])[0]
            text = ''.join(p.get('text', '')
                           for p in (cand.get('content') or {}).get('parts', []))
            parsed = json.loads(text)
        except (ValueError, KeyError, IndexError) as e:
            # A model that answers with something unparseable is not a quota
            # problem, but it is not usable for this either.
            logger.warning('[llm] %s gave unusable output: %s', model, e)
            _park(model, 'error')
            continue

        usage = data.get('usageMetadata') or {}
        with _lock:
            _last_used.update({'model': model, 'at': time.time()})
        logger.info('[llm] %s answered (%s + %s tokens)', model,
                    usage.get('promptTokenCount'), usage.get('candidatesTokenCount'))
        return {'_model': model, '_tokens': (usage.get('promptTokenCount', 0),
                                             usage.get('candidatesTokenCount', 0)),
                **parsed} if isinstance(parsed, dict) else parsed

    logger.info('[llm] every model in the chain is unavailable')
    return None
