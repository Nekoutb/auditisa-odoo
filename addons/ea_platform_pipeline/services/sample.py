"""What the Status tab shows before the collector is connected: SAMPLE DATA, and said so on every card. Pure."""

from datetime import timedelta

from . import collected


def _commit(sha, author, at):
    return {"sha": sha, "author": author, "at": at}


def sample_state(now):
    """The same shape as a real reading, with made-up commits, marked as a sample."""
    def at(hours):
        return (now - timedelta(hours=hours)).strftime("%Y-%m-%dT%H:%M:%SZ")

    raw = {
        "schema": 1,
        "generated": at(0),
        "next": {
            "github": "ok",
            "branches": {"dev": _commit("a1" * 20, "Sample author", at(20)), "main": _commit("b2" * 20, "Sample author", at(400))},
            "running": {"staging": _commit("a1" * 20, "Sample author", at(20)), "production": _commit("b2" * 20, "Sample author", at(400))},
            "ahead": {"development_over_staging": 0, "staging_over_production": 12, "main_over_production": 0},
            "sites": {"staging": {"up": True, "started_at": at(19)}, "production": {"up": True, "started_at": at(300)}},
            "figures": {
                "staging": {"deploys": [{"sha": "a1" * 20, "at": at(19)}], "backups": [{"at": at(6), "size": "9.8 MB"}], "migrations": 120, "pending": 0},
                "production": {"deploys": [{"sha": "b2" * 20, "at": at(400)}], "backups": [{"at": at(6), "size": "10.1 MB"}], "migrations": 85, "pending": 0},
            },
        },
        "odoo": {
            "github": "ok",
            "branches": {"dev": _commit("c3" * 20, "Sample author", at(2)), "main": _commit("d4" * 20, "Sample author", at(90))},
            "running": {"staging": _commit("c3" * 20, "Sample author", at(2))},
            "ahead": {"development_over_staging": 0, "staging_over_main": 7},
            "sites": {"staging": {"up": True, "mail_off": True, "band_on": True}},
            "log": {
                "dev": [{"sha": "c3" * 20, "author": "Sample author", "at": at(2), "subject": "Sample commit: not a real change"},
                        {"sha": "e5" * 20, "author": "Sample author", "at": at(30), "subject": "Sample commit: not a real change"}],
                "main": [{"sha": "d4" * 20, "author": "Sample author", "at": at(90), "subject": "Sample commit: not a real change"}],
            },
        },
    }
    import json

    state = collected.read_state(json.dumps(raw).encode(), now)
    state["sample"] = True
    return state
