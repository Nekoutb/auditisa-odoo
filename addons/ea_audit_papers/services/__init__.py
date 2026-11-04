"""Pure Python rules of working papers. Nothing in this package imports Odoo."""

from .canonical import canonical, digest
from .completeness import (
    NA,
    completeness_exempt,
    key_answered,
    paper_complete,
    paper_keys,
    paper_missing,
    paper_progress,
    required_keys,
    unanswered_keys,
)
from .definitions import (
    bespoke_codes,
    default_definition,
    group_of_task,
    has_bespoke_paper,
    load_definition,
    load_index,
    load_shadowed,
    paper_for,
    resolve_definition,
)
from .tokens import (
    applies_to_form,
    has_unresolved_legal_form_token,
    has_unresolved_token,
    isa_ref,
    legal_forms,
    organ_name,
    resolve_legal_form_paper,
    resolve_legal_form_text,
    resolve_paper,
    resolve_text,
    standards_editions,
    task_applies_to_form,
)
