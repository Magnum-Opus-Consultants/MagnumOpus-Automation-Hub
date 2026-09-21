"""Client question sheets: send a client questions, get their answers by email.

Two audiences in one module:

* The session-authenticated endpoints (`api_*`) are what the Sentinel UI calls.
* `public_*` is reached by the client with no login at all, authorised only by
  the unguessable token in their link. Those endpoints therefore never trust a
  session, never expose anything but the one record the token names, and never
  reveal who else was asked.
"""
import base64
import json
import logging
import os
import re

from django.conf import settings
from django.http import FileResponse, JsonResponse
from django.utils import timezone
from django.utils.html import escape
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from . import email_layout as el
from .docx_builder import build_docx
from .models import ClientRequest, ClientRequestAttachment
from .views import _require_module, _graph_send_simple

logger = logging.getLogger(__name__)

_KINDS = [c[0] for c in ClientRequest.KIND_CHOICES]
MAX_QUESTIONS = 40
MAX_ANSWER_CHARS = 8000

# Uploads arrive from unauthenticated strangers, so every limit here is a
# deliberate cap rather than a guess.
MAX_UPLOAD_BYTES = 15 * 1024 * 1024      # per file
MAX_ATTACHMENTS = 12                      # per request, files and links together
# Extensions we are willing to store. Anything script-bearing that a browser
# might execute (.html, .htm, .js, .xhtml) is refused outright - the download
# view forces an attachment disposition, but there is no reason to hold them.
ALLOWED_EXTENSIONS = {
    '.pdf', '.png', '.jpg', '.jpeg', '.gif', '.webp', '.bmp', '.tif', '.tiff',
    '.svg', '.doc', '.docx', '.xls', '.xlsx', '.csv', '.txt', '.rtf',
    '.ppt', '.pptx', '.zip', '.ai', '.psd', '.eps', '.sketch', '.fig',
    '.mp4', '.mov', '.heic',
}


def _body(request):
    try:
        return json.loads(request.body or b'{}')
    except json.JSONDecodeError:
        return None


def _base_url():
    """Public origin for client links."""
    return (getattr(settings, 'PUBLIC_BASE_URL', '') or 'https://workspace.moc-pty.com').rstrip('/')


def _link(req):
    return f'{_base_url()}/r/{req.token}'


def _dict(req, include_link=True):
    out = {
        'id': req.id,
        'title': req.title,
        'kind': req.kind,
        'kind_display': req.kind_label,
        'kind_other': req.kind_other,
        'client_name': req.client_name,
        'client_email': req.client_email,
        'intro': req.intro,
        'questions': req.questions or [],
        'answers': req.answers or {},
        'status': req.status,
        'notify_email': req.notify_email,
        'cc_emails': req.cc_emails or [],
        'recipients': req.all_recipients,
        'question_count': len(req.questions or []),
        'answered_count': req.answered_count,
        'attachments': [_attachment(a) for a in req.attachments.all()],
        'created_at': req.created_at.isoformat() if req.created_at else None,
        'sent_at': req.sent_at.isoformat() if req.sent_at else None,
        'answered_at': req.answered_at.isoformat() if req.answered_at else None,
    }
    if include_link:
        out['link'] = _link(req)
    return out


def _clean_emails(raw):
    """Normalise a list of extra recipients. Returns (emails, error)."""
    if isinstance(raw, str):
        # Accept a pasted "a@b.com, c@d.com" string as well as a real list.
        raw = [p for p in re.split(r'[,;\s]+', raw) if p]
    if not isinstance(raw, list):
        return None, 'cc_emails must be a list of email addresses.'
    out, seen = [], set()
    for addr in raw:
        if not isinstance(addr, str):
            return None, 'every extra recipient must be an email address.'
        addr = addr.strip()
        if not addr:
            continue
        if '@' not in addr or addr.startswith('@') or addr.endswith('@'):
            return None, f'"{addr}" is not a valid email address.'
        if addr.lower() in seen:
            continue
        seen.add(addr.lower())
        out.append(addr[:254])
    if len(out) > 20:
        return None, 'at most 20 extra recipients.'
    return out, None


