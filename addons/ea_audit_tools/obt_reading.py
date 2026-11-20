"""Reading uploaded financial statements for Opening Balance Testing. No Odoo; not in services/, whose
modules are pure figures (tests_pure/test_purity.py): this one talks to a service over the network.

The pages go to the document-reading service with the firm's own key (set by the platform owner on the
console, per firm: owner's ruling of 20/11/2026), and come back as the JSON of obt.reading_schema(). The
product never names the service to its users: on screen it is "AuditISA" that reads (owner, 20/11/2026).

The SDK is imported only when a document is read: a server whose update has not installed it yet answers
"not available", and the user types the figures by hand. Nothing here keeps the key or the pages.
"""
import base64
import json

#: The model that reads. Thinking stays adaptive (the model's default); effort high: figures must be exact.
MODEL = "claude-opus-5-5"
EFFORT = "high"
MAX_TOKENS = 16000
TIMEOUT_SECONDS = 300
#: The fallback beta: a declined request is answered by the fallback model chosen by the service.
FALLBACK_BETA = "server-side-fallback-2026-07-01"
#: What a request may carry: the service refuses more than 32 MB; base64 adds a third.
MAX_BYTES = 22 * 1024 * 1024
MEDIA_TYPES = {
    "application/pdf": "document",
    "image/png": "image", "image/jpeg": "image", "image/gif": "image", "image/webp": "image",
}
#: The words a reading can end with, besides "ok". Each has its sentence on the page (models/obt.py).
ERRORS = ("not_installed", "no_key", "key_refused", "unreachable", "busy", "too_large", "unsupported", "refused", "unreadable", "failed")


class ReadingError(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def media_type(name, mimetype):
    """The media type the service accepts for a file, or None."""
    if mimetype in MEDIA_TYPES:
        return mimetype
    lower = (name or "").lower()
    for suffix, kind in ((".pdf", "application/pdf"), (".png", "image/png"), (".jpg", "image/jpeg"),
                         (".jpeg", "image/jpeg"), (".gif", "image/gif"), (".webp", "image/webp")):
        if lower.endswith(suffix):
            return kind
    return None


def content_blocks(files, instructions):
    """The message: every page, then what to do with them. ``files``: [(name, mimetype, bytes)]."""
    blocks, total = [], 0
    for name, mimetype, data in files:
        kind = media_type(name, mimetype)
        if not kind:
            raise ReadingError("unsupported")
        total += len(data)
        if total > MAX_BYTES:
            raise ReadingError("too_large")
        source = {"type": "base64", "media_type": kind, "data": base64.standard_b64encode(data).decode("ascii")}
        blocks.append({"type": MEDIA_TYPES[kind], "source": source})
    if not blocks:
        raise ReadingError("unsupported")
    blocks.append({"type": "text", "text": instructions})
    return blocks


def _client(key):
    try:
        import anthropic  # noqa: PLC0415  imported here on purpose: see the module's docstring
    except ImportError:
        raise ReadingError("not_installed") from None
    return anthropic, anthropic.Anthropic(api_key=key, timeout=TIMEOUT_SECONDS, max_retries=2)


def read(key, files, instructions, schema, client=None):
    """The reading's JSON as a dict. ``client`` (tests): an object with beta.messages.create.
    Raises ReadingError with one of ERRORS."""
    if not key:
        raise ReadingError("no_key")
    blocks = content_blocks(files, instructions)
    if client is None:
        anthropic, client = _client(key)
        errors = (
            (anthropic.AuthenticationError, "key_refused"), (anthropic.PermissionDeniedError, "key_refused"),
            (anthropic.RateLimitError, "busy"), (anthropic.APIConnectionError, "unreachable"),
            (anthropic.APIStatusError, "failed"),
        )
    else:
        errors = ()
    try:
        response = client.beta.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            betas=[FALLBACK_BETA],
            fallbacks="default",
            output_config={"effort": EFFORT, "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": blocks}],
        )
    except Exception as error:  # noqa: BLE001  mapped to one word, most specific class first
        for kind, code in errors:
            if isinstance(error, kind):
                raise ReadingError(code) from None
        raise
    if getattr(response, "stop_reason", None) == "refusal":
        raise ReadingError("refused")
    if getattr(response, "stop_reason", None) == "max_tokens":
        raise ReadingError("unreadable")
    text = next((block.text for block in response.content if getattr(block, "type", None) == "text"), None)
    try:
        data = json.loads(text or "")
    except ValueError:
        raise ReadingError("unreadable") from None
    if not isinstance(data, dict):
        raise ReadingError("unreadable")
    return data
