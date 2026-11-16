"""The subsequent period: uploads of the year after the one audited (the next-year general ledger,
and its receivables, payables and inventory listings). They serve the cut-off procedures and the
search for unrecorded liabilities; they never stand in for the year audited."""
import re

from ._js import _days_from_civil
from .gl_line import projector

SUBSEQUENT = "subsequent"
# below this many days after the year end, the next-year ledger is too short for cut-off work
SUBSEQUENT_MIN_DAYS = 30
# the kinds that may be uploaded for the next year
SUBSEQUENT_KINDS = ("journal_entries", "ar_open_items", "ap_open_items", "inventory_listing")
# what the year audited reads: every timing but the next year's
CURRENT_YEAR_TIMINGS = ("pre_audit", "post_audit", "prior_year")


def empty_coverage():
    return {"first_date": None, "last_date": None, "days_after_year_end": None, "entries": 0}


_ISO_DAY = re.compile(r"^(\d{4})-(\d{2})-(\d{2})")


def _iso(value):
    """A date (or ISO text) as yyyy-mm-dd, or None."""
    if value is None:
        return None
    text = value.isoformat() if hasattr(value, "isoformat") else str(value)
    return text[:10] if _ISO_DAY.match(text) else None


def _day_number(iso):
    year, month, day = _ISO_DAY.match(iso).groups()
    return _days_from_civil(int(year), int(month), int(day))


def coverage_of(first_date, last_date, entries, period_end):
    """{first_date, last_date, days_after_year_end, entries} from what the lines give."""
    first, last, end = _iso(first_date), _iso(last_date), _iso(period_end)
    return {
        "first_date": first,
        "last_date": last,
        "days_after_year_end": _day_number(last) - _day_number(end) if last and end else None,
        "entries": int(entries or 0),
    }


def ledger_coverage(rows, mapping, period_end):
    """The coverage of a ledger read from its own rows (the data of each row, as imported): the
    posting date, else the entry date, of every line that belongs to an entry."""
    project = projector(mapping)
    first = last = None
    entries = set()
    for data in rows:
        line = project(data)
        if not line:
            continue
        entries.add(line["je_number"])
        day = line["journal_date"] or line["entry_date"]
        if day:
            first = day if first is None or day < first else first
            last = day if last is None or day > last else last
    return coverage_of(first, last, len(entries), period_end)


def _dmy(iso):
    return "%s/%s/%s" % (iso[8:10], iso[5:7], iso[0:4])


def coverage_sentence(coverage, fr=False):
    """The plain sentence the upload page and the procedures show."""
    if not coverage or not coverage.get("last_date"):
        if coverage and coverage.get("entries"):
            return ("Grand livre de l'exercice suivant fourni, sans date lisible." if fr
                    else "Next-year general ledger provided, with no readable date.")
        return "Aucun grand livre de l'exercice suivant importé." if fr else "No next-year general ledger uploaded."
    days = coverage["days_after_year_end"]
    if fr:
        return "Grand livre de l'exercice suivant fourni jusqu'au %s (%d jours après la clôture)." % (_dmy(coverage["last_date"]), days)
    return "Next-year general ledger provided up to %s (%d days after year end)." % (_dmy(coverage["last_date"]), days)


def coverage_short(coverage):
    """True when a next-year ledger is there but reaches fewer than SUBSEQUENT_MIN_DAYS after the year end."""
    if not coverage or not coverage.get("entries"):
        return False
    days = coverage.get("days_after_year_end")
    return days is None or days < SUBSEQUENT_MIN_DAYS


def coverage_warning(coverage, fr=False):
    """The warning when the next-year ledger is too short for cut-off work, else None."""
    if not coverage_short(coverage):
        return None
    if fr:
        return ("Le grand livre de l'exercice suivant couvre moins de %d jours après la clôture : "
                "demandez une version plus longue pour les tests de séparation des exercices." % SUBSEQUENT_MIN_DAYS)
    return ("The next-year general ledger covers less than %d days after year end: "
            "ask for a longer one for the cut-off tests." % SUBSEQUENT_MIN_DAYS)