def _attachment(a, for_client=False):
    """One attachment. Clients never get the internal download path."""
    out = {
        'id': a.id,
        'kind': a.kind,
        'question': a.question,
        'label': a.display_name,
        'uploaded_at': a.uploaded_at.isoformat() if a.uploaded_at else None,
    }
    if a.kind == 'link':
        out['url'] = a.url
    else:
        out['original_name'] = a.original_name
        out['size'] = a.size
        out['content_type'] = a.content_type
        if not for_client:
            out['download'] = f'/api/client-requests/attachments/{a.id}/download'
    return out


def _clean_questions(raw):
    """Normalise the question list. Returns (questions, error)."""
    if not isinstance(raw, list):
        return None, 'questions must be a list of strings.'
    seen, out = set(), []
    for q in raw:
        if not isinstance(q, str):
            return None, 'every question must be a string.'
        q = q.strip()
        if not q:
            continue
        # Answers are keyed by question text, so duplicates would collide and
        # silently overwrite each other.
        if q.lower() in seen:
            return None, f'duplicate question: "{q}".'
        seen.add(q.lower())
        out.append(q[:500])
    if not out:
        return None, 'at least one question is required.'
    if len(out) > MAX_QUESTIONS:
        return None, f'at most {MAX_QUESTIONS} questions.'
    return out, None


# ══════════════════════════════════════════════════════════════════════════════
# Sentinel UI (session-authenticated)
# ══════════════════════════════════════════════════════════════════════════════

def api_client_requests(request):
    err = _require_module(request, 'client_requests')
    if err:
        return err
    qs = ClientRequest.objects.all()
    status = (request.GET.get('status') or '').strip()
    if status:
        qs = qs.filter(status=status)
    rows = [_dict(r) for r in qs]
    return JsonResponse({
        'requests': rows,
        'total': len(rows),
        'sent': sum(1 for r in rows if r['status'] == 'sent'),
        'answered': sum(1 for r in rows if r['status'] == 'answered'),
        'draft': sum(1 for r in rows if r['status'] == 'draft'),
        'kinds': list(ClientRequest.KIND_CHOICES),
    })


@csrf_exempt
@require_http_methods(["POST"])
def api_client_request_create(request):
    err = _require_module(request, 'client_requests')
    if err:
        return err
    data = _body(request)
    if not isinstance(data, dict):
        return JsonResponse({'detail': 'Body must be a JSON object.'}, status=400)

    errors = []
    title = (data.get('title') or '').strip()
    client_name = (data.get('client_name') or '').strip()
    client_email = (data.get('client_email') or '').strip()
    if not title:
        errors.append('title is required.')
    if not client_name:
        errors.append('client_name is required.')
    if '@' not in client_email:
        errors.append('client_email must be a valid email address.')
    kind = (data.get('kind') or 'project').strip()
    if kind not in _KINDS:
        errors.append('kind must be one of: ' + ', '.join(_KINDS) + '.')
    questions, qerr = _clean_questions(data.get('questions') or [])
    if qerr:
        errors.append(qerr)
    if errors:
        return JsonResponse({'detail': ' '.join(errors), 'errors': errors}, status=400)

    notify = (data.get('notify_email') or '').strip()
    if not notify:
        notify = (request.user.email or '').strip() or 'Ethan.Sevenster@moc-pty.com'

    cc, cc_err = _clean_emails(data.get('cc_emails') or [])
    if cc_err:
        return JsonResponse({'detail': cc_err, 'errors': [cc_err]}, status=400)

    kind_other = (data.get('kind_other') or '').strip()[:80]
    if kind == 'other' and not kind_other:
        return JsonResponse(
            {'detail': 'Say what "Other" refers to, so the client sees a meaningful subject.'},
            status=400)

    req = ClientRequest.objects.create(
        title=title[:200], kind=kind,
        client_name=client_name[:200], client_email=client_email[:254],
        intro=(data.get('intro') or '').strip(),
        questions=questions,
        answers={},
        token=ClientRequest.new_token(),
        status='draft',
        notify_email=notify,
        cc_emails=cc,
        kind_other=kind_other,
        created_by=request.user if request.user.is_authenticated else None,
    )

    if data.get('send'):
        ok, msg = _email_client(req)
        if not ok:
            # The record is kept so it can be re-sent rather than retyped.
            return JsonResponse(
                {**_dict(req), 'send_error': msg,
                 'detail': f'Saved, but the email could not be sent: {msg}'},
                status=502)
    return JsonResponse(_dict(req), status=201)


