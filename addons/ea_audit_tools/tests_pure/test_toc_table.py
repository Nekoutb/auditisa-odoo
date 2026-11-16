"""The owner's sample table for tests of controls (ruling of 2026-11-16) and the reading of the
frequencies typed before the fixed list existed."""
import pytest

from services import sampling_params, toc_sampling
from services.toc_sampling import effective_frequency, frequency_code_from_text, frequency_choice_sizes, toc_suggested


def size(frequency, population=None, reliance="normal", sole=False, control_type="manual"):
    found = toc_suggested(control_type, frequency, population, sole, False, reliance)
    return found.get("size") if found else None


@pytest.mark.parametrize("code,normal,heavy", [
    ("annually", 1, 1), ("semi_annually", 1, 2), ("quarterly", 2, 2), ("monthly", 2, 4),
    ("twice_monthly", 3, 6), ("weekly", 5, 10),
])
def test_the_periodic_lines(code, normal, heavy):
    assert size(code) == normal
    assert size(code, reliance="heavy") == heavy
    assert frequency_choice_sizes(code, False) == "%d · %d" % (normal, heavy)


@pytest.mark.parametrize("code", ["daily", "multiple_daily", "event"])
def test_the_occurrence_lines(code):
    assert toc_suggested("manual", code, None, False, False) == {"needPopulation": True}
    assert size(code, 300) == 25
    assert size(code, 300, reliance="heavy") == 40
    assert size(code, 300, sole=True) == 60
    assert size(code, 300, reliance="heavy", sole=True) == 60
    assert size(code, 250) == 25  # 10 % of 250
    assert size(code, 120) == 12
    assert size(code, 50) == 5
    assert size(code, 49) == 5
    assert size(code, 5) == 5
    assert size(code, 4) == 4
    assert frequency_choice_sizes(code, False) == "count needed"


def test_automated_is_one_and_other_has_no_suggestion():
    assert size("monthly", control_type="automated") == 1
    assert size(None, control_type="automated") == 1
    assert toc_suggested("manual", "other", None, False, False) is None
    assert frequency_choice_sizes("other", True) == "motif requis"
    assert toc_suggested("manual", None, None, False, False) is None


def test_an_it_dependent_manual_control_follows_the_table():
    assert size("monthly", control_type="it_dependent") == 2


def test_a_small_population_caps_a_periodic_size():
    assert size("weekly", 3) == 3


def test_the_a2_attribute_plan_reads_the_same_table():
    assert sampling_params.ATTRIBUTE_SAMPLE_SIZES == {"daily": 40, "weekly": 10, "monthly": 4, "quarterly": 2, "annual": 1, "automated": 1}
    assert sampling_params.attribute_plan("monthly") == {"sampleSize": 4}
    assert sampling_params.attribute_plan("monthly", "normal") == {"sampleSize": 2}
    assert sampling_params.attribute_plan("annual", "normal") == {"sampleSize": 1}
    assert sampling_params.attribute_plan("daily", "normal") == {"sampleSize": 25}
    assert sampling_params.attribute_plan("automated", "normal") == {"sampleSize": 1}
    for code, (normal, heavy) in toc_sampling.FREQUENCY_SIZES.items():
        assert size(code) == normal and size(code, reliance="heavy") == heavy


@pytest.mark.parametrize("text,code", [
    ("Monthly", "monthly"), ("mensuel", "monthly"), ("Mensuelle", "monthly"), ("chaque mois", "monthly"),
    ("Quotidien", "daily"), ("journalier", "daily"), ("daily", "daily"), ("chaque jour", "daily"),
    ("Hebdomadaire", "weekly"), ("weekly", "weekly"),
    ("Trimestriel", "quarterly"), ("quarterly", "quarterly"),
    ("Semestriel", "semi_annually"), ("Semi-annually", "semi_annually"),
    ("Annuel", "annually"), ("annually", "annually"), ("yearly", "annually"),
    ("bimensuel", "twice_monthly"), ("twice a month", "twice_monthly"),
    ("Many times a day", "multiple_daily"), ("plusieurs fois par jour", "multiple_daily"),
    ("à chaque facture", "event"), ("Each order", "event"), ("per transaction", "event"),
    ("monthly", "monthly"), ("twice_monthly", "twice_monthly"),
])
def test_the_legacy_text_parser(text, code):
    assert frequency_code_from_text(text) == code


@pytest.mark.parametrize("text", ["", None, "x", "AD HOC", "daily or weekly", "biannually", "preventive check", "mensuel ou trimestriel"])
def test_unclear_text_maps_to_nothing(text):
    assert frequency_code_from_text(text) is None


def test_a_stored_code_wins_over_the_text():
    assert effective_frequency("weekly", "mensuel") == "weekly"
    assert effective_frequency(None, "mensuel") == "monthly"
    assert effective_frequency(False, "") is None


def test_the_legacy_text_gets_the_new_table():
    assert size("Mensuel", reliance="heavy") == 4
    assert size("Semestriel") == 1
