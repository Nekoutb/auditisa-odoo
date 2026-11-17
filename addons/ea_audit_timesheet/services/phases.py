"""The four sections of the top bar are the phases a budget is set against."""
BUDGET_PHASES = [
    ("acceptance", "Planning"),
    ("strategy", "Strategy and risks"),
    ("execution", "Execution"),
    ("conclusion", "Conclusion"),
]
_FROM_ENGAGEMENT = {
    "acceptance": "acceptance",
    "planning": "strategy",
    "execution": "execution",
    "conclusion": "conclusion",
    "archived": "conclusion",
}


def budget_phase(engagement_phase):
    return _FROM_ENGAGEMENT.get(engagement_phase, "acceptance")
