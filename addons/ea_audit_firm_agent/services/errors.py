"""Technical errors, reduced to codes before anything is written down. Pure.

An error message, a traceback's text and a record's values can all hold client data, so none of
them is kept: only the addon whose code raised it, the model it concerned, the exception's class
name, the time and a count. Each is checked against a closed shape; a model name must also be one
the registry knows, so a request cannot choose what is recorded.
"""

import re
import time

_ADDON_PATH = re.compile(r"[/\\]addons[/\\]([a-z][a-z0-9_]{1,63})[/\\]")
_MODULE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_MODEL = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9_]+){0,6}$")
_KIND = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")
_LINE = re.compile(r"^(\d{10}) ([a-z][a-z0-9_]{1,63}|-) ([a-z0-9_.]{1,80}|-) ([A-Za-z_][A-Za-z0-9_]{0,63})$")
MAX_REPORTED = 8


def module_of(paths):
    """The innermost addon in a traceback's file paths, or '-'. Only the path is read, never a line."""
    found = "-"
    for path in paths:
        match = _ADDON_PATH.search(path or "")
        if match:
            found = match.group(1)
    return found if _MODULE.match(found) else "-"


def model_code(name, known):
    return name if isinstance(name, str) and len(name) <= 80 and _MODEL.match(name) and name in known else "-"


def kind_code(exception_type):
    name = getattr(exception_type, "__name__", "")
    return name if _KIND.match(name) else "Error"


def line(module, model, kind, when=None):
    return f"{int(when or time.time()):010d} {module} {model} {kind}\n"


def aggregate(lines):
    """[{module, model, kind, count, last_at}], the most frequent first, at most MAX_REPORTED.

    A malformed line is dropped. `last_at` is seconds since the epoch, made into text by the caller.
    """
    groups = {}
    for raw in lines:
        match = _LINE.match(raw.strip())
        if not match:
            continue
        stamp, module, model, kind = int(match[1]), match[2], match[3], match[4]
        entry = groups.setdefault((module, model, kind), {"count": 0, "last": 0})
        entry["count"] += 1
        entry["last"] = max(entry["last"], stamp)
    ranked = sorted(groups.items(), key=lambda item: (-item[1]["count"], item[0]))[:MAX_REPORTED]
    return [
        {"module": module, "model": model, "kind": kind, "count": min(entry["count"], 100000), "last": entry["last"]}
        for (module, model, kind), entry in ranked
    ]
