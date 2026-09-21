"""One HTML shell for every email the platform sends.

Written for email clients, not browsers. That means:

* Tables for layout - Outlook's renderer is Word, which ignores flexbox and grid.
* Inline styles only - most clients strip <style> blocks.
* No SVG - Outlook will not render it, so the wordmark is text on a coloured band.
* A "bulletproof" table button rather than a styled <a>, which Outlook squashes.

Every caller passes plain text and gets escaping done here, so a client's answer
containing "&" or "<" cannot break the markup.
"""
import base64
import os
from functools import lru_cache
from xml.sax.saxutils import escape

BRAND = '#2563eb'
BRAND_DARK = '#1d4ed8'
INK = '#1f2328'
MUTED = '#6b7280'
LINE = '#e5e7eb'
WASH = '#f9fafb'

FONT = ("-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,"
        "'Helvetica Neue',Arial,sans-serif")


BANNER_CID = 'moc-banner'
_BANNER_PATH = os.path.join(os.path.dirname(__file__), 'assets', 'moc-email-banner.jpg')


def esc(text):
    return escape('' if text is None else str(text))


@lru_cache(maxsize=1)
def _banner_bytes():
    """The banner, read once per process. None when the file is missing."""
    try:
        with open(_BANNER_PATH, 'rb') as fh:
            return fh.read()
    except OSError:
        return None


def banner_attachment():
    """The banner as an inline Graph attachment, or None.

    Embedded with a content id rather than linked to a URL: most mail clients
    block remote images by default, which would leave a blank band at the top
    of every email.
    """
    data = _banner_bytes()
    if not data:
        return None
    return {
        'name': 'moc-banner.jpg',
        'contentType': 'image/jpeg',
        'contentBytes': base64.b64encode(data).decode('ascii'),
        'isInline': True,
        'contentId': BANNER_CID,
    }


def button(label, href):
    """A table button - the only kind Outlook renders at the right size."""
    href = esc(href)
    return f"""
<table role="presentation" cellpadding="0" cellspacing="0" border="0"
       style="margin:24px 0">
  <tr>
    <td align="center" bgcolor="{BRAND}"
        style="border-radius:6px">
      <a href="{href}"
         style="display:inline-block;padding:12px 26px;font-family:{FONT};
                font-size:15px;font-weight:600;color:#ffffff;text-decoration:none;
                border-radius:6px">{esc(label)}</a>
    </td>
  </tr>
</table>"""


def para(text, muted=False, size=15):
    color = MUTED if muted else INK
    return (f'<p style="margin:0 0 14px;font-family:{FONT};font-size:{size}px;'
            f'line-height:1.55;color:{color}">{esc(text)}</p>')


def raw(html):
    """Escape hatch for markup already built by a caller."""
    return html


def link(url, label=None):
    """An escaped anchor, for showing a URL in the body."""
    safe = esc(url)
    return (f'<a href="{safe}" style="color:{BRAND};word-break:break-all">'
            f'{esc(label or url)}</a>')


def bullet_list(items):
    if not items:
        return ''
    rows = ''.join(
        f'<li style="margin:0 0 6px;font-family:{FONT};font-size:14px;'
        f'line-height:1.5;color:{INK}">{esc(i)}</li>'
        for i in items
    )
    return f'<ul style="margin:0 0 16px;padding-left:22px">{rows}</ul>'


def qa_table(pairs):
    """Question/answer rows. A blank answer is marked, not left looking broken."""
    rows = []
    for q, a in pairs:
        answer = (a or '').strip()
        body = (esc(answer).replace('\n', '<br>') if answer
                else f'<span style="color:{MUTED};font-style:italic">Not answered</span>')
        rows.append(f"""
<tr>
  <td style="padding:10px 12px;border:1px solid {LINE};background:{WASH};
             font-family:{FONT};font-size:13px;font-weight:600;color:{INK};
             width:40%;vertical-align:top">{esc(q)}</td>
  <td style="padding:10px 12px;border:1px solid {LINE};font-family:{FONT};
             font-size:13px;line-height:1.5;color:{INK};vertical-align:top">{body}</td>
</tr>""")
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'width="100%" style="border-collapse:collapse;margin:0 0 16px">'
            f'{"".join(rows)}</table>')


