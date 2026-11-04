"""Port of the mapping of lib/tool-fed-papers.ts (F004)."""
import re

_LEAD_SCHEDULE_PAPER = re.compile(r"^E4\.([1-9]|[12][0-9]|3[0-4])$")


def tool_output_missing_code(output):
    return "tool-output-missing-%s" % output


def tool_outputs_for(code):
    """What each tool-fed paper needs, in the order it is checked."""
    if code == "P6.1":
        return ("materiality",)
    if code == "P6.2":
        return ("tb", "materiality")
    if code == "C1.1":
        return ("tb", "materiality", "sad")
    if _LEAD_SCHEDULE_PAPER.match(code):
        return ("tb",)
    return ()


def is_tool_fed_paper(code):
    return bool(tool_outputs_for(code))