@csrf_exempt
@require_http_methods(["POST", "PATCH"])
def api_client_request_update(request, pk):
    """Edit a request - most usefully to add recipients after it went out."""
    err = _require_module(request, 'client_requests')
    if err:
        return err
    req = ClientRequest.objects.filter(pk=pk).first()
    if req is None:
        return JsonResponse({'detail': 'Request not found.'}, status=404)
    data = _body(request)
    if not isinstance(data, dict):
        return JsonResponse({'detail': 'Body must be a JSON object.'}, status=400)

    fields = []
    if 'notify_email' in data:
        addr = (data.get('notify_email') or '').strip()
        if addr and '@' not in addr:
            return JsonResponse({'detail': 'notify_email must be a valid email address.'}, status=400)
        req.notify_email = addr
        fields.append('notify_email')

    # `add_cc` appends without having to resend the whole list, which is what
    # "these people should get it from now on" actually means.
    if 'add_cc' in data:
        extra, e = _clean_emails(data.get('add_cc') or [])
        if e:
            return JsonResponse({'detail': e}, status=400)
        merged, seen = list(req.cc_emails or []), {a.lower() for a in (req.cc_emails or [])}
        for a in extra:
            if a.lower() not in seen and a.lower() != (req.notify_email or '').lower():
                merged.append(a)
                seen.add(a.lower())
        req.cc_emails = merged
        fields.append('cc_emails')
    elif 'cc_emails' in data:
        cc, e = _clean_emails(data.get('cc_emails') or [])
        if e:
            return JsonResponse({'detail': e}, status=400)
        req.cc_emails = cc
        fields.append('cc_emails')

    for f in ('title', 'intro', 'client_name', 'kind_other'):
        if f in data:
            setattr(req, f, (data.get(f) or '').strip()[:200])
            fields.append(f)
    if 'client_email' in data:
        addr = (data.get('client_email') or '').strip()
        if '@' not in addr:
            return JsonResponse({'detail': 'client_email must be a valid email address.'}, status=400)
        req.client_email = addr
        fields.append('client_email')
    if 'kind' in data:
        if data['kind'] not in _KINDS:
            return JsonResponse({'detail': 'kind must be one of: ' + ', '.join(_KINDS) + '.'}, status=400)
        req.kind = data['kind']
        fields.append('kind')

    # Questions are keys for the stored answers, so changing them after a reply
    # would orphan those answers.
    if 'questions' in data:
        if req.status == 'answered':
            return JsonResponse(
                {'detail': 'This request has been answered; its questions can no longer change.'},
                status=409)
        questions, qerr = _clean_questions(data.get('questions') or [])
        if qerr:
            return JsonResponse({'detail': qerr}, status=400)
        req.questions = questions
        fields.append('questions')

    if not fields:
        return JsonResponse({'detail': 'Nothing to update.'}, status=400)
    req.save(update_fields=fields)
    return JsonResponse(_dict(req))


@csrf_exempt
@require_http_methods(["POST"])
def api_client_request_send(request, pk):
    err = _require_module(request, 'client_requests')
    if err:
        return err
    req = ClientRequest.objects.filter(pk=pk).first()
    if req is None:
        return JsonResponse({'detail': 'Request not found.'}, status=404)
    ok, msg = _email_client(req)
    if not ok:
        return JsonResponse({'detail': f'Could not send: {msg}'}, status=502)
    return JsonResponse(_dict(req))


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def api_client_request_delete(request, pk):
    err = _require_module(request, 'client_requests')
    if err:
        return err
    req = ClientRequest.objects.filter(pk=pk).first()
    if req is None:
        return JsonResponse({'detail': 'Request not found.'}, status=404)
    req.delete()
    return JsonResponse({'ok': True, 'deleted': pk})


