"""An article number of the AUSCGIE or AUDCIF stays marked "(à valider)" until the firm's
jurist has validated the workbook. The mark is added here, once, on everything a generated
document or a deadline basis says; the company's ``ea_articles_validated`` switch lifts it
for the whole firm."""
import re

MARK = "(à valider)"

_NUMBER = r"\d+(?:-\d+)?"
_ARTICLE = re.compile(
    r"\b(?:arts?\.|articles?)\s+" + _NUMBER
    + r"(?:\s*(?:et|à|/|,|–|-)\s*" + _NUMBER + r")*(?:\s+et\s+s\.)?(?:\s+al\.\s*\d+)?",
    re.IGNORECASE,
)


def mark_articles(text, validated=False):
    """Add the mark after each article reference that does not already carry it."""
    if not text or validated:
        return text

    def repl(match):
        tail = match.string[match.end():match.end() + 13]
        return match.group(0) if tail.lstrip().startswith(MARK) else "%s %s" % (match.group(0), MARK)

    return _ARTICLE.sub(repl, text)


def unmarked_articles(text):
    """The references left without the mark: what the tests assert is empty."""
    return [
        m.group(0) for m in _ARTICLE.finditer(text or "")
        if not m.string[m.end():m.end() + 13].lstrip().startswith(MARK)
    ]
