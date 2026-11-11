"""How far a promotion has gone, for the Status page's Versions panel. Pure: no Odoo, no network.

Staging (the practice computer) reports the steps of its update in its heartbeat: a step out of a total, a
step code, the space concerned, and on failure a reason code (ea_platform_admin/services/practice.py, closed
words only). The console adds one step in front, the wait before Staging picks the request up, and leaves
out the practice computer's last one, "done", which is no work. Production is read from the rollout's lines.
"""

from .environments import same_commit

# After this long without news the page stops refreshing by itself and says so.
LATE_MINUTES = 20
QUIET_MINUTES = 60
BAD_LINE_STATES = ("failed", "rolled_back", "timed_out")


def _percent(step, total):
    """The middle of step `step` out of `total`, so that the first step already shows a little."""
    if total < 1:
        return 0
    return max(3, min(100, round((step - 0.5) * 100 / total)))


def staging_progress(asked, running, progress, asked_minutes=None, report_minutes=None):
    """What the Staging row shows.

    `asked`: the commit the console asked Staging to take and Staging does not run yet, or None.
    `running`: the commit Staging runs. `progress`: its last report (a dict) or None.
    `asked_minutes`, `report_minutes`: how long ago the request was made and the report written.

    Returns a dict. `state` is one of:
      idle       nothing is going on
      waiting    asked, and Staging has not said anything about it yet
      running    Staging is installing it: `step` of `total`, `code`, `slug`, and for a space `index` of `count`
      finishing  the spaces run the new version; the demo template is being rebuilt
      failed     Staging could not install it and put everything back: `reason`, `slug`
      warning    the spaces run the new version but the demo template was not rebuilt: `reason`
    `busy` says whether the page should keep refreshing by itself; `late` that news is overdue.
    """
    result = {"state": "idle", "step": 0, "total": 0, "percent": 0, "code": None, "slug": None, "reason": None,
              "index": 0, "count": 0, "busy": False, "late": False}
    mine = bool(progress) and same_commit(progress["target"], asked or running or "")
    if mine:
        # The console's first step is the wait; the practice computer's last one ("done") is not shown.
        total = max(progress["total"], 2)
        step = min(progress["step"] + 1, total)
        count = max(progress["total"] - 5, 0)
        result.update(step=step, total=total, percent=_percent(step, total), code=progress["code"],
                      slug=progress["slug"], count=count,
                      index=min(max(progress["step"] - 2, 0), count) if progress["code"] == "space" else 0)
    quiet = report_minutes is not None and report_minutes > QUIET_MINUTES
    if asked:
        if not mine:
            late = asked_minutes is not None and asked_minutes > LATE_MINUTES
            result.update(state="waiting", step=1, percent=3, late=late,
                          busy=not (asked_minutes is not None and asked_minutes > QUIET_MINUTES))
            return result
        if progress["failed"]:
            result.update(state="failed", reason=progress["reason"] or "other")
            return result
        result.update(state="running", busy=not quiet, late=report_minutes is not None and report_minutes > LATE_MINUTES)
        return result
    if mine and progress["failed"]:
        result.update(state="warning", reason=progress["reason"] or "other")
        return result
    if mine and progress["code"] != "done" and not quiet:
        result.update(state="finishing", busy=True)
        return result
    result.update(step=0, total=0, percent=0, code=None, slug=None, index=0, count=0)
    return result


def production_progress(rollout_state, lines):
    """What the Production row shows, from the last rollout that started.

    `lines`: one dict per firm of the rollout, with `firm` (its name) and `state` (the rollout line's).
    `state` is idle (no rollout, or it ended well), running, or stopped (a firm failed: the others were left alone).
    """
    result = {"state": "idle", "done": 0, "total": 0, "percent": 0, "now": [], "bad": [], "waiting": 0,
              "untouched": 0, "busy": False}
    if rollout_state not in ("running", "stopped", "done") or not lines:
        return result
    done = [line for line in lines if line["state"] == "healthy"]
    result.update(
        done=len(done), total=len(lines),
        percent=round(len(done) * 100 / len(lines)),
        now=[line["firm"] for line in lines if line["state"] == "requested"],
        bad=[(line["firm"], line["state"]) for line in lines if line["state"] in BAD_LINE_STATES],
        waiting=len([line for line in lines if line["state"] == "pending"]),
        untouched=len([line for line in lines if line["state"] == "cancelled"]),
    )
    if rollout_state == "running":
        result.update(state="running", busy=True)
    elif rollout_state == "stopped":
        result.update(state="stopped")
    return result
