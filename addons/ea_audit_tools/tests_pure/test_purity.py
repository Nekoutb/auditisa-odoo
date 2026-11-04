"""The services must stay importable without Odoo, and away from the Python that
quietly differs from the TypeScript they were ported from."""
import ast
import os

import pytest

SERVICES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services")
ALLOWED = {
    "__future__", "decimal", "functools", "hashlib", "hmac", "math", "random", "re", "unicodedata",
}
MODULES = sorted(name for name in os.listdir(SERVICES) if name.endswith(".py"))


def _tree(name):
    with open(os.path.join(SERVICES, name), encoding="utf-8") as handle:
        return ast.parse(handle.read())


@pytest.mark.parametrize("name", MODULES)
def test_imports_only_the_standard_library(name):
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] in ALLOWED, alias.name
        elif isinstance(node, ast.ImportFrom) and node.level == 0:
            assert node.module.split(".")[0] in ALLOWED, node.module


@pytest.mark.parametrize("name", MODULES)
def test_no_builtin_that_rounds_differently(name):
    """``sum`` is compensated on floats from Python 3.12, ``round`` is bankers' rounding:
    both change a figure against a JavaScript reduce and Math.round."""
    for node in ast.walk(_tree(name)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            assert node.func.id not in ("sum", "round"), "%s:%d %s()" % (name, node.lineno, node.func.id)


@pytest.mark.parametrize("name", MODULES)
def test_no_table_placeholder_left(name):
    with open(os.path.join(SERVICES, name), encoding="utf-8") as handle:
        assert "__TABLE__" not in handle.read()
