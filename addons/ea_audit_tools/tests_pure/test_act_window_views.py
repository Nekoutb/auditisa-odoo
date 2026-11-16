"""Every window action the add-ons build in Python names its views: Odoo 19's web client reads
``action.views`` when a page passes the action to doAction, and stops on "Oops" when it is
missing (owner's report of 2026-11-16, "Draw the sample")."""
import ast
import pathlib

ADDONS = pathlib.Path(__file__).resolve().parents[2]


def _window_actions_without_views():
    missing = []
    for path in sorted(ADDONS.glob("ea_*/**/*.py")):
        if "tests" in path.parts or "tests_pure" in path.parts or "migrations" in path.parts:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Dict):
                continue
            keys = [key.value if isinstance(key, ast.Constant) else None for key in node.keys]
            kind = dict(zip(keys, node.values)).get("type")
            if isinstance(kind, ast.Constant) and kind.value == "ir.actions.act_window" and "views" not in keys:
                missing.append("%s:%d" % (path.relative_to(ADDONS), node.lineno))
    return missing


def test_every_window_action_names_its_views():
    assert _window_actions_without_views() == []
