import hashlib
import json

import pytest

from ea_audit_firm_agent.services import errors, signing
from ea_audit_firm_agent.services.collect import build_figures, parse_desired

KNOWN = {"res.partner", "ea.audit.engagement"}


def test_the_addon_is_read_from_the_path_only():
    paths = [
        "/opt/odoo19/src/odoo/models.py",
        "/opt/auditisa-odoo/current/addons/ea_audit_tools/models/tb.py",
        "/opt/auditisa-odoo/current/addons/ea_audit_core/models/engagement.py",
    ]
    assert errors.module_of(paths) == "ea_audit_core"
    assert errors.module_of(["/home/x/Agro SA/file.py"]) == "-"


@pytest.mark.parametrize("name,expected", [
    ("res.partner", "res.partner"),
    ("Agro SA", "-"),
    ("agro_sa", "-"),          # the right shape, but no such model: a request cannot choose it
    (None, "-"),
    ("res.partner'; drop", "-"),
])
def test_a_model_is_kept_only_if_the_registry_knows_it(name, expected):
    assert errors.model_code(name, KNOWN) == expected


def test_an_exception_is_kept_as_its_class_name_only():
    class ValueErrorWithClientData(Exception):
        pass

    assert errors.kind_code(ValueError) == "ValueError"
    assert errors.kind_code(ValueErrorWithClientData) == "ValueErrorWithClientData"
    assert errors.kind_code(type("x", (), {"__name__": "Agro SA, awa@agro.cm"})) == "Error"


def test_lines_are_counted_and_anything_else_is_dropped():
    lines = [
        errors.line("ea_audit_core", "res.partner", "ValueError", 1800000000),
        errors.line("ea_audit_core", "res.partner", "ValueError", 1800000100),
        errors.line("-", "-", "KeyError", 1800000050),
        "1800000000 ea_audit_core res.partner Agro SA awa@agro.cm\n",
        "Traceback: Agro SA, 12 500 000 FCFA\n",
        "garbage",
    ]
    found = errors.aggregate(lines)
    assert found == [
        {"module": "ea_audit_core", "model": "res.partner", "kind": "ValueError", "count": 2, "last": 1800000100},
        {"module": "-", "model": "-", "kind": "KeyError", "count": 1, "last": 1800000050},
    ]
    assert "Agro" not in json.dumps(found)


def test_at_most_a_few_groups_go_in_a_heartbeat():
    lines = [errors.line("ea_audit_core", "-", f"Error{n}", 1800000000) for n in range(20)]
    assert len(errors.aggregate(lines)) == errors.MAX_REPORTED


def test_the_heartbeat_carries_the_errors_and_the_visit_as_given():
    figures = build_figures({"release": "abcdef1"}, {}, {}, 1, 0, False, (), [], {"id": 3, "state": "open"})
    assert figures["errors"] == []
    assert figures["support_visit"] == {"id": 3, "state": "open"}
    assert "support_visit" not in build_figures({"release": "abcdef1"}, {}, {}, 1, 0, False)


def test_a_visit_request_must_have_its_exact_form():
    good = {"id": 7, "minutes": 60, "token_sha256": "a" * 64}
    assert parse_desired(json.dumps({"support_visit": good}).encode())["support_visit"] == good
    for bad in (
        {**good, "minutes": 241}, {**good, "minutes": 0}, {**good, "id": "7"}, {**good, "token_sha256": "x" * 64},
        {**good, "password": "secret"}, {"id": 7, "minutes": 60},
    ):
        assert "support_visit" not in parse_desired(json.dumps({"support_visit": bad}).encode())
    assert parse_desired(b'{"support_visit_end": 7}')["support_visit_end"] == 7
    assert "support_visit_end" not in parse_desired(b'{"support_visit_end": "7"}')


def test_the_support_channel_signs_apart_from_the_heartbeat():
    body = b'{"refs":[]}'
    ticket = signing.sign_kind(signing.PREFIX_TICKET, "t" * 64, "cabinet-a", 1800000000, body)
    sync = signing.sign_kind(signing.PREFIX_SYNC, "t" * 64, "cabinet-a", 1800000000, body)
    heartbeat = signing.sign("t" * 64, "cabinet-a", 1800000000, body)
    assert len({ticket, sync, heartbeat}) == 3
    assert len(hashlib.sha256(body).hexdigest()) == 64
