"""How much of the general ledger in use reaches each lead index (owner's request of 2026-11-15).

For each index: the number of distinct journal entries with at least one line on an account of
the index, and the number of distinct people who recorded or approved those lines. The account
goes to its index exactly as the trial balance's does (the client's prefixes first, then the
SYSCOHADA map): the caller passes that resolver.
"""
from .dataset_mapping import je_identity, je_key_columns
from .gl_line import _column, safe_text


def people_columns(mapping):
    """(preparer known, reviewer known): whether the import matched a column for each.

    Preparers come from "Prepared by" or "Recorded by" (the projection's preparer); reviewers
    from "Approved by" and "Reviewer" together."""
    mapping = mapping or {}
    preparer = bool(_column(mapping, "preparedBy") or _column(mapping, "recordedBy"))
    reviewer = bool(_column(mapping, "approvedBy") or _column(mapping, "reviewer"))
    return preparer, reviewer


def _person(value):
    text = (value or "").strip() if isinstance(value, str) else ""
    return text or None


class IndexActivity:
    """Fed line by line (a ledger can hold some 200,000 lines), read once at the end."""

    def __init__(self, index_of):
        self._index_of = index_of
        self._index_cache = {}
        self._entries = {}
        self._preparers = {}
        self._reviewers = {}

    def add(self, account, je_number, preparer=None, reviewers=()):
        if not account or not je_number:
            return
        index = self._index_cache.get(account, False)
        if index is False:
            # a projected account keeps the quote that neutralises a formula: the TB has none
            index = self._index_of(account[1:] if account.startswith("'") else account)
            self._index_cache[account] = index
        if not index:
            return
        self._entries.setdefault(index, set()).add(je_number)
        person = _person(preparer)
        if person:
            self._preparers.setdefault(index, set()).add(person)
        for value in reviewers:
            person = _person(value)
            if person:
                self._reviewers.setdefault(index, set()).add(person)

    def result(self):
        """{index: {"entries", "preparers", "reviewers"}} for every index the ledger reaches."""
        return {
            index: {
                "entries": len(entries),
                "preparers": len(self._preparers.get(index, ())),
                "reviewers": len(self._reviewers.get(index, ())),
            }
            for index, entries in self._entries.items()
        }


def line_reader(mapping):
    """row data -> (account, je_number, preparer, reviewer, approver), or None when the mapping
    cannot say which account or entry a row belongs to. The same columns and the same entry
    identity as the projection (gl_line.projector), without its dates and amounts."""
    mapping = mapping or {}
    account_col = _column(mapping, "account")
    je_col = _column(mapping, "jeNumber")
    key_columns = je_key_columns(mapping)
    if not account_col or (not je_col and not key_columns):
        return None
    preparer_col = _column(mapping, "preparedBy") or _column(mapping, "recordedBy")
    reviewer_col, approver_col = _column(mapping, "reviewer"), _column(mapping, "approvedBy")

    def read(data):
        data = data or {}
        return (
            safe_text(data.get(account_col)),
            je_identity(data, key_columns, je_col, safe_text),
            safe_text(data.get(preparer_col)) if preparer_col else None,
            safe_text(data.get(reviewer_col)) if reviewer_col else None,
            safe_text(data.get(approver_col)) if approver_col else None,
        )

    return read


def index_activity(lines, index_of):
    """``lines``: (account, je_number, preparer, reviewer, approver) tuples."""
    activity = IndexActivity(index_of)
    for account, je_number, preparer, reviewer, approver in lines:
        activity.add(account, je_number, preparer, (reviewer, approver))
    return activity.result()
