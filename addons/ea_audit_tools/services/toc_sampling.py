"""lib/toc-sampling.ts: SAMPLE 3.3, minimum sample sizes for tests of controls.

Discovery sampling: the sizes assume no or very few exceptions in the population;
exceptions found mean extend or stop and reassess (SAMPLE 3.6.2).
"""
import random as _random

from ._js import js_ceil, js_floor
from .control_labels import freq_label

#: The size a 25-item plan extends to after a single deviation.
TOC_EXTENDED_SIZE = 60


def norm_freq(frequency):
    s = (frequency if frequency is not None else "").lower()
    if "dail" in s or "jour" in s or "continuous" in s or "many" in s:
        return "daily"
    if "week" in s or "hebdo" in s:
        return "weekly"
    if "month" in s or "mens" in s:
        return "monthly"
    if "quart" in s or "trim" in s:
        return "quarterly"
    if "semi" in s or "semes" in s:
        return "semi_annually"
    if "ann" in s:
        return "annually"
    return s


_TABLE = {"weekly": 5, "monthly": 2, "quarterly": 2, "semi_annually": 2, "annually": 1}


def toc_suggested(control_type, frequency, population, sole, fr):
    """{size, rule}, {needPopulation: True}, or None when the frequency is unknown."""
    # The test of one belongs to a genuinely AUTOMATED control. An IT-dependent
    # manual control still has a person performing it: it follows the table.
    if control_type == "automated":
        return {
            "size": 1,
            "rule": "Contrôle automatisé — test unique (ITGC efficaces)" if fr else "Automated/application control — test of one (ITGCs effective)",
        }
    f = norm_freq(frequency)
    if f == "daily":
        if not population or population < 1:
            return {"needPopulation": True}
        if population > 250:
            if sole:
                return {"size": 60, "rule": "Quotidien, seul contrôle sur l'assertion → 60" if fr else "Daily, only control on its assertion → 60"}
            return {"size": 25, "rule": "Quotidien, population > 250 → 25" if fr else "Daily, population > 250 → 25"}
        if population >= 50:
            return {"size": js_ceil(population * 0.1), "rule": "50–250 occurrences → 10 %" if fr else "50–250 occurrences → 10%"}
        if population >= 5:
            return {"size": 5, "rule": "< 50 occurrences → 5" if fr else "Under 50 occurrences → 5"}
        return {"size": population, "rule": "< 5 occurrences → 100 %" if fr else "Under 5 occurrences → all of them"}
    size = _TABLE.get(f)
    if not size:
        return None
    capped = min(size, population) if population and population > 0 else size
    if fr:
        return {"size": capped, "rule": "Manuel, %s → minimum %d" % (freq_label(f, True).lower(), size)}
    return {"size": capped, "rule": "Manual, %s → minimum %d" % (freq_label(f, False).lower(), size)}


def draw_toc_sample(population, size, rng=None):
    """``size`` distinct occurrence numbers from 1 to ``population``, ascending.

    ``rng`` supplies the randomness: the server passes a generator derived from a
    stored seed, so a draw can be reproduced from its seed (F061).
    """
    rng = rng or _random.random
    n = max(0, js_floor(population))
    k = min(max(0, js_floor(size)), n)
    if k == 0:
        return []
    # partial Fisher-Yates over 1..n: exact, unbiased, cheap for a large population
    picked = {}
    out = []
    for i in range(k):
        j = i + js_floor(rng() * (n - i))
        vi = picked.get(i, i + 1)
        vj = picked.get(j, j + 1)
        out.append(vj)
        picked[j] = vi
        picked[i] = vj
    return sorted(out)


def seeded_rng(seed, random):
    """A generator whose i-th call returns ``random(seed, i)``."""
    index = [0]

    def rng():
        value = random(seed, index[0])
        index[0] += 1
        return value

    return rng


def toc_testing_started(grid):
    """True once any row of the E1.2 grid carries a result for any attribute."""
    if not grid or not isinstance(grid.get("rows"), list):
        return False
    for row in grid["rows"]:
        results = (row or {}).get("results") or {}
        if any(isinstance(v, str) and v != "" for v in results.values()):
            return True
    return False


def toc_evaluate(plan, tested, deviations):
    """Deviation evaluation: "high", "moderate", "rely", "extend" or "none"."""
    if deviations < 0:
        return "none"
    # A test extended to 60, or planned at 60, is judged on the 60 rule.
    if tested >= TOC_EXTENDED_SIZE or plan >= TOC_EXTENDED_SIZE:
        if deviations == 0:
            return "high"
        return "moderate" if deviations == 1 else "none"
    if plan >= 25:
        if deviations == 0:
            return "rely"
        return "extend" if deviations == 1 else "none"
    # 5, 2, 1 and the occurrence plans: the hypothesis is no exceptions at all.
    return "rely" if deviations == 0 else "none"
