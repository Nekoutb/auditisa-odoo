"""Work allocation (owner's mock-up of 2026-11-18), the pure half: the rule of a task in plain words,
the check of one row, and "Suggest by role". Read without Odoo.

A row is a dict: id, min_preparer, min_reviewer, preparer (user id or None), reviewer (user id or
None) and, where the task has one, assignee. A member is a dict: user_id and role (a rung of the
ladder: staff ... partner). The engagement quality reviewer is never a member here.
"""
from .signoff_rules import team_rank


def _lt(text):
    """Marks an English source for fr.po; the model layer translates it with env._."""
    return text


#: How a role reads inside a sentence: "Prepared by a senior or above".
ROLE_WORDS = {
    "staff": _lt("staff member"),
    "senior": _lt("senior"),
    "manager": _lt("manager"),
    "senior_manager": _lt("senior manager"),
    "director": _lt("director"),
    "partner": _lt("partner"),
}
PREPARED_BY = _lt("Prepared by a %(role)s or above")
REVIEWED_BY = _lt("reviewed by a %(role)s or above")
PARTNER_APPROVES = _lt("partner approves")

#: The four groups of the table, in the order of the audit.
PHASES = ("planning", "strategy", "execution", "conclusion")

# What a row's check can say. A refusal stops the save; a warning does not (owner's ruling: signing
# still follows the sign-off policy, which refuses a signature below the minimum).
SAME_PERSON = "same-person"
BELOW_MINIMUM = "below-minimum"


def _same(text):
    return text


def rule_text(rule, translate=_same):
    """The task's rule from the sign-off policy, in plain words. ``rule`` is what
    effective_task_rule returns. The reviewer part is left out when only a partner may review and
    the partner approves anyway."""
    parts = [translate(PREPARED_BY) % {"role": translate(ROLE_WORDS[rule["min_preparer"]])}]
    if not (rule["partner_required"] and rule["min_reviewer"] == "partner"):
        parts.append(translate(REVIEWED_BY) % {"role": translate(ROLE_WORDS[rule["min_reviewer"]])})
    if rule["partner_required"]:
        parts.append(translate(PARTNER_APPROVES))
    return "; ".join(parts)


def phase_of_code(code):
    """The table's group of a task: P planning, S strategy and risks, E execution, the rest conclusion."""
    first = (code or "")[:1]
    return {"P": "planning", "S": "strategy", "E": "execution"}.get(first, "conclusion")


def check_row(row, roles):
    """What is wrong with one row, as a list of (box, kind, blocking, role). ``box`` is
    "preparer" or "reviewer"; ``roles`` maps a user id to their role on the team.

    The reviewer who is also the preparer (or the task's assignee) is refused: nobody reviews their
    own work (ISA 220 (Revised) para. 29, F001). A person below the task's minimum is a warning."""
    problems = []
    preparer, reviewer = row.get("preparer"), row.get("reviewer")
    if reviewer and reviewer in (preparer, row.get("assignee")):
        problems.append(("reviewer", SAME_PERSON, True, None))
    if preparer and team_rank(roles.get(preparer)) < team_rank(row["min_preparer"]):
        problems.append(("preparer", BELOW_MINIMUM, False, row["min_preparer"]))
    if reviewer and team_rank(roles.get(reviewer)) < team_rank(row["min_reviewer"]):
        problems.append(("reviewer", BELOW_MINIMUM, False, row["min_reviewer"]))
    return problems


def refused(rows, roles):
    """The ids of the rows that cannot be saved."""
    return [row["id"] for row in rows if any(blocking for _box, _kind, blocking, _role in check_row(row, roles))]


def _pick(candidates, load):
    """The least loaded of the most junior candidates; the order given breaks a tie."""
    if not candidates:
        return None
    lowest = min(team_rank(member["role"]) for member in candidates)
    level = [member for member in candidates if team_rank(member["role"]) == lowest]
    return min(level, key=lambda member: load[member["user_id"]])["user_id"]


def suggest(rows, members):
    """"Suggest by role": fills only the empty boxes. The preparer is the most junior member the
    policy allows; the reviewer the next level up who is not the preparer (the same level when
    nobody is above); among equals, the one with the fewest tasks, so the work spreads evenly.
    Nobody below the minimum is suggested: a box with no one allowed stays empty.

    Returns {row id: {"preparer": user id, "reviewer": user id}}, only the boxes it filled."""
    roles = {member["user_id"]: member["role"] for member in members}
    prep_load = {member["user_id"]: 0 for member in members}
    review_load = {member["user_id"]: 0 for member in members}
    for row in rows:
        if row.get("preparer") in prep_load:
            prep_load[row["preparer"]] += 1
        if row.get("reviewer") in review_load:
            review_load[row["reviewer"]] += 1
    out = {}
    for row in rows:
        filled = {}
        preparer = row.get("preparer")
        if not preparer:
            preparer = _pick(
                [m for m in members if team_rank(m["role"]) >= team_rank(row["min_preparer"])
                 and m["user_id"] not in (row.get("reviewer"),)],
                prep_load,
            )
            if preparer:
                filled["preparer"] = preparer
                prep_load[preparer] += 1
        if not row.get("reviewer"):
            not_self = [
                m for m in members
                if m["user_id"] not in (preparer, row.get("assignee"))
                and team_rank(m["role"]) >= team_rank(row["min_reviewer"])
            ]
            above = [m for m in not_self if preparer and team_rank(m["role"]) > team_rank(roles.get(preparer))]
            reviewer = _pick(above or not_self, review_load)
            if reviewer:
                filled["reviewer"] = reviewer
                review_load[reviewer] += 1
        if filled:
            out[row["id"]] = filled
    return out
