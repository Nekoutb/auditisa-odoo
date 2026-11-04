"""lib/leadsheets.ts: only the grouping-rule resolution. The rest is queries."""


def resolve_section(account_code, overrides, global_rules):
    """Longest prefix wins, then the higher priority; client overrides beat the global rules."""

    def match(rules):
        best = None
        for rule in rules:
            hit = account_code == rule["prefix"] if rule["exact"] else account_code.startswith(rule["prefix"])
            if not hit:
                continue
            if (
                best is None
                or len(rule["prefix"]) > len(best["prefix"])
                or (len(rule["prefix"]) == len(best["prefix"]) and rule["priority"] > best["priority"])
            ):
                best = rule
        return best["sectionCode"] if best else None

    found = match(overrides)
    return found if found is not None else match(global_rules)
