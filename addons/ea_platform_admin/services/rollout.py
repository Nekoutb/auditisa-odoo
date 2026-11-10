"""The decisions of an update rollout. Pure.

The control plane never logs in to a firm. It names a release, with its SHA-256, in the firm's heartbeat
answer; the firm backs up, updates, checks itself and rolls itself back if needed
(deploy/firm/firm-update.sh), and says how it went in its next heartbeat. This module reads those
figures and says what happens next: canary first, then batches, and stop at the first failure.
"""

from datetime import timedelta

from .messages import _

PENDING = "pending"
REQUESTED = "requested"
HEALTHY = "healthy"
FAILED = "failed"
ROLLED_BACK = "rolled_back"
TIMED_OUT = "timed_out"
CANCELLED = "cancelled"

BAD_STATES = (FAILED, ROLLED_BACK, TIMED_OUT)
DEFAULT_TIMEOUT = timedelta(minutes=90)


def plan_batches(firm_ids, canary_id, batch_size):
    """[(firm_id, batch_number)]: the canary alone in batch 0, the others after it."""
    if canary_id not in firm_ids:
        raise ValueError("canary_not_in_firms")
    if batch_size < 1:
        raise ValueError("bad_batch_size")
    others = [firm_id for firm_id in firm_ids if firm_id != canary_id]
    lines = [(canary_id, 0)]
    for index, firm_id in enumerate(others):
        lines.append((firm_id, 1 + index // batch_size))
    return lines


def ineligible_reason(firm):
    """Why a firm cannot take part. Backups and health come first: an update needs a way back."""
    if firm.get("state") != "active":
        return _("firm not active")
    if firm.get("health_color") == "red":
        return _("red health")
    if firm.get("release_locked"):
        return _("release locked for this firm")
    if not firm.get("last_backup_at"):
        return _("no backup")
    if firm.get("last_backup_ok") is False:
        return _("last backup failed")
    return None


def line_outcome(requested_at, target, figures, now, timeout=DEFAULT_TIMEOUT):
    """New state of a requested line from the firm's last figures, or REQUESTED if undecided.

    Success needs all of: the target running, the firm saying the update went well, a heartbeat
    and a backup not older than the request, and a firm that is not red.
    """
    heartbeat = figures.get("last_heartbeat_at")
    fresh = bool(heartbeat and heartbeat >= requested_at)
    if fresh and figures.get("update_release") == target:
        state = figures.get("update_state")
        if state == "failed":
            return FAILED
        if state == "rolled_back":
            return ROLLED_BACK
        if state == "ok" and figures.get("release") == target:
            backup = figures.get("last_backup_at")
            if not backup or backup < requested_at:
                return FAILED
            if figures.get("health_color") != "red":
                return HEALTHY
    if now - requested_at > timeout:
        return TIMED_OUT
    return REQUESTED


def next_step(lines):
    """What the rollout does now, from its lines as dicts with keys `id`, `batch`, `state`.

    Returns (decision, line_ids), where decision is:
      "stopped"  a line failed: request nothing more; the lines still pending are cancelled
      "done"     every line is healthy
      "wait"     the current batch is still running
      "request"  line_ids are to be asked to update now
    A batch that is in flight when another of its lines fails finishes: it cannot be recalled.
    """
    if any(line["state"] in BAD_STATES for line in lines):
        return "stopped", [line["id"] for line in lines if line["state"] == PENDING]
    if all(line["state"] == HEALTHY for line in lines):
        return "done", []
    if any(line["state"] == REQUESTED for line in lines):
        return "wait", []
    batch = min(line["batch"] for line in lines if line["state"] == PENDING)
    return "request", [line["id"] for line in lines if line["batch"] == batch and line["state"] == PENDING]
