"""Build a Word (.docx) file with no third-party dependency.

A .docx is a ZIP holding a few XML parts. python-docx is not installed on the
server and adding it to a memory-tight box for one attachment is not worth it,
so the minimum valid document is assembled here directly. The output opens in
Word, LibreOffice, Google Docs and Word Online.

Everything user-supplied goes through `_esc`: a stray "&" or "<" in a client's
answer would otherwise produce a file Word refuses to open.
"""
import io
import zipfile
from xml.sax.saxutils import escape

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml"
            ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
  <Override PartName="/word/styles.xml"
            ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
  <Override PartName="/docProps/core.xml"
            ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>
</Types>"""

_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument"
    Target="word/document.xml"/>
  <Relationship Id="rId2"
    Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties"
    Target="docProps/core.xml"/>
</Relationships>"""

_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1"
    Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles"
    Target="styles.xml"/>
</Relationships>"""

# Only the styles actually referenced below, so Word does not fall back to
# unstyled text.
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
  <w:docDefaults>
    <w:rPrDefault><w:rPr>
      <w:rFonts w:ascii="Calibri" w:hAnsi="Calibri"/>
      <w:sz w:val="22"/>
    </w:rPr></w:rPrDefault>
  </w:docDefaults>
  <w:style w:type="paragraph" w:styleId="Title">
    <w:name w:val="Title"/>
    <w:pPr><w:spacing w:after="120"/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="44"/><w:color w:val="1F2328"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Subtitle">
    <w:name w:val="Subtitle"/>
    <w:pPr><w:spacing w:after="240"/></w:pPr>
    <w:rPr><w:sz w:val="20"/><w:color w:val="6B7280"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="Heading2">
    <w:name w:val="heading 2"/>
    <w:pPr><w:spacing w:before="280" w:after="80"/><w:keepNext/></w:pPr>
    <w:rPr><w:b/><w:sz w:val="24"/><w:color w:val="2563EB"/></w:rPr>
  </w:style>
  <w:style w:type="paragraph" w:styleId="BodyText">
    <w:name w:val="Body Text"/>
    <w:pPr><w:spacing w:after="120"/></w:pPr>
  </w:style>
</w:styles>"""


def _esc(text):
    return escape("" if text is None else str(text))


def _para(text, style=None, italic=False):
    """One paragraph. Newlines inside `text` become real line breaks."""
    pr = f'<w:pPr><w:pStyle w:val="{style}"/></w:pPr>' if style else ""
    rpr = "<w:rPr><w:i/><w:color w:val=\"6B7280\"/></w:rPr>" if italic else ""
    parts = str("" if text is None else text).split("\n")
    runs = []
    for i, chunk in enumerate(parts):
        br = "<w:br/>" if i else ""
        runs.append(f'<w:r>{rpr}{br}<w:t xml:space="preserve">{_esc(chunk)}</w:t></w:r>')
    return f"<w:p>{pr}{''.join(runs)}</w:p>"


def build_docx(title, subtitle=None, sections=None, footer=None):
    """Return .docx bytes.

    `sections` is a list of (heading, body) pairs. A body of None or "" renders
    as a greyed "Not answered", so a gap in the reply is visible rather than
    looking like a formatting slip.
    """
    body = [_para(title, "Title")]
    if subtitle:
        body.append(_para(subtitle, "Subtitle"))
    for heading, text in (sections or []):
        body.append(_para(heading, "Heading2"))
        if text is None or not str(text).strip():
            body.append(_para("Not answered", "BodyText", italic=True))
        else:
            body.append(_para(text, "BodyText"))
    if footer:
        body.append(_para(footer, "Subtitle"))

    document = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
        f'<w:body>{"".join(body)}'
        '<w:sectPr><w:pgSz w:w="11906" w:h="16838"/>'
        '<w:pgMar w:top="1134" w:right="1134" w:bottom="1134" w:left="1134"/>'
        '</w:sectPr></w:body></w:document>'
    )

    core = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<cp:coreProperties '
        'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
        'xmlns:dc="http://purl.org/dc/elements/1.1/">'
        f'<dc:title>{_esc(title)}</dc:title>'
        '<dc:creator>Magnum Opus Consultants</dc:creator>'
        '</cp:coreProperties>'
    )

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        # [Content_Types].xml must be the first entry for some readers.
        z.writestr("[Content_Types].xml", _CONTENT_TYPES)
        z.writestr("_rels/.rels", _RELS)
        z.writestr("word/_rels/document.xml.rels", _DOC_RELS)
        z.writestr("word/document.xml", document)
        z.writestr("word/styles.xml", _STYLES)
        z.writestr("docProps/core.xml", core)
    return buf.getvalue()
