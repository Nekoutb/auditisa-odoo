"""Roll forward to next year (owner's mock-up and rulings of 2026-11-16): the decisions of the
wizard that need no database. Standard library only, so the pure tests load this file directly.
"""

# What the wizard can carry, in the order the trail lists it.
ROLLFORWARD_KEYS = (
    "scope", "materiality", "scots", "risks", "procedures", "significance", "comparatives", "answers", "evidence",
)
# The wizard's boxes, ticked by default, and the key each one gives.
CARRY_FIELDS = tuple(("carry_%s" % key, key) for key in ROLLFORWARD_KEYS)

NOTE_LEFT = "left"
NOTE_DECLINED = "declined"


def carry_keys(ticked):
    """The keys of the ticked boxes ({field: bool}), in trail order."""
    return [key for field, key in CARRY_FIELDS if ticked.get(field)]


def uses_last_year_tasks(carry, approach):
    """Same as last year: last year's level and tasks. Change, or the scope not carried: the
    questionnaire decides the tasks of the new file."""
    return "scope" in carry and (approach or "same") == "same"


def evidence_to_copy(rows, carry):
    """The files to copy: the latest live version of each name on each task, all of them (no
    permanent-file restriction, owner 2026-11-16). rows: dicts with id, item, name, version, code,
    deleted. Sorted by task code, then name."""
    if "evidence" not in carry:
        return []
    latest = {}
    for row in rows:
        if row.get("deleted"):
            continue
        key = (row["item"], row["name"])
        kept = latest.get(key)
        if kept is None or (row["version"], row["id"]) > (kept["version"], kept["id"]):
            latest[key] = row
    return sorted(latest.values(), key=lambda r: (r["code"] or "", r["name"]))


def team_lines(members):
    """Last year's team as the wizard lists it, the partner's seat apart (the partner is chosen on
    its own). members: dicts with email, name, role, state, active (still a member of the firm).
    Those who left or declined are listed unticked, with why."""
    lines = []
    for member in members:
        if member["role"] == "partner":
            continue
        note = NOTE_LEFT if not member["active"] else NOTE_DECLINED if member["state"] == "declined" else False
        lines.append({
            "invite": not note, "email": member["email"], "name": member["name"], "team_role": member["role"],
            "note": note,
        })
    return lines


def invitations(lines, seated_emails):
    """The invitations to send: the ticked lines with an email, once each, leaving out whoever
    already sits on the new team (the partner, the person rolling forward)."""
    seated = {email.strip().lower() for email in seated_emails if email}
    out = []
    for line in lines:
        email = (line.get("email") or "").strip().lower()
        if not line.get("invite") or not email or email in seated:
            continue
        seated.add(email)
        out.append(dict(line, email=email))
    return out
