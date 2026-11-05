from markupsafe import Markup


from ..models.tool_record import grouped


def is_french_env(env):
    return (env.lang or env.context.get("lang") or "").startswith("fr")


def preview_html(preview, env):
    """The confirm step: the classes the file resolves to, and its first rows."""
    classes = Markup("").join(
        Markup("<tr><td>{p}</td><td class='text-end'>{n}</td><td class='text-end'>{t}</td><td>{i}</td></tr>").format(
            p=entry["prefix"], n=entry["accountCount"],
            t=grouped(entry["closingTotal"], env.lang),
            i=entry["leadIndex"] or env._("Unmapped"),
        )
        for entry in preview["classes"]
    )
    sample = Markup("").join(
        Markup("<tr><td>{a}</td><td>{l}</td><td class='text-end'>{o}</td><td class='text-end'>{c}</td></tr>").format(
            a=row["account"], l=row["label"] or "",
            o=grouped(row["opening"], env.lang),
            c=grouped(row["closing"], env.lang),
        )
        for row in preview["sample"]
    )
    return Markup(
        "<p>{rows}</p>"
        "<table class='table table-sm'><thead><tr><th>{prefix}</th><th class='text-end'>{accounts}</th>"
        "<th class='text-end'>{closing}</th><th>{index}</th></tr></thead><tbody>{classes}</tbody></table>"
        "<table class='table table-sm'><thead><tr><th>{account}</th><th>{label}</th><th class='text-end'>{opening}</th>"
        "<th class='text-end'>{closing}</th></tr></thead><tbody>{sample}</tbody></table>"
    ).format(
        rows=env._("%(count)s rows read", count=preview["rowCount"]),
        prefix=env._("Class"), accounts=env._("Accounts"), closing=env._("Closing"), index=env._("Lead index"),
        classes=classes, account=env._("Account"), label=env._("Description"), opening=env._("Opening"), sample=sample,
    )
