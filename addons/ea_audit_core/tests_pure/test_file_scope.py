"""The file's scope (services/file_scope.py), loaded straight from its file: no Odoo."""
import importlib.util
import os

import pytest

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "file_scope.py")
_spec = importlib.util.spec_from_file_location("file_scope", _PATH)
file_scope = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(file_scope)


@pytest.mark.parametrize("complexity", ["very_simple", "non_complex", "complex"])
@pytest.mark.parametrize("nature", [None, "limited_review", "contractual_audit"])
def test_c52_is_no_longer_on_a_new_file(complexity, nature):
    """Owner's decision of 2026-11-16: the statutory deadlines paper leaves the file."""
    assert "C5.2" in file_scope.RETIRED_CODES
    assert not file_scope.code_in_scope("C5.2", "core", False, complexity, "SA", nature)


def test_its_neighbours_stay():
    assert file_scope.code_in_scope("C5.1", "core", False, "complex", "SA")
    assert file_scope.code_in_scope("C5.3", "standard", False, "complex", "SA")


# ---------------------------------------------------------------------------------------------
# The scope of 2026-11-17 (owner's table "tasks by engagement profile")
# ---------------------------------------------------------------------------------------------

import csv  # noqa: E402

_CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "ea.audit.task.template.csv")
with open(_CSV, encoding="utf-8") as _handle:
    TEMPLATES = [(row["code"], row["tier"], row["conditional"] == "True") for row in csv.DictReader(_handle)]


def scope(complexity, form="SA", nature=None, version=file_scope.SCOPE_CURRENT):
    return file_scope.scope_codes(TEMPLATES, complexity, form, nature, version)


def active(complexity, form="SA", version=file_scope.SCOPE_CURRENT, substantive=False):
    return {
        code for code, dormant in scope(complexity, form, version=version).items()
        if not dormant and (substantive or not file_scope.SUBSTANTIVE.match(code))
    }


@pytest.mark.parametrize("form, counts", [
    ("SA", {"very_simple": (77, 59), "non_complex": (109, 86), "complex": (112, 89)}),
    ("SARL", {"very_simple": (74, 56), "non_complex": (106, 83), "complex": (109, 86)}),
])
def test_the_matrix_counts(form, counts):
    """On the file of a new engagement, and active before any fact."""
    for complexity, (on_file, live) in counts.items():
        codes = scope(complexity, form)
        assert (len(codes), sum(1 for d in codes.values() if not d)) == (on_file, live), complexity


def test_very_simple_gets_the_tasks_every_audit_needs():
    codes = active("very_simple")
    assert {"P2.2", "P4.1", "P4.3", "S1.1", "S1.2", "S1.4", "S4.1", "S5.4", "S5.5", "C5.3"} <= codes
    assert not {"S1.3", "S5.6"} & codes
    # non-complex and complex differ from it by the walkthroughs and the general procedures only
    assert active("non_complex") - codes == {"S1.3", "S5.6"}
    assert active("complex") == active("non_complex")


@pytest.mark.parametrize("complexity", ["very_simple", "non_complex", "complex"])
def test_facts_decide_whether_at_every_complexity(complexity):
    codes = scope(complexity)
    for code in file_scope.FACT_CODES:
        assert codes.get(code) is True, code


@pytest.mark.parametrize("complexity", ["very_simple", "non_complex", "complex"])
def test_the_sa_papers_follow_the_legal_form(complexity):
    for code in ("C5.4", "C5.7", "C5.10"):
        assert code in active(complexity, "SA")
        assert code in active(complexity, "SA_AG")
        assert code not in scope(complexity, "SARL")
        assert code not in scope(complexity, "SAS")
    assert "C5.3" in active(complexity, "SARL")


@pytest.mark.parametrize("complexity", ["very_simple", "non_complex", "complex"])
def test_merged_tasks_leave_new_files(complexity):
    codes = scope(complexity)
    for code, target in (("P4.2", "P4.1"), ("C5.8", "E6.3"), ("C4.3", "C4.1")):
        assert code not in codes
        assert file_scope.MERGED_INTO[code] == target
        assert codes.get(target) is False


@pytest.mark.parametrize("complexity", ["very_simple", "non_complex", "complex"])
def test_substantive_lines_keep_their_scope(complexity):
    old = {c: d for c, d in scope(complexity, version=file_scope.SCOPE_LEGACY).items() if file_scope.SUBSTANTIVE.match(c)}
    new = {c: d for c, d in scope(complexity).items() if file_scope.SUBSTANTIVE.match(c)}
    assert old == new


def test_a_file_of_the_older_scope_keeps_its_rule():
    assert len(scope("very_simple", version=file_scope.SCOPE_LEGACY)) == 47
    assert len(scope("non_complex", version=file_scope.SCOPE_LEGACY)) == 108
    assert len(scope("complex", version=file_scope.SCOPE_LEGACY)) == 115
    assert "C4.3" in scope("complex", version=file_scope.SCOPE_LEGACY)
    assert file_scope.retired_codes(file_scope.SCOPE_LEGACY) == file_scope.RETIRED_2026_11_16
    assert file_scope.retired_codes(None) == file_scope.RETIRED_2026_11_16
