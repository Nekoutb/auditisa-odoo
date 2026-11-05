from datetime import date, datetime, timedelta

import pytest

from .. import health, loghash, rollout

NOW = datetime(2026, 11, 5, 12)
ASKED = NOW - timedelta(minutes=30)
TARGET = "abcdef123456"


def good_firm(**changes):
    firm = {
        "state": "active",
        "last_heartbeat_at": NOW - timedelta(minutes=5),
        "last_backup_at": NOW - timedelta(hours=8),
        "last_backup_ok": True,
        "last_restore_test_at": NOW - timedelta(days=2),
        "last_restore_test_ok": True,
        "cert_expires_on": date(2027, 1, 30),
        "disk_used_pct": 20,
        "mem_total_mb": 8000,
        "mem_available_mb": 4000,
        "update_state": "idle",
        "backup_key_escrowed": True,
    }
    firm.update(changes)
    return firm


def colour(**changes):
    return health.evaluate(good_firm(**changes), NOW)[0]


def reasons(**changes):
    return " | ".join(health.evaluate(good_firm(**changes), NOW)[1])


def test_a_good_firm_is_green():
    assert health.evaluate(good_firm(), NOW) == (health.GREEN, ["All is normal"])


@pytest.mark.parametrize("changes,expected", [
    ({"last_heartbeat_at": None}, health.RED),
    ({"last_heartbeat_at": NOW - timedelta(hours=1)}, health.AMBER),
    ({"last_heartbeat_at": NOW - timedelta(hours=3)}, health.RED),
    ({"last_backup_at": NOW - timedelta(hours=30)}, health.AMBER),
    ({"last_backup_at": NOW - timedelta(hours=60)}, health.RED),
    ({"last_backup_ok": False}, health.RED),
    ({"last_backup_at": None}, health.RED),
    ({"last_restore_test_at": NOW - timedelta(days=9)}, health.AMBER),
    ({"last_restore_test_at": NOW - timedelta(days=20)}, health.RED),
    ({"last_restore_test_ok": False}, health.RED),
    ({"last_restore_test_at": None}, health.RED),
    ({"cert_expires_on": None}, health.AMBER),
    ({"cert_expires_on": date(2026, 11, 20)}, health.AMBER),
    ({"cert_expires_on": date(2026, 11, 8)}, health.RED),
    ({"cert_expires_on": date(2026, 11, 1)}, health.RED),
    ({"disk_used_pct": 85}, health.AMBER),
    ({"disk_used_pct": 95}, health.RED),
    ({"mem_available_mb": 600}, health.AMBER),
    ({"mem_available_mb": 200}, health.RED),
    ({"update_state": "failed"}, health.RED),
    ({"update_state": "rolled_back"}, health.AMBER),
    ({"backup_key_escrowed": False}, health.AMBER),
    ({"ssh_sessions_24h": 2}, health.AMBER),
    ({"export_state": "failed"}, health.RED),
    ({"heartbeat_rejects_24h": 3}, health.AMBER),
])
def test_each_problem_gives_its_colour(changes, expected):
    assert colour(**changes) == expected


def test_a_new_firm_has_a_day_for_its_first_backup_and_a_week_for_its_first_restore_test():
    fresh = {"last_backup_at": None, "last_restore_test_at": None, "activated_at": NOW - timedelta(hours=3)}
    assert colour(**fresh) == health.GREEN
    late = {"last_backup_at": None, "last_restore_test_at": None, "activated_at": NOW - timedelta(days=30)}
    assert colour(**late) == health.RED


def test_ssh_sessions_covered_by_the_log_raise_no_alert():
    assert colour(ssh_sessions_24h=2, breakglass_24h=2) == health.GREEN
    assert "1 SSH login" in reasons(ssh_sessions_24h=2, breakglass_24h=1)


def test_the_worst_reason_comes_first():
    _, why = health.evaluate(good_firm(disk_used_pct=85, last_backup_ok=False), NOW)
    assert why[0] == "The last backup failed"
    assert "Disk 85% full" in why


def test_an_orphan_is_red_whatever_the_state():
    for state in ("provisioning", "active", "suspended", "archived"):
        found_colour, why = health.evaluate(good_firm(state=state, orphan_flag=True, orphan_detail="srv-1"), NOW)
        assert found_colour == health.RED
        assert "ORPHAN" in why[0]
        assert "srv-1" in why[0]


def test_states_that_expect_silence_are_grey():
    assert colour(state="archived", last_heartbeat_at=None) == health.GREY
    assert colour(state="suspended", last_heartbeat_at=None) == health.GREY
    assert colour(state="provisioning", last_heartbeat_at=None) == health.GREY
    assert colour(state="provisioning", job_failed=True) == health.RED


def test_offboarding_stays_watched():
    assert colour(state="offboarding", last_heartbeat_at=None) == health.RED


# ---------------------------------------------------------------- rollout


def lines(*states):
    return [{"id": i, "batch": batch, "state": state} for i, (batch, state) in enumerate(states)]


def test_the_canary_goes_alone_and_first():
    plan = rollout.plan_batches([1, 2, 3, 4, 5], 3, 2)
    assert plan[0] == (3, 0)
    assert plan[1:] == [(1, 1), (2, 1), (4, 2), (5, 2)]


