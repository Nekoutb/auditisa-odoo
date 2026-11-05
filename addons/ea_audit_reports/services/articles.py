"""An article number of the AUSCGIE or AUDCIF stays marked "(à valider)", or "(to validate)" in
English, until the firm's
jurist has validated the workbook. The mark is added here, once, on everything a generated
document or a deadline basis says; the company's ``ea_articles_validated`` switch lifts it
for the whole firm."""
import re

MARK_FR = "(à valider)"
MARK = MARK_FR
MARK_EN = "(to validate)"

_NUMBER = r"\d+(?:-\d+)?"
_ARTICLE = re.compile(
    r"\b(?:arts?\.|articles?)\s+" + _NUMBER
    + r"(?:\s*(?:et|and|to|à|/|,|–|-)\s*" + _NUMBER + r")*(?:\s+(?:et\s+s|ff)\.)?(?:\s+(?:al|para)\.\s*\d+)?",  # i18n: input
    re.IGNORECASE,
)


def mark_articles(text, validated=False, fr=True):
    """Add the mark after each article reference that does not already carry it."""
    if not text or validated:
        return text
    mark = MARK if fr else MARK_EN

    def repl(match):
        tail = match.string[match.end():match.end() + 16]
        return match.group(0) if tail.lstrip().startswith((MARK, MARK_EN)) else "%s %s" % (match.group(0), mark)

    return _ARTICLE.sub(repl, text)


def unmarked_articles(text):
    """The references left without the mark: what the tests assert is empty."""
    return [
        m.group(0) for m in _ARTICLE.finditer(text or "")
        if not m.string[m.end():m.end() + 16].lstrip().startswith((MARK, MARK_EN))
    ]
