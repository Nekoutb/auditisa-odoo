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