# ══════════════════════════════════════════════════════════════════════════════
# Public, token-authorised (the client's view - no login)
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_http_methods(["GET", "POST"])
def public_client_request(request, token):
    req = ClientRequest.objects.filter(token=token).first()
    if req is None:
        return JsonResponse({'detail': 'This link is not valid.'}, status=404)

    if request.method == 'GET':
        # Deliberately narrow: the client sees the questions and who is asking,
        # never notify_email, the internal id, or anyone else's data.
        return JsonResponse({
            'title': req.title,
            'kind_display': req.kind_label,
            'client_name': req.client_name,
            'intro': req.intro,
            'questions': req.questions or [],
            'answers': req.answers or {},
            'attachments': [_attachment(a, for_client=True) for a in req.attachments.all()],
            'max_upload_mb': MAX_UPLOAD_BYTES // (1024 * 1024),
            'max_attachments': MAX_ATTACHMENTS,
            'allowed_extensions': sorted(ALLOWED_EXTENSIONS),
            'already_answered': req.status == 'answered',
            'answered_at': req.answered_at.isoformat() if req.answered_at else None,
            'from_company': 'Magnum Opus Consultants',
        })

    data = _body(request)
    if not isinstance(data, dict):
        return JsonResponse({'detail': 'Body must be a JSON object.'}, status=400)
    submitted = data.get('answers')
    if not isinstance(submitted, dict):
        return JsonResponse({'detail': 'answers must be an object keyed by question.'}, status=400)

    # Only accept keys that are actually questions on this record, so a client
    # cannot inject extra fields into the email we send ourselves.
    answers = {}
    for q in (req.questions or []):
        val = submitted.get(q)
        if isinstance(val, str) and val.strip():
            answers[q] = val.strip()[:MAX_ANSWER_CHARS]
    if not answers:
        return JsonResponse({'detail': 'Please answer at least one question.'}, status=400)

    req.answers = answers
    req.status = 'answered'
    req.answered_at = timezone.now()
    req.save(update_fields=['answers', 'status', 'answered_at'])

    ok, msg = _email_answers(req)
    if not ok:
        # The answers are already stored, so the client is not asked to retype
        # them just because our own notification failed.
        logger.error('[client-request] saved %s but notify failed: %s', req.id, msg)

    # The site is built after the response, not before it. Writing the copy is
    # a model call and the client should not wait on it. Imported here rather
    # than at module scope: the builder reaches the sites API, which reaches
    # views, and this module is imported from there.
    from .site_autobuild import autobuild_async
    started = autobuild_async(req)

    return JsonResponse({
        'ok': True, 'answered': len(answers), 'notified': ok,
        # The client is told a draft is being prepared, never given the URL: it
        # is an internal draft until someone has looked at it.
        'site_started': started,
    })


# ══════════════════════════════════════════════════════════════════════════════
# Email
# ══════════════════════════════════════════════════════════════════════════════

