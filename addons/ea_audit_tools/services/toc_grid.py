"""lib/toc-grid.ts: the rows the "effective" conclusion needs on the E1.2 grid."""
from ._js import is_finite, js_round


def toc_rows_planned(sample_size):
    """The planned sample size; 0 when none was planned, and "effective" is then refused."""
    if is_finite(sample_size) and sample_size > 0:
        return js_round(sample_size)
    return 0


def toc_rows_tested(grid):
    """Rows with every attribute answered; 0 when the grid or its attributes are missing."""
    if not grid or not isinstance(grid.get("rows"), list):
        return 0
    attributes = grid.get("attributes")
    if not isinstance(attributes, list) or len(attributes) == 0:
        return 0
    count = 0
    for row in grid["rows"]:
        results = row.get("results") or {}
        if all(results.get(a, "") not in ("", None) for a in attributes):
            count += 1
    return count
