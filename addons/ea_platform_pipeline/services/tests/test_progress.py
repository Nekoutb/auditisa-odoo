"""How far a promotion has gone, as the Status page's Versions panel reads it. Pure."""

from ea_platform_pipeline.services import progress

OLD = "abcdef123456"
NEW = "fedcba654321aaaaaaaaaaaaaaaaaaaaaaaaaaaa"


def report(step, code, total=9, slug=None, failed=False, reason=None, target=NEW[:12]):
    return {"target": target, "step": step, "total": total, "code": code, "slug": slug, "failed": failed, "reason": reason}


def test_nothing_asked_and_nothing_reported_is_idle():
    result = progress.staging_progress(None, OLD, None)
    assert (result["state"], result["busy"], result["percent"]) == ("idle", False, 0)
    assert progress.staging_progress(None, None, None)["state"] == "idle"


def test_asked_and_not_picked_up_yet_is_the_first_step():
    result = progress.staging_progress(NEW, OLD, None, asked_minutes=0.2)
    assert (result["state"], result["step"], result["busy"], result["late"]) == ("waiting", 1, True, False)
    assert 0 < result["percent"] <= 5
    # A report about an older update is not about this one.
    stale = progress.staging_progress(NEW, OLD, report(9, "done", target=OLD), asked_minutes=1)
    assert stale["state"] == "waiting" and stale["total"] == 0


def test_waiting_too_long_is_said_and_the_page_stops_asking_after_an_hour():
    late = progress.staging_progress(NEW, OLD, None, asked_minutes=progress.LATE_MINUTES + 1)
    assert late["state"] == "waiting" and late["late"] and late["busy"]
    quiet = progress.staging_progress(NEW, OLD, None, asked_minutes=progress.QUIET_MINUTES + 1)
    assert quiet["state"] == "waiting" and quiet["late"] and not quiet["busy"]


def test_each_step_of_the_practice_computer_is_one_step_further():
    """Four spaces: download 1, copy 2, spaces 3-6, start 7, template 8, done 9. The console's wait comes first."""
    seen = []
    for step, code, slug in [(1, "download", None), (2, "copy", None), (3, "space", "cabinet-a"), (4, "space", "cabinet-b"),
                             (5, "space", "cabinet-c"), (6, "space", "demo-akwa"), (7, "start", None)]:
        result = progress.staging_progress(NEW, OLD, report(step, code, slug=slug), asked_minutes=3, report_minutes=0.1)
        assert result["state"] == "running" and result["busy"] and not result["late"]
        assert (result["step"], result["total"], result["code"], result["slug"]) == (step + 1, 9, code, slug)
        seen.append(result["percent"])
    assert seen == sorted(seen) and len(set(seen)) == len(seen) and seen[-1] < 100
    third = progress.staging_progress(NEW, OLD, report(5, "space", slug="cabinet-c"))
    assert (third["index"], third["count"]) == (3, 4)


def test_the_short_and_the_long_commit_are_the_same_release():
    result = progress.staging_progress(NEW, OLD, report(2, "copy", target=NEW[:8]))
    assert result["state"] == "running"
    result = progress.staging_progress(NEW[:12], OLD, report(2, "copy", target=NEW))
    assert result["state"] == "running"


def test_the_demo_template_is_rebuilt_after_the_spaces_run_the_new_version():
    result = progress.staging_progress(None, NEW, report(8, "template"), report_minutes=2)
    assert (result["state"], result["step"], result["total"], result["busy"]) == ("finishing", 9, 9, True)
    assert result["percent"] < 100
    done = progress.staging_progress(None, NEW, report(9, "done"), report_minutes=0)
    assert (done["state"], done["busy"], done["percent"], done["step"]) == ("idle", False, 0, 0)
    # A template step never followed by "done" does not keep the page asking for ever.
    assert progress.staging_progress(None, NEW, report(8, "template"), report_minutes=progress.QUIET_MINUTES + 5)["state"] == "idle"


