"""The add-on catalogue and the desired-against-actual comparison. Pure.

A release's catalogue comes from its manifests (scripts/provision/build_catalogue.py, run by
build_release.sh). An add-on with "ea_client_addon": True in its manifest is optional for a firm;
everything else is a base feature, always on, with no switch of any kind.

Nothing here decides what a firm finally does: its root script checks the request again, against
the manifests of the signed release it runs. See docs/runbook/CLIENT-ADDONS.md.
"""

import ast
import json
import re
from datetime import timedelta
from pathlib import Path

from .messages import _

MARKER = "ea_client_addon"
SAMPLE_MARKER = "ea_client_addon_sample"
# Same shape as ea_audit_firm_agent/services/collect.py and deploy/firm/firm-addons.sh.
CODE = re.compile(r"^[a-z][a-z0-9_]{2,39}$")
_SHA = re.compile(r"^[0-9a-f]{12,40}$")
# Enough for a heartbeat that reports all of them to stay under heartbeat.MAX_BODY_BYTES.
MAX_OPTIONAL = 24
MAX_TEXT = 300
# A firm acts within its heartbeat, its five-minute timer and its five-minute cron.
SWITCH_GRACE = timedelta(hours=1)

ON, OFF, SWITCHING_ON, SWITCHING_OFF, DIFFERS_ON, DIFFERS_OFF, NOT_IN_RELEASE = (
    "on", "off", "switching_on", "switching_off", "differs_on", "differs_off", "not_in_release",
)
DIFFERENT = (DIFFERS_ON, DIFFERS_OFF, NOT_IN_RELEASE)


class CatalogueRefused(Exception):
    def __init__(self, message):
        super().__init__(message)
        self.message = message


def scan(folder):
    """The catalogue entries of a folder of addons. Same result as build_catalogue.py."""
    entries = []
    for manifest in sorted(Path(folder).glob("*/__manifest__.py")):
        code = manifest.parent.name
        if code.startswith("ea_platform_") or not (manifest.parent / "__init__.py").is_file():
            continue
        data = ast.literal_eval(manifest.read_text(encoding="utf-8"))
        if not data.get("installable", True):
            continue
        entries.append({
            "code": code,
            "name": str(data.get("name") or code),
            "summary": str(data.get("summary") or ""),
            "version": str(data.get("version") or ""),
            "optional": data.get(MARKER) is True,
            "sample": data.get(SAMPLE_MARKER) is True,
        })
    return entries


def _entry(item):
    if not isinstance(item, dict) or set(item) != {"code", "name", "summary", "version", "optional", "sample"}:
        raise CatalogueRefused(_("The catalogue has an entry of the wrong form."))
    code = item["code"]
    if not isinstance(code, str) or not CODE.match(code):
        raise CatalogueRefused(_("The catalogue has an invalid add-on code."))
    if code.startswith("ea_platform_"):
        raise CatalogueRefused(_("The catalogue lists the control plane's own addon."))
    for key in ("name", "summary", "version"):
        if not isinstance(item[key], str) or len(item[key]) > MAX_TEXT:
            raise CatalogueRefused(_("The catalogue has a text that is too long or not a text."))
    if type(item["optional"]) is not bool or type(item["sample"]) is not bool:
        raise CatalogueRefused(_("The catalogue has an entry of the wrong form."))
    return dict(item)


def parse_catalogue(raw, release_sha):
    """The entries of a catalogue file made for this release, or CatalogueRefused."""
    try:
        document = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError, AttributeError):
        raise CatalogueRefused(_("This file is not a catalogue.")) from None
    if not isinstance(document, dict) or document.get("schema") != 1 or not isinstance(document.get("addons"), list):
        raise CatalogueRefused(_("This file is not a catalogue."))
    if document.get("release") != release_sha or not _SHA.match(release_sha or ""):
        raise CatalogueRefused(_("This catalogue was made for another release."))
    entries = [_entry(item) for item in document["addons"]]
    codes = [entry["code"] for entry in entries]
    if len(set(codes)) != len(codes) or not codes:
        raise CatalogueRefused(_("The catalogue is empty or lists an add-on twice."))
    if sum(1 for entry in entries if entry["optional"]) > MAX_OPTIONAL:
        raise CatalogueRefused(_("A release may carry %(count)s optional add-ons at most.", count=MAX_OPTIONAL))
    return entries


def desired_answer(asked, optional_in_release):
    """What a firm may be asked: only optional add-ons that its running release carries."""
    return sorted(set(asked) & set(optional_in_release))


def line_status(desired, reported, known, in_release, changed_at, now):
    """How one optional add-on stands on one firm, from what was asked and what the firm says."""
    if desired and not in_release:
        return NOT_IN_RELEASE
    if known and desired == reported:
        return ON if desired else OFF
    if not known and not desired:
        return OFF
    recent = bool(changed_at) and now - changed_at <= SWITCH_GRACE
    if desired:
        return SWITCHING_ON if recent else DIFFERS_ON
    return SWITCHING_OFF if recent else DIFFERS_OFF


def split_reported(reported, known_codes):
    """(codes the catalogue knows, how many it does not). An unknown code is counted, never kept."""
    known = sorted(code for code in set(reported or ()) if code in known_codes)
    return known, len(set(reported or ())) - len(known)
