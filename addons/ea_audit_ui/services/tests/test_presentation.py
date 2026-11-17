import csv
from datetime import date
from pathlib import Path

from ..presentation import (
    HOME_EMPTY,
    HOME_EMPTY_START,
    TASKS_AWAIT_PROFILE,
    TASKS_NONE_MINE,
    TASKS_NONE_OPEN,
    fmt_date,
    home_empty_lines,
    initials,
    my_tasks_empty,
    percent,
    phase_deadline,
    report_due,
    short_name,
)
from ..task_groups import GROUP_BY_ID, SECTION_OF_PHASE, TASK_GROUPS, group_of_code, phase_label

TEMPLATES = Path(__file__).parents[3] / "ea_audit_core" / "data" / "ea.audit.task.template.csv"


def test_report_is_due_six_months_after_the_period_end():
    assert report_due(date(2025, 12, 31)) == date(2026, 6, 30)
    assert report_due(date(2025, 6, 30)) == date(2025, 12, 30)


def test_phase_deadlines_follow_the_period_end_as_today():
    end = date(2025, 12, 31)
    assert phase_deadline(end, "acceptance") == date(2025, 10, 2)
    assert phase_deadline(end, "planning") == date(2025, 11, 16)
    assert phase_deadline(end, "execution") == date(2026, 3, 31)
    assert phase_deadline(end, "conclusion") == date(2026, 5, 30)
    assert phase_deadline(end, "archived") is None


def test_dates_read_day_month_year():
    assert fmt_date(date(2026, 3, 1)) == "01/03/2026"
    assert fmt_date(False) == ""


def test_names():
    assert short_name("Jean-Pierre Mbarga") == "J.-P. Mbarga"
    assert short_name("Marie Ndongo") == "M. Ndongo"
    assert short_name("Administrator") == "Administrator"
    assert initials("Jean-Pierre Mbarga") == "JM"
    assert initials("Administrator") == "AD"


def test_percent_of_nothing_is_zero():
    assert percent(0, 0) == 0
    assert percent(1, 3) == 33


def test_every_task_of_the_file_index_has_one_group():
    with TEMPLATES.open(encoding="utf-8") as handle:
        codes = [row["code"] for row in csv.DictReader(handle)]
    assert len(codes) == 118
    for code in codes:
        assert code in group_of_code(code)["members"], code
    members = [code for group in TASK_GROUPS for code in group["members"]]
    assert len(members) == len(set(members))
    assert sorted(members) == sorted(codes)


def test_phases_map_to_the_rings():
    assert SECTION_OF_PHASE["planning"] == "strategy"
    assert phase_label("acceptance") == "Planning"
    assert phase_label("planning") == "Strategy and risks"
    assert phase_label("archived") == "Archived"
    assert GROUP_BY_ID["e4"]["short"] == "Substantive procedures"


def test_an_empty_home_tells_everyone_why_and_starters_what_to_do():
    assert home_empty_lines("staff", True) == [HOME_EMPTY]
    assert home_empty_lines("senior", True) == [HOME_EMPTY]
    assert home_empty_lines("read_only", False) == [HOME_EMPTY]
    for role in ("partner", "manager", "firm_admin"):
        assert home_empty_lines(role, True) == [HOME_EMPTY, HOME_EMPTY_START]
    assert home_empty_lines(False, False) == [HOME_EMPTY]


def test_empty_my_tasks_waits_for_the_questionnaire_with_its_count():
    source, params = my_tasks_empty(True, 7, 19)
    assert source == TASKS_AWAIT_PROFILE
    assert source % params == (
        "No tasks yet: the partner has answered 7 of 19 questions in the engagement questionnaire."
    )
    # the questionnaire wins even if a task were somehow mine
    assert my_tasks_empty(True, 0, 19, any_mine=True)[0] == TASKS_AWAIT_PROFILE


def test_empty_my_tasks_after_the_questionnaire_asks_for_an_assignment():
    assert my_tasks_empty(False, 19, 19) == (TASKS_NONE_MINE, {})
    assert my_tasks_empty(False, 19, 19, any_mine=True) == (TASKS_NONE_OPEN, {})