def test_a_failure_is_a_failure_with_its_reason_and_the_page_stops_asking():
    failed = progress.staging_progress(NEW, OLD, report(4, "space", slug="cabinet-b", failed=True, reason="space_update"))
    assert (failed["state"], failed["reason"], failed["slug"], failed["busy"]) == ("failed", "space_update", "cabinet-b", False)
    assert failed["step"] == 5 and failed["total"] == 9
    refused = progress.staging_progress(NEW, OLD, report(1, "download", failed=True, reason="digest"))
    assert (refused["state"], refused["reason"]) == ("failed", "digest")
    unnamed = progress.staging_progress(NEW, OLD, report(1, "download", failed=True, reason=None))
    assert unnamed["reason"] == "other"


def test_a_template_that_was_not_rebuilt_is_a_warning_not_a_failure():
    result = progress.staging_progress(None, NEW, report(8, "template", failed=True, reason="template"))
    assert (result["state"], result["reason"], result["busy"]) == ("warning", "template", False)


def test_a_failure_of_another_release_is_forgotten_once_a_new_one_is_asked():
    newer = "1111111111112222222222223333333333334444"
    result = progress.staging_progress(newer, OLD, report(4, "space", failed=True, reason="space_update"), asked_minutes=0)
    assert result["state"] == "waiting" and result["reason"] is None


def test_no_news_for_a_long_time_is_said():
    late = progress.staging_progress(NEW, OLD, report(3, "space", slug="cabinet-a"), report_minutes=progress.LATE_MINUTES + 1)
    assert late["state"] == "running" and late["late"] and late["busy"]
    quiet = progress.staging_progress(NEW, OLD, report(3, "space", slug="cabinet-a"), report_minutes=progress.QUIET_MINUTES + 1)
    assert quiet["late"] and not quiet["busy"]


def test_odd_figures_never_break_the_bar():
    result = progress.staging_progress(NEW, OLD, report(1, "download", total=1))
    assert result["step"] <= result["total"] and 0 <= result["percent"] <= 100
    result = progress.staging_progress(NEW, OLD, report(999, "space", total=999, slug="x1"))
    assert result["step"] == result["total"] == 999 and result["percent"] <= 100


# ---------------------------------------------------------------------------- production


def lines(*states):
    return [{"firm": f"Cabinet {index}", "state": state} for index, state in enumerate(states, 1)]


def test_no_rollout_is_idle():
    assert progress.production_progress(None, [])["state"] == "idle"
    assert progress.production_progress("draft", lines("pending"))["state"] == "idle"


def test_a_running_rollout_counts_the_firms_and_names_the_one_updating():
    result = progress.production_progress("running", lines("healthy", "requested", "pending", "pending"))
    assert (result["state"], result["done"], result["total"], result["percent"], result["busy"]) == ("running", 1, 4, 25, True)
    assert result["now"] == ["Cabinet 2"] and result["waiting"] == 2 and result["bad"] == []
    first = progress.production_progress("running", lines("requested", "pending"))
    assert (first["done"], first["percent"], first["now"]) == (0, 0, ["Cabinet 1"])


def test_a_stopped_rollout_names_the_firm_that_failed_and_counts_the_untouched():
    result = progress.production_progress("stopped", lines("healthy", "rolled_back", "cancelled", "cancelled"))
    assert (result["state"], result["busy"], result["done"], result["total"]) == ("stopped", False, 1, 4)
    assert result["bad"] == [("Cabinet 2", "rolled_back")] and result["untouched"] == 2
    for bad in ("failed", "timed_out"):
        assert progress.production_progress("stopped", lines(bad))["bad"] == [("Cabinet 1", bad)]


def test_a_finished_rollout_is_idle_and_complete():
    result = progress.production_progress("done", lines("healthy", "healthy"))
    assert (result["state"], result["busy"], result["done"], result["total"], result["percent"]) == ("idle", False, 2, 2, 100)
