"""Pure Python rules of working papers. Nothing in this package imports Odoo."""

from .canonical import canonical, digest
from .completeness import (
    NA,
    completeness_exempt,
    js_trim,
    key_answered,
    missing_parts,
    paper_complete,
    paper_keys,
    paper_missing,
    paper_progress,
    required_keys,
    unanswered_keys,
)
from .definitions import (
    all_paper_keys,
    bespoke_codes,
    default_definition,
    group_of_task,
    group_siblings,
    has_bespoke_paper,
    load_definition,
    load_index,
    load_shadowed,
    paper_for,
    resolve_definition,
)
from .saving import (
    EQR_C42_KEYS,
    StaleEdit,
    acceptance_verdict,
    answer_changed,
    base_digests,
    field_digest,
    is_blank,
    norm_text,
    persons_on_save,
    plan_save,
    same_answer,
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
from .upload_safety import MAX_BYTES, UnsafeFile, allowed_extensions, check_upload, extension_of, safe_filename
