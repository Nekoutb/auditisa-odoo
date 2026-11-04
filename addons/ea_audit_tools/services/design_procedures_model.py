"""lib/design-procedures-model.ts: the nature and timing sets a procedure may use."""
import re

from .assertions import ASSERTIONS as PLATFORM_ASSERTIONS

NATURE_OPTIONS = [
    {"value": "combined", "en": "SAPs + tests of details", "fr": "Analytiques + tests de détail"},
    {"value": "tod_led", "en": "Tests of details led", "fr": "Tests de détail en priorité"},
    {"value": "sap_led", "en": "Analytics led, data tested", "fr": "Analytiques en priorité, données testées"},
]

TIMING_OPTIONS = [
    {"value": "period_end", "en": "At / near period end", "fr": "À / près de la clôture"},
    {"value": "interim_3", "en": "Interim ≤ 3 months + rollforward", "fr": "Intercalaire ≤ 3 mois + liaison"},
    {"value": "interim_6", "en": "Interim ≤ 6 months + rollforward", "fr": "Intercalaire ≤ 6 mois + liaison"},
]

NATURE_VALUES = [o["value"] for o in NATURE_OPTIONS]
TIMING_VALUES = [o["value"] for o in TIMING_OPTIONS]

#: Caps on the stored ``osp_list``: a design, not a document store.
OSP_MAX = 20
OSP_TEXT_MAX = 800
OSP_EXTENT_MAX = 400
OSP_ID = re.compile(r"[A-Za-z0-9_-]{1,40}\Z")
#: The design set is the platform's six assertions, RO included (F041).
ASSERTIONS = list(PLATFORM_ASSERTIONS)


def timing_allowed(level):
    """The widest interim window the CRA level permits (ISA 330 A11-A12)."""
    if level == "minimal":
        return ["period_end", "interim_3", "interim_6"]
    if level == "low":
        return ["period_end", "interim_3"]
    return ["period_end"]


def cra_level_of(tod):
    """The CRA level of a tod value: the significant-risk suffix does not change the window."""
    return tod.replace("_sr", "", 1)
