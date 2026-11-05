"""lib/upload-safety.ts: what may enter an audit file. An allowlist of what a working paper needs, a
signature check so the extension is not merely asserted, and a MIME derived from the bytes."""
import re

from .errors import ServiceError

_ZIP = [b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08"]
_OLE = [b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1"]
_OOXML_MARKER = b"[Content_Types].xml"

_KINDS = {
    "xlsx": ("application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", _ZIP),
    "docx": ("application/vnd.openxmlformats-officedocument.wordprocessingml.document", _ZIP),
    "pptx": ("application/vnd.openxmlformats-officedocument.presentationml.presentation", _ZIP),
    "xls": ("application/vnd.ms-excel", _OLE),
    "doc": ("application/msword", _OLE),
    "pdf": ("application/pdf", [b"%PDF"]),
    "png": ("image/png", [b"\x89PNG\r\n\x1a\n"]),
    "jpg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "jpeg": ("image/jpeg", [b"\xff\xd8\xff"]),
    "gif": ("image/gif", [b"GIF8"]),
    "webp": ("image/webp", [b"RIFF"]),
    "csv": ("text/csv", None),
    "txt": ("text/plain", None),
    "xml": ("text/plain", None),
    "json": ("application/json", None),
}
_UNSAFE = re.compile("[\x00-\x1f\x7f‪-‮⁦-⁩]")


def extension_of(filename):
    base = re.split(r"[/\\]", filename or "")[-1]
    dot = base.rfind(".")
    return "" if dot <= 0 else base[dot + 1:].lower()


def safe_filename(filename):
    """No path separators, control characters, leading dots or right-to-left overrides."""
    base = _UNSAFE.sub("", re.split(r"[/\\]", filename or "")[-1]).lstrip(".").strip()[:160]
    return base or "attachment"


def check_upload(filename, content):
    """(safe name, canonical mime), or file-type. The stored name and MIME come from what the bytes are."""
    extension = extension_of(filename)
    kind = _KINDS.get(extension)
    if not kind:
        raise ServiceError("file-type")
    mime, signatures = kind
    if signatures is None:
        if b"\x00" in content[:8192]:
            raise ServiceError("file-type")
    else:
        if not any(content.startswith(signature) for signature in signatures):
            raise ServiceError("file-type")
        if extension in ("xlsx", "docx", "pptx") and _OOXML_MARKER not in content:
            raise ServiceError("file-type")
    return safe_filename(filename), mime
