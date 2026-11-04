"""Loads paper definitions from data/ and resolves them. No Odoo import.

Replaces ALL_PAPERS, GROUP_DEFAULT and paperFor of lib/working-papers.ts. Definitions
come back shared and cached: treat them as read-only. The resolvers build new objects.
"""

import json
import os
from functools import lru_cache

from .tokens import DATA_DIR, resolve_legal_form_paper, resolve_paper

_PAPERS_DIR = os.path.join(DATA_DIR, "papers")
_SHADOWED_DIR = os.path.join(DATA_DIR, "papers_shadowed")


def _read(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


@lru_cache(maxsize=1)
def load_index():
    return _read(os.path.join(_PAPERS_DIR, "index.json"))


@lru_cache(maxsize=1)
def _group_defaults():
    return _read(os.path.join(DATA_DIR, "group_defaults.json"))


def bespoke_codes():
    """The codes with their own definition, in catalogue order."""
    return list(load_index()["papers"])


def has_bespoke_paper(code):
    return code in load_index()["papers"]


@lru_cache(maxsize=None)
def load_definition(code):
    """The unresolved bespoke definition of one code. KeyError when it has none."""
    if not has_bespoke_paper(code):
        raise KeyError(code)
    return _read(os.path.join(_PAPERS_DIR, "%s.json" % code))["definition"]


def load_shadowed(file_name):
    """A definition the registry never returns, kept as source material (index["shadowed"])."""
    return _read(os.path.join(_SHADOWED_DIR, file_name))["definition"]


def group_of_task(code):
    """The group id of a task: its member list, else its code's prefix, else None."""
    defaults = _group_defaults()
    return defaults["members"].get(code) or defaults["prefixes"].get(code.split(".")[0])


def default_definition(code):
    """The unresolved paper of a task with no bespoke definition, built from its group."""
    defaults = _group_defaults()
    group = group_of_task(code)
    head = defaults["groups"].get(group) if group else None
    return dict(head or defaults["fallback"], fields=defaults["fields"])


def resolve_definition(definition, edition="current", legal_form=None):
    """Edition first, then legal form, as paperFor does."""
    return resolve_legal_form_paper(resolve_paper(definition, edition), legal_form)


def paper_for(code, edition="current", legal_form=None):
    """The paper for a task, read for the engagement's edition and the client's form."""
    unresolved = load_definition(code) if has_bespoke_paper(code) else default_definition(code)
    return resolve_definition(unresolved, edition, legal_form)
