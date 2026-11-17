"""OWL templates see only the component and a few names (Math, Object, Array, Date...). A call such as
``Boolean(x)`` in a template is read as ``ctx.Boolean(x)`` and the page stops with "ctx.Boolean is not a
function": Sampling, Journal entries and Findings stopped opening this way (found 2026-11-17). Write
``!!x``, or work the value out in the component."""
import pathlib
import re

ADDONS = pathlib.Path(__file__).resolve().parents[2]
NOT_IN_TEMPLATES = re.compile(r"(?<![\w.])(Boolean|Number|String|JSON|parseInt|parseFloat|isNaN|encodeURIComponent)\s*[.(]")
COMMENT = re.compile(r"<!--.*?-->", re.S)


def test_no_template_calls_a_global_owl_does_not_expose():
    found = []
    for path in sorted(ADDONS.glob("ea_*/static/src/**/*.xml")):
        text = COMMENT.sub("", path.read_text(encoding="utf-8"))
        for number, line in enumerate(text.splitlines(), 1):
            if NOT_IN_TEMPLATES.search(line):
                found.append(f"{path.relative_to(ADDONS)}:{number}: {line.strip()[:120]}")
    assert not found, "templates call globals OWL does not expose:\n" + "\n".join(found)