def _email_client(req):
    link = _link(req)
    n = len(req.questions or [])
    intro = req.intro.strip() if req.intro else (
        f'We need a little more detail about your {req.kind_label.lower()} '
        'so we can help properly.')

    blocks = [
        el.heading(req.title, f'{n} question{"" if n == 1 else "s"} for {req.client_name}'),
        el.para(f'Hi {req.client_name},'),
        el.para(intro),
        el.para('The questions are below. The form saves nothing until you send it, '
                'and you can answer as many or as few as you like.', muted=True, size=13),
        el.bullet_list(list(req.questions or [])[:12]),
    ]
    if n > 12:
        blocks.append(el.para(f'…and {n - 12} more on the form.', muted=True, size=13))
    blocks += [
        el.button('Answer the questions', link),
        el.para('Or paste this link into your browser:', muted=True, size=12),
        el.raw(f'<p style="margin:0 0 4px;font-family:{el.FONT};font-size:12px">'
               f'{el.link(link)}</p>'),
    ]

    html = el.render(
        req.title, blocks,
        preheader=f'{n} quick question{"" if n == 1 else "s"} about your '
                  f'{req.kind_label.lower()}.',
        footer_note='This link is unique to you - please do not forward it.',
    )

    text = (f'Hi {req.client_name},\n\n{intro}\n\n{req.title}\n\n'
            + '\n'.join(f'- {q}' for q in (req.questions or []))
            + f'\n\nAnswer here: {link}\n\nMagnum Opus Consultants\n')

    subject = f'{req.title} - a few questions'
    # The shell references the banner by content id, so it has to travel with
    # the message or the header renders as a broken image.
    banner = el.banner_attachment()
    ok, msg = _graph_send_simple(req.client_email, subject, body_html=html,
                                 body_text=text,
                                 attachments=[banner] if banner else [])
    if ok:
        req.status = 'sent' if req.status == 'draft' else req.status
        req.sent_at = timezone.now()
        req.save(update_fields=['status', 'sent_at'])
        logger.info('[client-request] sent %s to %s', req.id, req.client_email)
    return ok, msg


def _email_answers(req):
    """Send the client's answers to whoever asked for them.

    Sent from the request itself, so it goes out whatever happens to the site
    generator afterwards. The site's own link arrives in _email_site_ready.
    """
    when = req.answered_at.strftime('%d %b %Y at %H:%M') if req.answered_at else ''
    total = len(req.questions or [])
    blocks = [
        el.heading(req.title, 'A client has answered your question sheet'),
        el.fact_row([
            ('Client', req.client_name),
            ('Email', req.client_email),
            ('About', req.kind_label),
            ('Answered', f'{req.answered_count} of {total}'),
        ]),
        el.qa_table([(q, (req.answers or {}).get(q, '')) for q in (req.questions or [])]),
    ]

    # Anything they attached, with the internal link to fetch it. The files
    # themselves are not attached to this email: they can be 15 MB each.
    items = list(req.attachments.all())
    if items:
        base = _base_url()
        rows = []
        for a in items:
            if a.kind == 'link':
                rows.append(f'{a.display_name} - {a.url}')
            else:
                mb = a.size / (1024 * 1024)
                size = f'{mb:.1f} MB' if mb >= 0.1 else f'{a.size // 1024} KB'
                rows.append(f'{a.display_name} ({size}) - '
                            f'{base}/api/client-requests/attachments/{a.id}/download')
        blocks.append(el.para(
            f'{len(items)} attachment{"" if len(items) == 1 else "s"} came with this reply:'))
        blocks.append(el.bullet_list(rows))

    blocks.append(
        el.para('A first draft of their website is being generated from these '
                'answers. The link follows in a separate email.',
                muted=True, size=13))

    blocks.append(
        el.para('The answers are also attached as a Word document, ready to paste '
                'into a brief or a quote.', muted=True, size=13))
    if when:
        blocks.append(el.para(f'Submitted {when}.', muted=True, size=12))

    html = el.render(
        f'Client reply: {req.title}', blocks,
        preheader=f'{req.client_name} answered {req.answered_count} of {total} questions.',
    )
    text = (f'{req.title}\n{req.client_name} <{req.client_email}>\n'
            f'{req.answered_count} of {total} answered'
            + (f' - {when}' if when else '') + '\n\n'
            + '\n\n'.join(
                f'{q}\n  {(req.answers or {}).get(q, "") or "Not answered"}'
                for q in (req.questions or [])))

    recipients = req.all_recipients or ['Ethan.Sevenster@moc-pty.com']
    subject = f'Client reply: {req.title} - {req.client_name}'

    # A Word copy of the reply, so the answers can be edited into a brief or a
    # quote without retyping them out of an email.
    banner = el.banner_attachment()
    attachments = [banner] if banner else []
    try:
        answered = f'{req.answered_count} of {len(req.questions or [])} answered'
        when = req.answered_at.strftime('%Y-%m-%d %H:%M') if req.answered_at else ''
        doc = build_docx(
            req.title,
            subtitle=f'{req.client_name} <{req.client_email}> - {req.kind_label}'
                     + (f' - answered {when}' if when else '')
                     + f' - {answered}',
            sections=[(q, (req.answers or {}).get(q, '')) for q in (req.questions or [])],
            footer='Magnum Opus Consultants - collected via the client question sheet',
        )
        safe = re.sub(r'[^A-Za-z0-9 _-]+', '', req.title).strip()[:60] or 'client-reply'
        attachments.append({
            'name': f'{safe}.docx',
            'contentType': 'application/vnd.openxmlformats-officedocument'
                           '.wordprocessingml.document',
            'contentBytes': base64.b64encode(doc).decode('ascii'),
        })
    except Exception:
        # The answers are already saved and the email body carries them, so a
        # failure to build the attachment must not cost the notification.
        logger.exception('[client-request] could not build the Word document for %s', req.id)

    # Every recipient is attempted even if one address fails, so a single bad
    # extra address cannot cost you the reply.
    ok_any, errors = False, []
    for to in recipients:
        ok, msg = _graph_send_simple(to, subject, body_html=html, body_text=text,
                                     attachments=attachments)
        if ok:
            ok_any = True
        else:
            errors.append(f'{to}: {msg}')
            logger.error('[client-request] notify %s failed: %s', to, msg)
    return ok_any, '; '.join(errors) if errors else 'sent'


