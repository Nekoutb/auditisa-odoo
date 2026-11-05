"""Edition and legal-form resolution of a paper definition. No Odoo import.

Ports lib/standards-edition.ts (resolveText, resolvePaper) and lib/legal-forms.ts
(resolveLegalFormText, appliesToForm, resolveLegalFormPaper, taskAppliesToForm).
Parity with both is enforced by tests/pure/test_parity.py; behaviour that looks odd
below is kept because the TypeScript has it:

- a value's language comes from its property name alone (`fr`, `*Fr`), so `std`
  resolves in English for a French reader;
- an unknown token stays visible rather than failing;
- a missing or unknown legal form reads as OTHER, for the vocabulary AND for the
  `forms` filter: a procedure restricted to ["SA"] is dropped for OTHER.
"""

import json
import os
import re
from functools import lru_cache

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")

_EDITION_TOKEN = re.compile(r"\{\{([A-Za-z0-9_.]+)\}\}")
_FORM_TOKEN = re.compile(r"\[\[lf\.([a-z]+)\]\]")
# How French determines each name, from FR_DETERMINER of lib/legal-forms.ts: masculine,
# feminine, elided (v), plural. Not in data/: export_papers.ts exports the vocabulary only.
_FR_DETERMINER = {
    "SA": {"form": "f", "board": "m", "chair": "m", "ceo": "m", "executive": "m", "meeting": "v", "members": "p", "officers": "p", "holders": "p"},
    "SA_AG": {"form": "f", "board": "v", "chair": "v", "ceo": "v", "executive": "v", "meeting": "v", "members": "p", "officers": "v", "holders": "p"},
    "SARL": {"form": "f", "board": "m", "chair": "m", "ceo": "m", "executive": "m", "meeting": "v", "members": "p", "officers": "p", "holders": "p"},
    "SAS": {"form": "f", "board": "m", "chair": "m", "ceo": "m", "executive": "m", "meeting": "p", "members": "p", "officers": "m", "holders": "p"},
    "GIE": {"form": "m", "board": "p", "chair": "v", "ceo": "v", "executive": "v", "meeting": "v", "members": "p", "officers": "p", "holders": "p"},
    "OTHER": {"form": "f", "board": "v", "chair": "m", "ceo": "m", "executive": "m", "meeting": "v", "members": "p", "officers": "p", "holders": "p"},
}
_FR_ARTICLES = {
    "none": {"m": "le ", "f": "la ", "v": "l'", "p": "les "},
    "de": {"m": "du ", "f": "de la ", "v": "de l'", "p": "des "},
    "a": {"m": "au ", "f": "à la ", "v": "à l'", "p": "aux "},
    "dem": {"m": "ce ", "f": "cette ", "v": "cet ", "p": "ces "},
}
_FR_ARTICLE_TOKEN = re.compile(
    r"(^|[\W\d_])(de l['’]|de la |du |des |à l['’]|à la |au |aux |l['’]|le |la |les |cette |cet |ce )\[\[lf\.([a-z]+)\]\]",
    re.IGNORECASE,
)


