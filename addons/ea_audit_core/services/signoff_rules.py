"""Port of the pure half of lib/signoff-policy.ts and the rank table of lib/rbac.ts."""
import re

TEAM_LADDER = ("staff", "senior", "manager", "senior_manager", "director", "partner")
EQR_ROLE = "eqr_reviewer"
EQR_PAPER = "C4.2"

SIGNOFF_ROLES = ("preparer", "reviewer", "partner", "eqr")

# Tasks whose approval belongs to the audit partner alone (operator rule).
PARTNER_ONLY_APPROVAL = frozenset({"P5.2", "P7.2", "S6.1", "S6.2", "S3.1", "C1.1"})
# Papers whose phase gate looks for a partner signature (lib/gates.ts).
PARTNER_GATED = frozenset({"P1.1", "P2.2", "P5.2", "S3.1", "P7.2"})

# The firm's default matrix (F002, decision of 2026-10-27): first match wins.
DEFAULT_MATRIX = (
    (re.compile(r"^(E3\.1|E6\.3|E6\.10)$"), "senior", "manager"),
    (re.compile(r"^P[12]\."), "manager", "partner"),
    (re.compile(r"^P[3-7]\."), "senior", "manager"),
    (re.compile(r"^S[1-6]\."), "senior", "manager"),
    (re.compile(r"^E[1-6]\."), "staff", "senior"),
    (re.compile(r"^C[1-4]\."), "senior", "manager"),
    (re.compile(r"^C[56]\."), "manager", "partner"),
)
DEFAULT_PARTNER_SIGNOFF = frozenset({"P1.1", "P2.2", "P5.2", "P7.2", "S3.1", "S6.1", "S6.2", "C1.1", "C6.2"})

DEFAULT_MIN_PREPARER = "staff"
DEFAULT_MIN_REVIEWER = "senior"

# lib/rbac.ts. client_user belongs to the portal addon; 0 means no firm role.
FIRM_RANK = {
    "read_only": 1,
    "staff": 2,
    "senior": 3,
    "eqr_reviewer": 4,
    "manager": 4,
    "partner": 5,
    "firm_admin": 6,
}


def at_least(role, minimum):
    return FIRM_RANK.get(role, 0) >= FIRM_RANK[minimum]


def can_write(role):
    return bool(role) and role != "read_only"


def can_review(role):
    return at_least(role, "senior")


def can_partner_signoff(role):
    return at_least(role, "partner")


def may_hold_partner_seat(role):
    return at_least(role, "partner")


def team_rank(role):
    """Position on the ladder; -1 for anything off it (eqr_reviewer, None)."""
    return TEAM_LADDER.index(role) if role in TEAM_LADDER else -1


def is_ladder_role(value):
    return value in TEAM_LADDER


def below_minimum_code(required):
    return "role-below-task-minimum-%s" % required.replace("_", "-")


def default_partner_signoff(code):
    return (
        code in DEFAULT_PARTNER_SIGNOFF
        or code.startswith("C5.")
        or code in PARTNER_GATED
        or code in PARTNER_ONLY_APPROVAL
    )


def default_task_minimums(code):
    for pattern, min_preparer, min_reviewer in DEFAULT_MATRIX:
        if pattern.match(code):
            return min_preparer, min_reviewer
    return DEFAULT_MIN_PREPARER, DEFAULT_MIN_REVIEWER


def default_require_partner_on(codes):
    """Every task of the index needing the partner's own sign-off by default."""
    return sorted({c for c in codes if default_partner_signoff(c)} | PARTNER_GATED | PARTNER_ONLY_APPROVAL)


def default_policy(codes=()):
    return {
        "min_reviewer_role": DEFAULT_MIN_REVIEWER,
        "require_partner_on": default_require_partner_on(codes),
        "allow_sole_practitioner": False,
        "require_distinct_preparer_approver": True,
        "stored": False,
    }


def _higher(a, b):
    return a if team_rank(a) >= team_rank(b) else b


def effective_task_rule(policy, rules, code):
    """Port of effectiveTaskRule: the task's own rule where set, otherwise the
    matrix raised by the firm policy; the reviewer minimum is never below the
    preparer minimum. ``rules`` maps code -> dict(min_preparer, min_reviewer,
    partner_required), None meaning the firm default."""
    rule = rules.get(code) or {}
    matrix_preparer, matrix_reviewer = default_task_minimums(code)
    min_preparer = rule.get("min_preparer") or matrix_preparer
    min_reviewer = rule.get("min_reviewer") or _higher(matrix_reviewer, policy["min_reviewer_role"])
    partner_required = rule.get("partner_required")
    if partner_required is None:
        partner_required = default_partner_signoff(code) or code in policy["require_partner_on"]
    return {
        "min_preparer": min_preparer,
        "min_reviewer": _higher(min_reviewer, min_preparer),
        "partner_required": partner_required,
    }
