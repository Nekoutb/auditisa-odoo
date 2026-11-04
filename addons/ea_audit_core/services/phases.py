"""Port of phaseStillOpen (lib/gates.ts) and phaseOfTask (lib/engagement-dashboard.ts)."""

PHASE_RANK = {"acceptance": 0, "planning": 1, "execution": 2, "conclusion": 3, "archived": 4}

POST_REPORT_CODES = frozenset({"C6.1", "C6.2"})

ACCEPTANCE_CODES = frozenset({"P1.1", "P1.2", "P1.3", "P1.4", "P1.5", "P2.1", "S6.1", "S6.2", "P2.2", "P5.2"})


def phase_of_task(section, code):
    if section == "E":
        return "execution"
    if section in ("A", "B", "C", "F"):
        return "conclusion"
    return "acceptance" if code in ACCEPTANCE_CODES else "planning"


def phase_still_open(task_phase, current_phase, code=None):
    """None when a task of ``task_phase`` may proceed with the engagement in
    ``current_phase``, otherwise the code naming the phase still open."""
    need = PHASE_RANK.get(task_phase, 0)
    # Completion papers open from execution; only C6.x waits for the report.
    if task_phase == "conclusion" and not (code and code in POST_REPORT_CODES):
        need = PHASE_RANK["execution"]
    if need <= PHASE_RANK.get(current_phase, 0):
        return None
    return "%s-open" % current_phase