def _read(name):
    with open(os.path.join(DATA_DIR, name), encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def _refs():
    return _read("standards_refs.json")


@lru_cache(maxsize=1)
def _forms():
    return _read("legal_forms.json")


def standards_editions():
    return list(_refs()["editions"])


def legal_forms():
    return list(_forms()["forms"])


def lang_of(key):
    """The language a paper property is written in, from its name."""
    return "fr" if key == "fr" or key.endswith("Fr") else "en"


def _check_edition(edition):
    if edition not in _refs()["editions"]:
        raise ValueError("unknown standards edition: %r" % (edition,))


def isa_ref(edition, key, locale="en"):
    """The reference string of one requirement under one edition."""
    _check_edition(edition)
    pair = _refs()["refs"][key][edition]
    return pair[1] if locale == "fr" else pair[0]


def resolve_text(text, edition, locale):
    """Substitute every {{key}} in one string. Unknown keys are left visible."""
    if "{{" not in text:
        return text
    refs = _refs()["refs"]

    def sub(match):
        key = match.group(1)
        return isa_ref(edition, key, locale) if key in refs else match.group(0)

    return _EDITION_TOKEN.sub(sub, text)


def _resolve_edition_value(value, edition, locale):
    if isinstance(value, str):
        return resolve_text(value, edition, locale)
    if isinstance(value, list):
        return [_resolve_edition_value(v, edition, locale) for v in value]
    if isinstance(value, dict):
        return {k: _resolve_edition_value(v, edition, lang_of(k)) for k, v in value.items()}
    return value


def resolve_paper(definition, edition):
    """The paper as the engagement reads it: every {{token}} replaced."""
    _check_edition(edition)
    return _resolve_edition_value(definition, edition, "en")


def has_unresolved_token(text):
    return _EDITION_TOKEN.search(text) is not None


def normalise_form(form):
    """A form this catalogue knows, otherwise OTHER."""
    return form if isinstance(form, str) and form in _forms()["forms"] else "OTHER"


def organ_name(form, key, locale):
    pair = _forms()["vocabulary"][normalise_form(form)][key]
    return pair[1] if locale == "fr" else pair[0]


def _french_articles(text, form):
    """The article written before a token states the construction (none, de, à, the
    demonstrative); _FR_DETERMINER decides the form it takes, so "à l'[[lf.board]]" reads
    "au conseil" on an SA and "à l'administrateur général" on an SA_AG."""
    determiners = _FR_DETERMINER[normalise_form(form)]

    def sub(match):
        before, article, key = match.groups()
        if key not in determiners:
            return match.group(0)
        lower = article.lower()
        if lower.startswith(("de ", "du ", "des ")):
            construction = "de"
        elif lower.startswith(("à ", "au ", "aux ")):
            construction = "a"
        elif lower.startswith(("cette ", "cet ", "ce ")):
            construction = "dem"
        else:
            construction = "none"
        chosen = _FR_ARTICLES[construction][determiners[key]]
        if article[0] == article[0].upper():
            chosen = chosen[0].upper() + chosen[1:]
        return "%s%s%s" % (before, chosen, organ_name(form, key, "fr"))

    return _FR_ARTICLE_TOKEN.sub(sub, text)


def resolve_legal_form_text(text, form, locale):
    """Substitute every [[lf.key]] in one string. Unknown keys are left visible."""
    if "[[lf." not in text:
        return text
    keys = _forms()["organ_keys"]

    def sub(match):
        key = match.group(1)
        return organ_name(form, key, locale) if key in keys else match.group(0)

    prepared = _french_articles(text, form) if locale == "fr" else text
    return _FORM_TOKEN.sub(sub, prepared)


def has_unresolved_legal_form_token(text):
    return _FORM_TOKEN.search(text) is not None


def applies_to_form(forms, form):
    """Whether a procedure or an item restricted to some forms applies to this one."""
    if not forms:
        return True
    return normalise_form(form) in forms


def _resolve_form_value(value, form, locale):
    if isinstance(value, str):
        return resolve_legal_form_text(value, form, locale)
    if isinstance(value, list):
        return [
            _resolve_form_value(v, form, locale)
            for v in value
            # any object of any array that names its forms is dropped for the others
            if not (isinstance(v, dict) and "forms" in v) or applies_to_form(v["forms"], form)
        ]
    if isinstance(value, dict):
        return {k: _resolve_form_value(v, form, lang_of(k)) for k, v in value.items()}
    return value


def resolve_legal_form_paper(definition, form):
    """The paper as the client reads it: organs named, other forms' items removed."""
    return _resolve_form_value(definition, normalise_form(form), "en")


def task_applies_to_form(code, form):
    """Whether a file-index code is instantiated on a file of this form (unknown form: yes)."""
    excluded = _forms()["task_exclusions"].get(code)
    if not excluded or form not in _forms()["forms"]:
        return True
    return form not in excluded