def _email_site_ready(req, site):
    """Tell whoever asked for the reply that a draft site is live.

    Separate from the answers email because it cannot be produced at the same
    time: the copy is written by a model and that takes long enough that the
    client would be left waiting on the form.
    """
    rows = [f'Layout: {site.get_template_display()}']
    if site.industry:
        rows.append(f'Read as: {site.industry}')
    rows.append(f'Sections: {site.blocks.count()}')
    if site.published_ip:
        rows.append(f'Served from: {site.published_ip}')

    blocks = [
        el.heading(f'{site.site_name} - first draft is live',
                   f'Generated from {req.client_name}\u2019s answers'),
        el.para('This was built and published automatically from their reply. '
                'It is a draft: read it before you send the client the link.'),
        el.bullet_list(rows),
    ]
    if site.published_url:
        blocks.append(el.button('Open the draft site', site.published_url))
        blocks.append(el.raw(
            f'<p style="margin:0 0 14px;font-family:{el.FONT};font-size:12px">'
            f'{el.link(site.published_url)}</p>'))
    if site.notes:
        # The internal notes say which sections are the client's own words,
        # which are standard wording, and anything the copywriter was refused.
        blocks.append(el.para('What went into it:', muted=True, size=13))
        blocks.append(el.bullet_list(
            [line for line in site.notes.split('\n') if line.strip()][:8]))

    html = el.render(f'{site.site_name} - draft site', blocks,
                     preheader=f'A draft site for {req.client_name} is live.',
                     footer_note='Generated by Sentinel from the client\u2019s '
                                 'question sheet. Nothing has been sent to the '
                                 'client.')
    text = (f'{site.site_name} - first draft is live\n'
            f'{site.published_url}\n\n' + '\n'.join(rows)
            + '\n\nThis is a draft generated from the reply. Review it before '
              'sending the client the link.\n')

    banner = el.banner_attachment()
    ok_any, errors = False, []
    for to in (req.all_recipients or ['Ethan.Sevenster@moc-pty.com']):
        ok, msg = _graph_send_simple(to, f'Draft site ready: {site.site_name}',
                                     body_html=html, body_text=text,
                                     attachments=[banner] if banner else [])
        if ok:
            ok_any = True
        else:
            errors.append(f'{to}: {msg}')
            logger.error('[client-request] site-ready mail to %s failed: %s', to, msg)
    return ok_any, '; '.join(errors) if errors else 'sent'


# ══════════════════════════════════════════════════════════════════════════════
# Attachments
# ══════════════════════════════════════════════════════════════════════════════