def fact_row(pairs):
    """A compact label/value strip for context under the heading."""
    cells = ''.join(
        f'<td style="padding:0 18px 0 0;font-family:{FONT};font-size:12px;'
        f'color:{MUTED};white-space:nowrap">'
        f'<span style="display:block;text-transform:uppercase;letter-spacing:.4px;'
        f'font-size:10px;color:{MUTED}">{esc(k)}</span>'
        f'<strong style="color:{INK};font-size:13px">{esc(v)}</strong></td>'
        for k, v in pairs if v
    )
    if not cells:
        return ''
    return (f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" '
            f'style="margin:0 0 20px"><tr>{cells}</tr></table>')


def render(subject_title, blocks, preheader='', footer_note='', banner=True):
    """Wrap `blocks` (a list of HTML strings) in the branded shell.

    `preheader` is the grey snippet a mail client shows next to the subject; it
    is hidden in the body itself.
    """
    body = ''.join(blocks)
    hidden = (f'<div style="display:none;max-height:0;overflow:hidden;opacity:0">'
              f'{esc(preheader)}</div>' if preheader else '')
    note = (f'<p style="margin:16px 0 0;font-family:{FONT};font-size:12px;'
            f'line-height:1.5;color:{MUTED}">{esc(footer_note)}</p>'
            if footer_note else '')

    # The asset is a 1200x240 band, so it lands 120px tall at the 600px email
    # width - a header, not a poster. width/height as attributes as well as
    # CSS, because Outlook ignores the CSS and will otherwise size it wrong.
    banner_row = ''
    if banner and _banner_bytes():
        banner_row = (
            f'<tr><td style="padding:0;line-height:0">'
            f'<img src="cid:{BANNER_CID}" width="600" height="120" alt=""'
            f' style="display:block;width:100%;max-width:600px;height:auto;border:0"></td></tr>'
        )

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{esc(subject_title)}</title></head>
<body style="margin:0;padding:0;background:#f3f4f6">
{hidden}
<table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%"
       style="background:#f3f4f6;padding:20px 12px">
  <tr><td align="center">
    <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="600"
           style="max-width:600px;width:100%;background:#ffffff;border-radius:10px;
                  overflow:hidden;box-shadow:0 1px 3px rgba(0,0,0,.08)">

      {banner_row}

      <!-- Brand band. Text, not an image: SVG will not render in Outlook and a
           remote PNG is blocked by default in most clients. -->
      <tr><td style="background:{BRAND};padding:11px 28px">
        <table role="presentation" cellpadding="0" cellspacing="0" border="0" width="100%">
          <tr>
            <td style="font-family:{FONT};font-size:15px;font-weight:700;color:#ffffff;
                       letter-spacing:.4px">SENTINEL</td>
            <td align="right" style="font-family:{FONT};font-size:12px;
                       color:rgba(255,255,255,.85)">Magnum Opus Consultants</td>
          </tr>
        </table>
      </td></tr>

      <tr><td style="padding:24px 28px 28px">
        {body}
      </td></tr>

      <tr><td style="border-top:1px solid {LINE};background:{WASH};padding:16px 28px">
        <p style="margin:0;font-family:{FONT};font-size:11px;line-height:1.5;color:{MUTED}">
          Sent by Sentinel, the operations platform of Magnum Opus Consultants.
        </p>
        {note}
      </td></tr>

    </table>
  </td></tr>
</table>
</body></html>"""


def heading(text, sub=''):
    out = (f'<h1 style="margin:0 0 6px;font-family:{FONT};font-size:21px;'
           f'line-height:1.3;font-weight:700;color:{INK}">{esc(text)}</h1>')
    if sub:
        out += (f'<p style="margin:0 0 18px;font-family:{FONT};font-size:13px;'
                f'color:{MUTED}">{esc(sub)}</p>')
    return out
