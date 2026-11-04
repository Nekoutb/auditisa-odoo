"""What may enter an audit file (lib/upload-safety.ts). No Odoo import.

An allow-list of what a working paper needs, a signature check so that the extension is
not merely asserted, and a MIME derived from what the bytes are.
"""

import re

MAX_BYTES = 25 * 1024 * 1024

_ZIP = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")
_OLE = (b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1",)
_OOXML_MARKER = b"[Content_Types].xml"

_KINDS = (
    (("xlsx",), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _ZIP),
    (("docx",), "application/vnd.openxmlformats-officedocument.wordprocessingml.document", _ZIP),
    (("pptx",), "application/vnd.openxmlformats-officedocument.presentationml.presentation", _ZIP),
    (("xls",), "application/vnd.ms-excel", _OLE),
    (("doc",), "application/msword", _OLE),
    (("pdf",), "application/pdf", (b"%PDF",)),
    (("png",), "image/png", (b"\x89PNG\r\n\x1a\n",)),
    (("jpg", "jpeg"), "image/jpeg", (b"\xff\xd8\xff",)),
    (("gif",), "image/gif", (b"GIF8",)),
    (("webp",), "image/webp", (b"RIFF",)),
    (("csv",), "text/csv", None),
    (("txt",), "text/plain", None),
    (("xml",), "text/plain", None),
    (("json",), "application/json", None),
)
_BY_EXT = {ext: (mime, magic) for exts, mime, magic in _KINDS for ext in exts}

_NOTABLY_REFUSED = frozenset(
    "exe com scr bat cmd ps1 vbs js jse wsf wsh hta lnk msi dll cpl jar app sh svg html htm "
    "xlsm docm pptm xlsb iso img reg".split()
)
_UNSAFE_CHARS = re.compile("[\u0000-\u001f\u007f‪-‮⁦-⁩]")


class UnsafeFile(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def extension_of(filename):
    base = re.split(r"[/\\]", filename)[-1]
    dot = base.rfind(".")
    return "" if dot <= 0 else base[dot + 1 :].lower()


def safe_filename(filename):
    base = _UNSAFE_CHARS.sub("", re.split(r"[/\\]", filename)[-1]).lstrip(".").strip()[:160]
    return base or "attachment"


def _looks_textual(content):
    head = content[:8192]
    if b"\x00" in head:
        return False
    try:
        head.decode("utf-8")
        return True
    except UnicodeDecodeError as error:
        # a character cut at the 8192 boundary is still UTF-8
        if error.start >= len(head) - 3 and len(content) > len(head):
            return True
        # A CSV exported as latin-1 is still a legitimate ledger export.
        return not any(b < 0x09 or 0x0d < b < 0x20 for b in head)


def check_upload(filename, content):
    """(name, mime, ext), or UnsafeFile with a code. The uploader's claimed MIME is ignored."""
    name = safe_filename(filename)
    ext = extension_of(name)
    if not ext:
        raise UnsafeFile("no-extension")
    if ext in _NOTABLY_REFUSED:
        raise UnsafeFile("executable-refused")
    if ext not in _BY_EXT:
        raise UnsafeFile("extension-not-allowed")
    if not content:
        raise UnsafeFile("empty-file")
    mime, magic = _BY_EXT[ext]
    if magic is None:
        if not _looks_textual(content):
            raise UnsafeFile("content-mismatch")
    elif not any(content.startswith(sig) for sig in magic):
        raise UnsafeFile("content-mismatch")
    # An OOXML file is a zip; so is a renamed .zip full of anything. Search the whole
    # buffer: the part sits in the central directory, at the end of real workbooks.
    if ext in ("xlsx", "docx", "pptx") and _OOXML_MARKER not in content:
        raise UnsafeFile("not-an-office-file")
    return name, mime, ext


def allowed_extensions():
    return sorted(_BY_EXT)
