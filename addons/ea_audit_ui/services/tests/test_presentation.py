import csv
from datetime import date
from pathlib import Path

from ..presentation import fmt_date, initials, percent, phase_deadline, report_due, short_name
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
    assert phase_label("planning") == "Strategy & risks"
    assert phase_label("archived") == "Archived"
    assert GROUP_BY_ID["e4"]["short"] == "Substantive procedures"
