"""Work allocation (services/work_allocation.py): the rule in plain words, the check of a row and
"Suggest by role". Loaded as a bare package of the services folder: no Odoo."""
import importlib.util
import os
import sys
import types

_SERVICES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services")
_package = types.ModuleType("wa_services")
_package.__path__ = [_SERVICES]
sys.modules.setdefault("wa_services", _package)
_spec = importlib.util.spec_from_file_location("wa_services.work_allocation", os.path.join(_SERVICES, "work_allocation.py"))
wa = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(wa)
rules = sys.modules["wa_services.signoff_rules"]


def rule_of(code, **policy):
    base = rules.default_policy([code])
    base.update(policy)
    return rules.effective_task_rule(base, {}, code)


# ---- the rule in plain words ---------------------------------------------------------------

def test_a_partner_task_reads_as_the_mock_up():
    rule = {"min_preparer": "senior", "min_reviewer": "partner", "partner_required": True}
    assert wa.rule_text(rule) == "Prepared by a senior or above; partner approves"


def test_the_reviewer_is_named_when_someone_below_the_partner_reviews():
    assert wa.rule_text(rule_of("S3.1")) == "Prepared by a senior or above; reviewed by a manager or above; partner approves"
    assert wa.rule_text(rule_of("E4.1")) == "Prepared by a staff member or above; reviewed by a senior or above"


def test_p1_reads_from_the_default_matrix():
    assert wa.rule_text(rule_of("P1.1")) == "Prepared by a manager or above; partner approves"


def test_the_words_go_through_the_translator():
    french = {
        wa.PREPARED_BY: "Préparé par un %(role)s ou plus",
        wa.REVIEWED_BY: "revu par un %(role)s ou plus",
        wa.PARTNER_APPROVES: "l'associé approuve",
        "senior": "senior",
        "manager": "manager",
    }
    rule = {"min_preparer": "senior", "min_reviewer": "manager", "partner_required": True}
    assert wa.rule_text(rule, french.get) == "Préparé par un senior ou plus; revu par un manager ou plus; l'associé approuve"


def test_every_rung_has_its_word():
    assert set(wa.ROLE_WORDS) == set(rules.TEAM_LADDER)


def test_the_phase_groups():
    assert [wa.phase_of_code(c) for c in ("P1.1", "S3.1", "E4.2", "C1.1", "A1")] == [
        "planning", "strategy", "execution", "conclusion", "conclusion",
    ]


# ---- the check of a row ---------------------------------------------------------------------

ROLES = {1: "staff", 2: "senior", 3: "manager", 4: "partner"}


def row(**values):
    base = {"id": 10, "min_preparer": "senior", "min_reviewer": "manager", "preparer": None, "reviewer": None}
    base.update(values)
    return base


def test_the_reviewer_cannot_be_the_preparer():
    problems = wa.check_row(row(preparer=3, reviewer=3), ROLES)
    assert ("reviewer", wa.SAME_PERSON, True, None) in problems
    assert wa.refused([row(preparer=3, reviewer=3)], ROLES) == [10]


def test_the_reviewer_cannot_be_the_assignee_either():
    assert wa.refused([row(preparer=2, reviewer=3, assignee=3)], ROLES) == [10]


def test_below_the_minimum_is_a_warning_only():
    problems = wa.check_row(row(preparer=1, reviewer=2), ROLES)
    assert problems == [
        ("preparer", wa.BELOW_MINIMUM, False, "senior"),
        ("reviewer", wa.BELOW_MINIMUM, False, "manager"),
    ]
    assert wa.refused([row(preparer=1, reviewer=2)], ROLES) == []


def test_a_good_row_says_nothing():
    assert wa.check_row(row(preparer=2, reviewer=3), ROLES) == []
    assert wa.check_row(row(), ROLES) == []


# ---- Suggest by role --------------------------------------------------------------------------

MEMBERS = [
    {"user_id": 1, "role": "staff"},
    {"user_id": 5, "role": "staff"},
    {"user_id": 2, "role": "senior"},
    {"user_id": 3, "role": "manager"},
    {"user_id": 4, "role": "partner"},
]


def test_the_most_junior_allowed_prepares_and_the_next_level_reviews():
    out = wa.suggest([row(id=1, min_preparer="staff", min_reviewer="senior")], MEMBERS)
    assert out == {1: {"preparer": 1, "reviewer": 2}}


def test_a_higher_minimum_moves_both_up():
    out = wa.suggest([row(id=1, min_preparer="senior", min_reviewer="manager")], MEMBERS)
    assert out == {1: {"preparer": 2, "reviewer": 3}}


def test_the_work_spreads_evenly_between_equals():
    rows = [row(id=n, min_preparer="staff", min_reviewer="senior") for n in range(1, 5)]
    out = wa.suggest(rows, MEMBERS)
    preparers = [out[n]["preparer"] for n in range(1, 5)]
    assert sorted(preparers) == [1, 1, 5, 5]


def test_only_empty_boxes_are_filled():
    rows = [row(id=1, min_preparer="staff", min_reviewer="senior", preparer=5)]
    assert wa.suggest(rows, MEMBERS) == {1: {"reviewer": 2}}
    full = [row(id=1, min_preparer="staff", min_reviewer="senior", preparer=5, reviewer=3)]
    assert wa.suggest(full, MEMBERS) == {}


def test_the_reviewer_suggested_is_never_the_preparer():
    team = [{"user_id": 3, "role": "manager"}, {"user_id": 6, "role": "manager"}]
    out = wa.suggest([row(id=1, min_preparer="manager", min_reviewer="manager")], team)
    assert out == {1: {"preparer": 3, "reviewer": 6}}
    alone = [{"user_id": 3, "role": "manager"}]
    assert wa.suggest([row(id=1, min_preparer="manager", min_reviewer="manager")], alone) == {1: {"preparer": 3}}


def test_nobody_below_the_minimum_is_suggested():
    juniors = [{"user_id": 1, "role": "staff"}]
    assert wa.suggest([row(id=1, min_preparer="senior", min_reviewer="manager")], juniors) == {}


def test_existing_allocations_count_in_the_spread():
    rows = [
        row(id=1, min_preparer="staff", min_reviewer="senior", preparer=1, reviewer=2),
        row(id=2, min_preparer="staff", min_reviewer="senior"),
    ]
    assert wa.suggest(rows, MEMBERS)[2]["preparer"] == 5
