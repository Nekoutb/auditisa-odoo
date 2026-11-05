"""A generated document is a list of blocks: {"t": kind, "s": text}. This writes them as a
WordprocessingML package with the standard library only, so that Word opens and edits the
file and the server needs no extra Python package. The same blocks feed the QWeb PDF."""
import io
import re
import zipfile
from xml.sax.saxutils import escape

KINDS = ("title", "h", "p", "b", "i", "small")

_CONTENT_TYPES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""
_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
_DOC_RELS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""
_W = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"'
_STYLES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles %s>
<w:docDefaults><w:rPrDefault><w:rPr><w:rFonts w:ascii="Calibri" w:hAnsi="Calibri" w:cs="Calibri"/><w:sz w:val="22"/><w:lang w:val="fr-FR"/></w:rPr></w:rPrDefault></w:docDefaults>
<w:style w:type="paragraph" w:default="1" w:styleId="Normal"><w:name w:val="Normal"/><w:pPr><w:spacing w:after="120"/></w:pPr></w:style>
<w:style w:type="paragraph" w:styleId="Title"><w:name w:val="Title"/><w:basedOn w:val="Normal"/><w:pPr><w:spacing w:before="240" w:after="240"/></w:pPr><w:rPr><w:b/><w:sz w:val="32"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:pPr><w:keepNext/><w:spacing w:before="240" w:after="80"/></w:pPr><w:rPr><w:b/><w:sz w:val="26"/></w:rPr></w:style>
</w:styles>""" % _W
DOCX_MIME = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_ILLEGAL_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")


def block(kind, text):
    return {"t": kind, "s": text}


def _paragraph(item):
    kind, text = item["t"], _ILLEGAL_XML.sub("", item["s"] or "")
    props = {"title": '<w:pPr><w:pStyle w:val="Title"/></w:pPr>', "h": '<w:pPr><w:pStyle w:val="Heading1"/></w:pPr>'}.get(kind, "")
    run = {"b": "<w:rPr><w:b/></w:rPr>", "i": "<w:rPr><w:i/></w:rPr>", "small": '<w:rPr><w:sz w:val="18"/></w:rPr>'}.get(kind, "")
    return '<w:p>%s<w:r>%s<w:t xml:space="preserve">%s</w:t></w:r></w:p>' % (props, run, escape(text))


def build_docx(blocks, lang="fr-FR"):
    """The bytes of the .docx. Timestamps are fixed: the same blocks give the same hash."""
    body = "".join(_paragraph(item) for item in blocks)
    document = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:document %s><w:body>%s<w:sectPr/></w:body></w:document>' % (_W, body)
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in (
            ("[Content_Types].xml", _CONTENT_TYPES), ("_rels/.rels", _RELS), ("word/_rels/document.xml.rels", _DOC_RELS),
            ("word/styles.xml", _STYLES.replace("fr-FR", lang)), ("word/document.xml", document),
        ):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, content.encode("utf-8"))
    return buffer.getvalue()


def docx_text(content):
    """The text of a .docx built here, paragraph by paragraph, for the tests and the trail."""
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        xml = archive.read("word/document.xml").decode("utf-8")
    paragraphs = re.findall(r"<w:p>(.*?)</w:p>", xml, re.S)
    text = "\n".join("".join(re.findall(r"<w:t[^>]*>(.*?)</w:t>", p, re.S)) for p in paragraphs)
    return text.replace("&lt;", "<").replace("&gt;", ">").replace("&amp;", "&")
