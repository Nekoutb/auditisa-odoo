"""lib/search-methodology.ts (F079): the static half of the search. "ISA 700", "DSF", "505" live in
the paper definitions, where a search on titles cannot see them."""
import re
import unicodedata

_NOT_WORD = re.compile(r"[^a-z0-9.¶]+")
SNIPPET = 180


def normalize(text):
    """Lower-case, no accents, "ISA 260/265" splits into ISA, 260 and 265."""
    plain = unicodedata.normalize("NFD", text or "")
    plain = "".join(char for char in plain if not unicodedata.combining(char)).lower()
    return _NOT_WORD.sub(" ", plain).strip()


def methodology_entry(code, title, definition, fr):
    """One paper as the search reads it: its standards, requirements, procedures and questions."""
    pieces = [definition.get("std") or ""] + list(definition.get("reqFr" if fr else "reqEn") or [])
    for section in definition.get("sections") or []:
        if section.get("kind") == "proc":
            for proc in section.get("procs") or []:
                pieces += [proc.get("fr" if fr else "en") or "", proc.get("srcFr" if fr else "srcEn") or ""]
        elif section.get("kind") == "yn":
            pieces += [item.get("fr" if fr else "en") or "" for item in section.get("items") or []]
    pieces = tuple(piece for piece in pieces if piece)
    return {"code": code, "title": title, "pieces": pieces, "text": normalize(" ".join((code, title) + pieces))}


def methodology_matches(query, entries):
    """{code: snippet}: every term of the query present as a whole word, in any order."""
    terms = [term for term in normalize(query).split(" ") if len(term) >= 2]
    if not terms:
        return {}
    matchers = [re.compile(r"(?:^|[^a-z0-9])%s(?:$|[^a-z0-9])" % re.escape(term)) for term in terms]
    out = {}
    for entry in entries:
        if not all(matcher.search(entry["text"]) for matcher in matchers):
            continue
        piece = next(
            (piece for piece in entry["pieces"] if all(matcher.search(normalize(piece)) for matcher in matchers)),
            entry["pieces"][0] if entry["pieces"] else "",
        )
        out[entry["code"]] = "%s…" % piece[:SNIPPET - 2] if len(piece) > SNIPPET else piece
    return out


def answer_snippet(value, term):
    """The words around the match, not the first hundred characters of an answer."""
    text = (value or "").strip()
    at = text.lower().find(term.lower())
    if at < 0 or len(text) <= SNIPPET:
        return text[:SNIPPET]
    start = max(0, at - 60)
    return "%s%s…" % ("…" if start else "", text[start:start + SNIPPET])
