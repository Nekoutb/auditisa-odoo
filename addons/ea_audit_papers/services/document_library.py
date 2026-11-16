"""The engagement's own documents, offered when a file is attached somewhere else in the same file.

Pure: rows are plain dicts read by the model (ea.audit.engagement.ea_document_library), so the
search can be tested without Odoo. A row reads
{"id", "name", "type", "code", "task", "by", "date", "version", "ext", "item_id"}.
"""

import unicodedata

#: The fields a search looks in: name, type, task code and title, uploader, date.
SEARCHED = ("name", "type", "code", "task", "by", "date")


def _fold(text):
    """Lower case without accents: "Relevé" is found by "releve"."""
    text = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in text if not unicodedata.combining(ch)).lower()


def latest_versions(rows):
    """One row per document: the highest version of each (task, name) chain."""
    best = {}
    for row in rows:
        key = (row.get("item_id"), row.get("name"))
        if key not in best or (row.get("version") or 0) > (best[key].get("version") or 0):
            best[key] = row
    return list(best.values())


def search_rows(rows, search=None):
    """The rows matching every word of the search, in any of the searched fields."""
    words = [_fold(word) for word in (search or "").split() if word.strip()]
    if not words:
        return list(rows)
    found = []
    for row in rows:
        haystack = " ".join(_fold(row.get(field)) for field in SEARCHED)
        if all(word in haystack for word in words):
            found.append(row)
    return found


def library(rows, search=None, limit=200):
    """What the picker lists: latest versions, matching the search, by task code then name."""
    rows = search_rows(latest_versions(rows), search)
    rows.sort(key=lambda row: (str(row.get("code") or ""), _fold(row.get("name"))))
    return rows[:limit]
