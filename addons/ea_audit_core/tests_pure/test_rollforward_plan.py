"""Roll forward (services/rollforward_plan.py), loaded straight from its file: no Odoo."""
import importlib.util
import os

import pytest

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "rollforward_plan.py")
_spec = importlib.util.spec_from_file_location("rollforward_plan", _PATH)
plan = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(plan)

ALL = {field: True for field, _key in plan.CARRY_FIELDS}


def test_every_box_ticked_carries_everything_in_trail_order():
    assert plan.carry_keys(ALL) == list(plan.ROLLFORWARD_KEYS)


@pytest.mark.parametrize("field,key", plan.CARRY_FIELDS)
def test_each_box_unticked_leaves_out_its_item_only(field, key):
    keys = plan.carry_keys(dict(ALL, **{field: False}))
    assert key not in keys
    assert len(keys) == len(plan.ROLLFORWARD_KEYS) - 1


@pytest.mark.parametrize("carry,approach,expected", [
    ({"scope"}, "same", True),
    ({"scope"}, None, True),
    ({"scope"}, "change", False),
    (set(), "same", False),
])
def test_last_year_tasks_only_with_the_scope_carried_and_the_same_approach(carry, approach, expected):
    assert plan.uses_last_year_tasks(carry, approach) is expected


ROWS = [
    {"id": 1, "item": 10, "name": "statutes.pdf", "version": 1, "code": "P3.1", "deleted": False},
    {"id": 2, "item": 10, "name": "statutes.pdf", "version": 2, "code": "P3.1", "deleted": False},
    {"id": 3, "item": 20, "name": "bank.pdf", "version": 1, "code": "E4.7", "deleted": False},
    {"id": 4, "item": 20, "name": "old.pdf", "version": 1, "code": "E4.7", "deleted": True},
    {"id": 5, "item": 30, "name": "chart.pdf", "version": 1, "code": "P4.1", "deleted": False},
]


def test_all_evidence_copies_the_latest_live_version_of_each_file():
    chosen = plan.evidence_to_copy(ROWS, {"evidence"})
    assert [row["id"] for row in chosen] == [3, 2, 5]


def test_without_all_evidence_only_the_permanent_file_is_copied():
    chosen = plan.evidence_to_copy(ROWS, {"permanent"})
    assert [row["code"] for row in chosen] == ["P3.1", "P4.1"]
    assert chosen[0]["version"] == 2


def test_no_evidence_box_copies_nothing():
    assert plan.evidence_to_copy(ROWS, {"scope", "risks"}) == []


def test_last_years_team_is_listed_with_who_left_or_declined_unticked():
    lines = plan.team_lines([
        {"email": "p@firm.cm", "name": "P", "role": "partner", "state": "accepted", "active": True},
        {"email": "s@firm.cm", "name": "S", "role": "senior", "state": "accepted", "active": True},
        {"email": "x@firm.cm", "name": "X", "role": "staff", "state": "accepted", "active": False},
        {"email": "d@firm.cm", "name": "D", "role": "staff", "state": "declined", "active": True},
    ])
    assert [(line["email"], line["invite"], line["note"]) for line in lines] == [
        ("s@firm.cm", True, False), ("x@firm.cm", False, plan.NOTE_LEFT), ("d@firm.cm", False, plan.NOTE_DECLINED),
    ]


def test_invitations_skip_the_unticked_the_seated_and_the_repeats():
    lines = [
        {"invite": True, "email": " S@Firm.cm ", "role": "senior"},
        {"invite": True, "email": "s@firm.cm", "role": "staff"},
        {"invite": False, "email": "x@firm.cm", "role": "staff"},
        {"invite": True, "email": "p@firm.cm", "role": "manager"},
        {"invite": True, "email": "", "role": "staff"},
        {"invite": True, "email": "new@firm.cm", "role": "staff"},
    ]
    sent = plan.invitations(lines, ["P@firm.cm"])
    assert [(line["email"], line["role"]) for line in sent] == [("s@firm.cm", "senior"), ("new@firm.cm", "staff")]
