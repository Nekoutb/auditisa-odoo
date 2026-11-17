"""lib/tb-reasons.ts: why a trial-balance import is invalid, as lines a person can act on."""
from ._js import format_fr, js_str

COLUMN_LABEL = {
    "account": {"en": "Account", "fr": "Compte"},
    "label": {"en": "Label", "fr": "Libellé"},
    "openingDebit": {"en": "Opening debit", "fr": "Débit d'ouverture"},
    "openingCredit": {"en": "Opening credit", "fr": "Crédit d'ouverture"},
    "opening": {"en": "Opening balance", "fr": "Solde d'ouverture"},
    "debit": {"en": "Debit movement", "fr": "Mouvement débit"},
    "credit": {"en": "Credit movement", "fr": "Mouvement crédit"},
    "closingDebit": {"en": "Closing debit", "fr": "Débit de clôture"},
    "closingCredit": {"en": "Closing credit", "fr": "Crédit de clôture"},
    "closing": {"en": "Closing balance", "fr": "Solde de clôture"},
}


def tb_status_label(status, locale):
    """A stored import status in the UI language (UAT run2-B106)."""
    fr = locale == "fr"
    if status == "valid":
        return "valide" if fr else "valid"
    if status == "invalid":
        return "invalide" if fr else "invalid"
    if status == "pending":
        return "en attente" if fr else "pending"
    if not status:
        return ""
    return "avec avertissements" if fr else "with warnings"


def _list(items, limit=8):
    text = ", ".join(items[:limit])
    return text + (" … (+%d)" % (len(items) - limit) if len(items) > limit else "")


def explain_tb_summary(summary, locale):
    """[{blocking, text}]: the column that could not be read and the values in it, the
    totals that do not agree and by how much, the accounts concerned."""
    fr = locale == "fr"
    nf = format_fr
    out = []
    c = summary["checks"]
    r = summary.get("readability")

    if r:
        for u in r["unreadable"]:
            col = COLUMN_LABEL[u["column"]]["fr" if fr else "en"]
            ex = "; ".join(
                '%s %s (%s): "%s"' % ("ligne du fichier" if fr else "file row", js_str(e["row"]), e["account"], e["value"])
                for e in u["examples"]
            )
            out.append({
                "blocking": True,
                "text": (
                    "Colonne « %s » (%s) : %s valeur(s) illisible(s) en montant, lues comme 0 — %s. Mettre ces cellules au format nombre (ou 1 234,56 / 1 234.56 / (1 234)) puis réimporter."
                    if fr else
                    'Column "%s" (%s): %s value(s) not readable as an amount, read as 0 — %s. Put those cells in number format (or 1 234,56 / 1,234.56 / (1,234)) and re-upload.'
                ) % (u["header"], col, nf(u["count"]), ex),
            })
        if r["rowsWithoutAccount"] > 0:
            account = summary["mapping"].get("account")
            account = "?" if account is None else account
            out.append({
                "blocking": False,
                "text": (
                    "%s ligne(s) sans numéro de compte (colonne « %s ») ont été ignorées — totaux, sous-totaux ou lignes vides en général."
                    if fr else
                    '%s row(s) with no account number (column "%s") were skipped — usually totals, subtotals or blank lines.'
                ) % (nf(r["rowsWithoutAccount"]), account),
            })
    if not c["balanced"]["ok"]:
        debit = c["balanced"]["totalDebit"]
        credit = c["balanced"]["totalCredit"]
        out.append({
            "blocking": True,
            "text": (
                "Les mouvements ne s'équilibrent pas : débit %s ≠ crédit %s — écart %s."
                if fr else
                "Movements do not balance: debit %s ≠ credit %s — difference %s."
            ) % (nf(debit), nf(credit), nf(debit - credit)),
        })
    if not c["openingBalanced"]["ok"]:
        debit = c["openingBalanced"]["totalDebit"]
        credit = c["openingBalanced"]["totalCredit"]
        out.append({
            "blocking": True,
            "text": (
                "Les soldes d'ouverture ne s'équilibrent pas : débit %s ≠ crédit %s — écart %s."
                if fr else
                "Opening balances do not balance: debit %s ≠ credit %s — difference %s."
            ) % (nf(debit), nf(credit), nf(debit - credit)),
        })
    if not c["closingEquation"]["ok"]:
        failures = c["closingEquation"]["failures"]
        out.append({
            "blocking": True,
            "text": (
                "Clôture ≠ ouverture + mouvements sur %s compte(s) : %s."
                if fr else
                "Closing ≠ opening + movements on %s account(s): %s."
            ) % (nf(len(failures)), _list(failures)),
        })
    if not c["codification"]["ok"]:
        bad = c["codification"]["badAccounts"]
        out.append({
            "blocking": False,
            "text": (
                "%s numéro(s) de compte hors codification (1 à 8 chiffres, sans zéro initial) : %s."
                if fr else
                "%s account number(s) outside the codification (1–8 digits, no leading zero): %s."
            ) % (nf(len(bad)), _list(bad)),
        })
    if c["unknownAccounts"]:
        unknown = c["unknownAccounts"]
        out.append({
            "blocking": False,
            "text": (
                "%s compte(s) sans règle de regroupement SYSCOHADA (à mapper dans l'analyseur) : %s."
                if fr else
                "%s account(s) with no SYSCOHADA grouping rule (map them in the analyzer): %s."
            ) % (nf(len(unknown)), _list(unknown)),
        })
    ties = c["openingTiesToPrior"]
    if ties["checked"] and ties["exceptions"]:
        exceptions = ties["exceptions"]
        result_label = "résultat reporté 12x/13x (classes 6-8 et 12/13 N-1)" if fr else "result carried forward 12x/13x (prior classes 6-8 and 12/13)"
        ex = ", ".join(
            "%s (%s %s %s)" % (
                result_label if e["account"] == "12x/13x" else e["account"], nf(e["opening"]), "vs" if fr else "compared with",
                nf(e["priorClosing"]),
            )
            for e in exceptions[:5]
        )
        more = " …" if len(exceptions) > 5 else ""
        out.append({
            "blocking": False,
            "text": (
                "%s solde(s) d'ouverture différent(s) de la clôture N-1 : %s%s."
                if fr else
                "%s opening balance(s) differ from the prior-year closing: %s%s."
            ) % (nf(len(exceptions)), ex, more),
        })
    return out