def test_the_canary_must_be_one_of_the_firms():
    with pytest.raises(ValueError):
        rollout.plan_batches([1, 2], 9, 1)
    with pytest.raises(ValueError):
        rollout.plan_batches([1, 2], 1, 0)


def test_only_the_canary_is_asked_at_first():
    decision, ids = rollout.next_step(lines((0, "pending"), (1, "pending"), (1, "pending")))
    assert (decision, ids) == ("request", [0])


def test_nothing_more_until_the_canary_is_healthy():
    assert rollout.next_step(lines((0, "requested"), (1, "pending")))[0] == "wait"


def test_the_next_batch_goes_together():
    decision, ids = rollout.next_step(lines((0, "healthy"), (1, "pending"), (1, "pending"), (2, "pending")))
    assert (decision, ids) == ("request", [1, 2])


def test_it_ends_when_all_are_healthy():
    assert rollout.next_step(lines((0, "healthy"), (1, "healthy")))[0] == "done"


@pytest.mark.parametrize("bad", ["failed", "rolled_back", "timed_out"])
def test_it_stops_at_the_first_failure(bad):
    decision, ids = rollout.next_step(lines((0, bad), (1, "pending"), (2, "pending")))
    assert (decision, ids) == ("stopped", [1, 2])


def test_a_failure_in_a_batch_stops_the_following_ones():
    decision, ids = rollout.next_step(lines((0, "healthy"), (1, "failed"), (1, "requested"), (2, "pending")))
    assert (decision, ids) == ("stopped", [3])


def figures(**changes):
    data = {
        "last_heartbeat_at": NOW,
        "update_release": TARGET,
        "update_state": "ok",
        "release": TARGET,
        "last_backup_at": ASKED + timedelta(minutes=1),
        "health_color": "green",
    }
    data.update(changes)
    return data


def test_a_good_update_is_healthy():
    assert rollout.line_outcome(ASKED, TARGET, figures(), NOW) == rollout.HEALTHY


def test_no_backup_after_the_request_is_a_failure():
    assert rollout.line_outcome(ASKED, TARGET, figures(last_backup_at=ASKED - timedelta(hours=1)), NOW) == rollout.FAILED
    assert rollout.line_outcome(ASKED, TARGET, figures(last_backup_at=None), NOW) == rollout.FAILED


def test_the_firms_own_rollback_is_seen():
    assert rollout.line_outcome(ASKED, TARGET, figures(update_state="rolled_back"), NOW) == rollout.ROLLED_BACK
    assert rollout.line_outcome(ASKED, TARGET, figures(update_state="failed"), NOW) == rollout.FAILED


def test_a_heartbeat_older_than_the_request_proves_nothing():
    old = figures(last_heartbeat_at=ASKED - timedelta(minutes=1))
    assert rollout.line_outcome(ASKED, TARGET, old, NOW) == rollout.REQUESTED


def test_an_outcome_about_another_release_proves_nothing():
    other = figures(update_release="000000000000", update_state="failed")
    assert rollout.line_outcome(ASKED, TARGET, other, NOW) == rollout.REQUESTED


def test_a_red_firm_is_not_called_healthy():
    assert rollout.line_outcome(ASKED, TARGET, figures(health_color="red"), NOW) == rollout.REQUESTED


def test_silence_ends_in_a_timeout():
    silent = {"last_heartbeat_at": ASKED - timedelta(minutes=1)}
    assert rollout.line_outcome(ASKED, TARGET, silent, NOW) == rollout.REQUESTED
    assert rollout.line_outcome(ASKED, TARGET, silent, ASKED + timedelta(hours=2)) == rollout.TIMED_OUT


@pytest.mark.parametrize("firm,word", [
    ({"state": "suspended"}, "active"),
    ({"state": "active", "health_color": "red"}, "red"),
    ({"state": "active", "release_locked": True}, "locked"),
    ({"state": "active", "last_backup_at": None}, "backup"),
    ({"state": "active", "last_backup_at": NOW, "last_backup_ok": False}, "backup"),
])
def test_a_firm_without_a_way_back_takes_no_update(firm, word):
    assert word in rollout.ineligible_reason(firm)


def test_a_good_firm_is_eligible():
    assert rollout.ineligible_reason({"state": "active", "last_backup_at": NOW, "last_backup_ok": True}) is None


# ---------------------------------------------------------------- the log's chain


def chain(*rows):
    entries, previous = [], loghash.GENESIS
    for fields in rows:
        value = loghash.entry_hash(previous, fields)
        entries.append((previous, fields, value))
        previous = value
    return entries


def test_an_intact_chain_has_no_break():
    assert loghash.first_break(chain({"a": 1}, {"a": 2}, {"a": 3})) is None


def test_a_changed_row_is_found():
    entries = chain({"a": 1}, {"a": 2}, {"a": 3})
    entries[1] = (entries[1][0], {"a": 9}, entries[1][2])
    assert loghash.first_break(entries) == 1


def test_a_removed_row_is_found():
    entries = chain({"a": 1}, {"a": 2}, {"a": 3})
    del entries[1]
    assert loghash.first_break(entries) == 1