@csrf_exempt
@require_http_methods(["POST"])
def public_attach(request, token):
    """A client attaches a file or a reference link.

    Unauthenticated by design - the token in the URL is the authorisation, the
    same as the form itself.
    """
    req = ClientRequest.objects.filter(token=token).first()
    if req is None:
        return JsonResponse({'detail': 'This link is not valid.'}, status=404)

    if req.attachments.count() >= MAX_ATTACHMENTS:
        return JsonResponse(
            {'detail': f'You can attach at most {MAX_ATTACHMENTS} items. '
                       'Remove one first, or send the rest by email.'},
            status=400)

    question = (request.POST.get('question') or '').strip()[:500]
    # Only accept a question this request actually asks, so the label cannot be
    # used to smuggle arbitrary text into the email we send ourselves.
    if question and question not in (req.questions or []):
        question = ''
    label = (request.POST.get('label') or '').strip()[:300]

    upload = request.FILES.get('file')
    url = (request.POST.get('url') or '').strip()

    if upload is None and not url:
        return JsonResponse({'detail': 'Send either a file or a link.'}, status=400)

    if url:
        if not url.lower().startswith(('http://', 'https://')):
            return JsonResponse(
                {'detail': 'A link must start with http:// or https://'}, status=400)
        if len(url) > 1000:
            return JsonResponse({'detail': 'That link is too long.'}, status=400)
        a = ClientRequestAttachment.objects.create(
            request=req, kind='link', question=question, label=label, url=url)
        logger.info('[client-request] %s attached a link to %s', req.client_email, req.id)
        return JsonResponse(_attachment(a, for_client=True), status=201)

    if upload.size > MAX_UPLOAD_BYTES:
        return JsonResponse(
            {'detail': f'That file is {upload.size // (1024 * 1024)} MB. '
                       f'The limit is {MAX_UPLOAD_BYTES // (1024 * 1024)} MB - '
                       'please send a link to it instead.'},
            status=400)
    if upload.size == 0:
        return JsonResponse({'detail': 'That file is empty.'}, status=400)

    ext = os.path.splitext(upload.name or '')[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        return JsonResponse(
            {'detail': f'"{ext or "that type"}" is not a file type we accept. '
                       'Documents, images, spreadsheets and archives are fine.'},
            status=400)

    a = ClientRequestAttachment(
        request=req, kind='file', question=question, label=label,
        original_name=(upload.name or 'file')[:300],
        size=upload.size,
        content_type=(upload.content_type or '')[:150],
    )
    a.file = upload
    a.save()
    logger.info('[client-request] %s uploaded %s (%s bytes) to %s',
                req.client_email, a.original_name, a.size, req.id)
    return JsonResponse(_attachment(a, for_client=True), status=201)


@csrf_exempt
@require_http_methods(["POST", "DELETE"])
def public_attach_delete(request, token, pk):
    """The client removes something they attached, before they send."""
    req = ClientRequest.objects.filter(token=token).first()
    if req is None:
        return JsonResponse({'detail': 'This link is not valid.'}, status=404)
    a = req.attachments.filter(pk=pk).first()
    if a is None:
        return JsonResponse({'detail': 'Attachment not found.'}, status=404)
    name = a.display_name
    if a.file:
        a.file.delete(save=False)
    a.delete()
    return JsonResponse({'ok': True, 'removed': name})


@require_http_methods(["GET"])
def attachment_download(request, pk):
    """Hand a client's upload to a signed-in member of staff.

    Always as an attachment with a neutral content type: these files came from
    outside, and this domain also serves the platform itself.
    """
    err = _require_module(request, 'client_requests')
    if err:
        return err
    a = ClientRequestAttachment.objects.filter(pk=pk, kind='file').first()
    if a is None or not a.file:
        return JsonResponse({'detail': 'Attachment not found.'}, status=404)
    try:
        fh = a.file.open('rb')
    except (OSError, ValueError):
        logger.error('[client-request] attachment %s is missing from disk', a.id)
        return JsonResponse({'detail': 'That file is no longer on disk.'}, status=410)

    resp = FileResponse(fh, as_attachment=True,
                        filename=a.original_name or f'attachment-{a.id}')
    resp['Content-Type'] = 'application/octet-stream'
    resp['X-Content-Type-Options'] = 'nosniff'
    return resp
