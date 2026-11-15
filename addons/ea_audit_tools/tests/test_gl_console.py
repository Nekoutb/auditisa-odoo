import base64
import io

from odoo.tests import Form, tagged

from odoo.addons.ea_audit_tools.services.gl_analytics import ANALYTICS, mad_of

from .common import to_bytes
from .test_gl import GlCase

# Nine lines, four entries. VE001 is a plain sale; BQ001 is self-approved, round and on the closing
# day; SA001 falls on a Saturday with no reference; DU001 repeats a line exactly.
RICH = """Compte;Intitulé;N° écriture;Libellé;Date;Saisie;Débit;Crédit;Référence;Journal;Préparé;Approuvé;Réviseur;Tiers
411000;Clients;VE001;Facture 1;15/01/2025;15/01/2025;1 000,00;;F1;VE;Awa;Ben;Cid;C1
701000;Ventes;VE001;Facture 1;15/01/2025;15/01/2025;;1 000,00;F1;VE;Awa;Ben;Cid;
521000;Banque;BQ001;Encaissement;31/12/2025;05/01/2026;200 000,00;;C1;BQ;Awa; AWA ;;
411000;Clients;BQ001;Encaissement;31/12/2025;05/01/2026;;200 000,00;C1;BQ;Awa; AWA ;;
601000;Achats;SA001;Achat samedi;01/02/2025;;150,00;;;OD;Dan;;;
521000;Banque;SA001;Achat samedi;01/02/2025;;;150,00;;OD;Dan;;;
601000;Achats;DU001;Doublon;10/03/2025;;70,00;;D1;OD;Dan;;;
601000;Achats;DU001;Doublon;10/03/2025;;70,00;;D1;OD;Dan;;;
521000;Banque;DU001;Doublon;10/03/2025;;;140,00;D1;OD;Dan;;;
"""

RICH_MAPPING = {
    "account": "Compte", "accountName": "Intitulé", "jeNumber": "N° écriture", "jeDescription": "Libellé",
    "journalDate": "Date", "jeDate": "Saisie", "debit": "Débit", "credit": "Crédit", "reference": "Référence",
    "journalCode": "Journal", "preparedBy": "Préparé", "approvedBy": "Approuvé", "reviewer": "Réviseur", "thirdPartyCode": "Tiers",
}

# The mandatory fields and nothing more: an analytic that needs another one says so.
THIN_MAPPING = {"account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "debit": "Débit", "credit": "Crédit"}


class ConsoleCase(GlCase):
    def setUp(self):
        super().setUp()
        self.dataset_id = self.as_staff.create_dataset("journal_entries", "gl.csv", to_bytes(RICH), mapping=RICH_MAPPING)["datasetId"]
        self.as_staff.gl_build_projection(self.dataset_id)

    def run_analytic(self, key, params=None, actor=None):
        return (actor or self.as_staff).gl_run_analytic(self.dataset_id, key, params)

    def console(self, actor=None):
        action = self.env["ea.audit.dataset"].with_user(actor or self.staff).browse(self.dataset_id).action_open_console()
        return self.env["ea.audit.gl.console"].with_user(actor or self.staff).browse(action["res_id"])


@tagged("post_install", "-at_install")
class TestCatalogue(ConsoleCase):
    def test_thirty_with_their_status(self):
        entries = self.as_staff.gl_catalogue(self.dataset_id)
        self.assertEqual([entry["id"] for entry in entries], list(range(1, 31)))
        unavailable = {entry["key"]: entry["unavailable"] for entry in entries if entry["unavailable"]}
        self.assertEqual(set(unavailable), {
            "near-duplicates", "out-of-hours-postings", "sequence-gaps", "manual-vs-automated", "post-period-postings",
        })
        self.assertIn("timestamp", unavailable["out-of-hours-postings"])
        self.assertIn("entry-source", unavailable["manual-vs-automated"])
        self.assertIn("Declared", unavailable["sequence-gaps"])

    def test_the_catalogue_reads_in_french(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        entries = self.as_staff.with_context(lang="fr_FR").gl_catalogue(self.dataset_id)
        self.assertEqual(entries[0]["title"], "Rapprochement du grand livre")

    def test_every_analytic_returns_the_source_shape(self):
        for definition in ANALYTICS:
            # the default threshold of ten repeats finds nothing in nine lines
            params = {"minOccurrences": 2} if definition["key"] == "repeated-amounts" else None
            result = self.run_analytic(definition["key"], params)
            for key in ("key", "title", "objective", "requiredFields", "columns", "rows", "exceptions", "population"):
                self.assertIn(key, result, definition["key"])
            self.assertEqual(result["key"], definition["key"])
            if result.get("unavailable"):
                self.assertEqual(result["rows"], [], definition["key"])
                continue
            self.assertTrue(result["rows"], definition["key"])
            for row in result["rows"]:
                self.assertEqual(len(row["cells"]), len(result["columns"]), definition["key"])
                self.assertRegex(row["month"], r"^(\d{4}-\d{2}|n/a)$")
            if result.get("totals"):
                self.assertEqual(len(result["totals"]), len(result["columns"]), definition["key"])

    def test_unknown_analytic(self):
        with self.assertRaisesRegex(Exception, "unknown-analytic"):
            self.run_analytic("nonsense")

    def test_unavailable_when_a_required_field_is_unmapped(self):
        thin = self.as_staff.create_dataset("journal_entries", "gl.csv", to_bytes(RICH), mapping=THIN_MAPPING, timing="post_audit")["datasetId"]
        self.as_staff.gl_build_projection(thin)
        result = self.as_staff.gl_run_analytic(thin, "self-review")
        self.assertIn("preparer", result["unavailable"])
        self.assertIn("approvedBy", result["unavailable"])
        self.assertEqual(result["rows"], [])
        # the mapping is reported before the analytic's own reason
        self.assertIn("jeDate", self.as_staff.gl_run_analytic(thin, "out-of-hours-postings")["unavailable"])
        self.assertIn("reference", self.as_staff.gl_run_analytic(thin, "near-duplicates")["unavailable"])
        self.assertIsNone(self.as_staff.gl_catalogue(thin)[0]["unavailable"])

    def test_ledger_reconciliation(self):
        result = self.run_analytic("ledger-reconciliation")
        self.assertEqual(result["totals"], [9, 201290, 201290, 0])
        self.assertEqual((result["exceptions"], result["population"]), (0, 4))

    def test_unbalanced_entries(self):
        self.assertEqual(self.run_analytic("unbalanced-entries")["totals"], [4, 0, 0, 0])

    def test_benford(self):
        result = self.run_analytic("benford")
        self.assertEqual(result["totals"][:3], [55.56, 22.22, 0])
        self.assertEqual(result["totals"][6], 22.22)
        self.assertEqual(result["totals"][9], 9)
        self.assertEqual(result["totals"][10], mad_of([5, 2, 0, 0, 0, 0, 2, 0, 0]))
        self.assertEqual(result["population"], 4)
        self.assertEqual(result["exceptions"], 4)
        self.assertIn("risk indicator", result["note"])

    def test_duplicates(self):
        result = self.run_analytic("exact-duplicates")
        self.assertEqual(result["rows"], [{"month": "2025-03", "cells": [1, 2, 1, 140]}])
        self.assertEqual((result["exceptions"], result["population"]), (1, 9))

    def test_round_numbers_with_their_knobs(self):
        result = self.run_analytic("round-numbers")
        self.assertEqual((result["exceptions"], result["population"]), (2, 9))
        self.assertEqual(result["rows"][-1]["cells"][:3], [2, 2, 400000])
        result = self.run_analytic("round-numbers", {"roundMin": 1000, "roundStep": 1000})
        self.assertEqual(result["exceptions"], 4)
        self.assertIn("at least 1000 and an exact multiple of 1000", result["note"])

    def test_weekend(self):
        result = self.run_analytic("weekend-postings")
        self.assertEqual((result["exceptions"], result["population"]), (2, 9))
        february = [row for row in result["rows"] if row["month"] == "2025-02"][0]
        self.assertEqual(february["cells"][5:], [2, 0, 2, 100])

    def test_year_end_is_clamped(self):
        result = self.run_analytic("year-end-concentration")
        self.assertEqual(result["exceptions"], 2)
        self.assertEqual(result["totals"][4], 400000)
        self.assertIn("last 15 days", result["note"])
        self.assertIn("last 90 days", self.run_analytic("year-end-concentration", {"yearEndDays": 5000})["note"])
        self.assertIn("last 1 days", self.run_analytic("year-end-concentration", {"yearEndDays": -3})["note"])
        # 340 days back reaches 25 January, so the sale stays out and February comes in
        self.assertEqual(self.run_analytic("year-end-concentration", {"yearEndDays": 90})["exceptions"], 2)

    def test_self_review(self):
        result = self.run_analytic("self-review")
        self.assertEqual(result["totals"][:3], [4, 2, 1])
        self.assertEqual(result["totals"][4], 2)
        self.assertEqual(result["totals"][5], 400000)
        self.assertEqual((result["exceptions"], result["population"]), (1, 2))

    def test_entry_date_lag(self):
        result = self.run_analytic("entry-date-lag")
        self.assertEqual(result["totals"][:6], [2, 1, 0, 0, 1, 0])
        self.assertEqual(result["exceptions"], 1)
        self.assertEqual(result["totals"][7], 5)

    def test_preparers_fold_into_columns(self):
        result = self.run_analytic("preparer-volume")
        self.assertEqual([column["label"] for column in result["columns"]], ["Dan", "Awa", "Other", "Unattributed", "Total"])
        self.assertEqual(result["totals"], [5, 4, 0, 0, 9])
        self.assertEqual(result["exceptions"], 0)
        top_one = self.run_analytic("preparer-volume", {"topN": 1})
        self.assertEqual(top_one["totals"], [5, 4, 0, 9])
        value = self.run_analytic("preparer-value")
        self.assertEqual(value["columns"][0]["label"], "Awa")
        self.assertEqual(value["totals"][0], 402000)
        reviewer = self.run_analytic("reviewer-workload")
        self.assertEqual(reviewer["exceptions"], 7)

    def test_rare_repeated_and_third_party(self):
        rare = self.run_analytic("rare-accounts", {"rareMax": 1})
        self.assertEqual(rare["exceptions"], 1)  # 701000
        repeated = self.run_analytic("repeated-amounts", {"minOccurrences": 2})
        self.assertEqual(repeated["exceptions"], 8)  # all but 140
        third = self.run_analytic("third-party-attribution")
        self.assertEqual(third["totals"][:3], [2, 1, 1])
        self.assertEqual(self.run_analytic("third-party-attribution", {"prefixes": ["52", "x;--"]})["population"], 3)

    def test_top_value_spikes_and_correlation_notes(self):
        self.assertEqual(self.run_analytic("top-value", {"percentile": 0.5})["exceptions"], 6)
        self.assertIn("99th percentile", self.run_analytic("top-value")["note"])
        spikes = self.run_analytic("monthly-spikes", {"sdFactor": 0.5})
        self.assertEqual(spikes["exceptions"], 1)
        self.assertEqual(spikes["rows"][-1]["month"], "2025-12")
        note = self.run_analytic("debit-credit-correlation")["note"]
        self.assertIn("Pearson correlation", note)
        self.assertEqual(self.run_analytic("debit-credit-correlation")["exceptions"], 0)

    def test_integrity_counts(self):
        self.assertEqual(self.run_analytic("zero-value")["exceptions"], 0)
        self.assertEqual(self.run_analytic("invalid-debit-credit")["exceptions"], 0)
        self.assertEqual(self.run_analytic("missing-references")["exceptions"], 2)
        # 411 credited on BQ001, 701 and 601 never against their side
        self.assertEqual(self.run_analytic("normal-side-exceptions")["exceptions"], 0)
        self.assertEqual(self.run_analytic("account-frequency-value")["exceptions"], 0)
        combos = self.run_analytic("unusual-account-combinations")
        self.assertEqual((combos["population"], combos["exceptions"]), (4, 4))


@tagged("post_install", "-at_install")
class TestCorrelationRead(ConsoleCase):
    def test_two_accounts_keep_to_their_shared_entries(self):
        result = self.as_staff.gl_two_account_correlation(self.dataset_id, "411000", "701000")
        self.assertEqual(result["commonEntries"], 1)
        self.assertEqual(result["months"], [{"month": "2025-01", "aTotal": 1000, "bTotal": -1000, "ratio": -1, "difference": 2000}])
        self.assertIsNone(result["pearson"])  # too few months
        self.assertEqual(result["largestDifference"], 2000)
        self.assertEqual(result["largestDifferenceMonth"], "2025-01")

    def test_correlation_refusals(self):
        with self.assertRaisesRegex(Exception, "same-account"):
            self.as_staff.gl_two_account_correlation(self.dataset_id, "411000", " 411000 ")
        with self.assertRaisesRegex(Exception, "invalid-accounts"):
            self.as_staff.gl_two_account_correlation(self.dataset_id, "411 000", "701000")
        with self.assertRaisesRegex(Exception, "no-dataset"):
            self.as_staff.gl_two_account_correlation(999999, "411000", "701000")

    def test_entry_analysis(self):
        result = self.as_staff.gl_entry_analysis(self.dataset_id, ["411000"])
        self.assertEqual(result["linkedEntries"], 2)
        self.assertEqual([row["account"] for row in result["counterpartAccounts"]], ["521000", "701000"])
        self.assertEqual((result["totalDebit"], result["totalCredit"], result["net"]), (200000, 1000, 199000))
        self.assertEqual(result["months"][0], {"month": "2025-01", "cells": [None, -1000], "total": -1000})
        self.assertEqual(result["hiddenAccounts"], 0)

    def test_entry_analysis_options(self):
        both = self.as_staff.gl_entry_analysis(self.dataset_id, ["411000", "701000"], mode="all")
        self.assertEqual(both["linkedEntries"], 1)
        self.assertEqual(both["counterpartAccounts"], [])
        self.assertEqual(both["months"], [])
        # a limit that is not on offer falls back to twenty
        by_day = self.as_staff.gl_entry_analysis(self.dataset_id, ["411000"], period="weekday", rank="account", limit=1)
        self.assertEqual(by_day["period"], "weekday")
        self.assertEqual([row["account"] for row in by_day["counterpartAccounts"]], ["521000", "701000"])
        self.assertEqual(by_day["hiddenAccounts"], 0)
        self.assertEqual(by_day["months"][0]["month"], "3")  # 31/12/2025 is a Wednesday

    def test_entry_analysis_refusals(self):
        with self.assertRaisesRegex(Exception, "invalid-accounts"):
            self.as_staff.gl_entry_analysis(self.dataset_id, [])
        with self.assertRaisesRegex(Exception, "invalid-accounts"):
            self.as_staff.gl_entry_analysis(self.dataset_id, ["41 1"])
        with self.assertRaisesRegex(Exception, "invalid-accounts"):
            self.as_staff.gl_entry_analysis(self.dataset_id, [str(100000 + i) for i in range(26)])

    def test_the_picker(self):
        found = self.as_staff.gl_accounts_for(self.dataset_id)
        self.assertEqual(found["total"], 4)
        self.assertFalse(found["truncated"])
        self.assertEqual(found["accounts"][0]["account"], "411000")
        self.assertEqual(found["accounts"][0]["signed"], -199000)
        self.assertEqual([row["account"] for row in self.as_staff.gl_accounts_for(self.dataset_id, "clien")["accounts"]], ["411000"])
        self.assertEqual(self.as_staff.gl_accounts_for(self.dataset_id, "%")["total"], 0)


@tagged("post_install", "-at_install")
class TestDrill(ConsoleCase):
    def drill(self, **filter_):
        return self.as_staff.gl_drill_down(self.dataset_id, filter_)

    def test_filters(self):
        self.assertEqual(self.drill()["total"], 9)
        by_account = self.drill(accounts=["411000"])
        self.assertEqual((by_account["total"], by_account["sumSigned"]), (2, -199000))
        self.assertEqual(self.drill(month="2025-03")["total"], 3)
        self.assertEqual(self.drill(month="n/a")["total"], 0)
        self.assertEqual(self.drill(weekday="6")["total"], 2)
        self.assertEqual(self.drill(jeNumber="BQ001")["total"], 2)
        self.assertEqual(self.drill(preparer="Dan")["total"], 5)
        self.assertEqual(self.drill(approver="Ben")["total"], 2)
        self.assertEqual(self.drill(reviewer="Cid")["total"], 2)
        self.assertEqual(self.drill(minAbs=1000)["total"], 4)
        self.assertEqual(self.drill(maxAbs=70)["total"], 2)
        self.assertEqual(self.drill(dateFrom="2025-02-01", dateTo="2025-03-10")["total"], 5)
        self.assertEqual(self.drill(journalCode="VE")["total"], 2)
        self.assertEqual(self.drill(weekendOnly=True)["total"], 2)
        self.assertEqual(self.drill(missingReference=True)["total"], 2)
        line = self.drill(jeNumber="VE001")["lines"][0]
        self.assertEqual(line["journalDate"], "2025-01-15")
        self.assertEqual(line["lineDescription"], "Facture 1")

    def test_entry_level_and_whole_entries(self):
        self.assertEqual(self.drill(accounts=["701000"], entryAccounts=["411000"])["total"], 1)
        whole = self.drill(accounts=["701000"], entryAccounts=["411000"], wholeEntries=True)
        self.assertEqual(whole["total"], 2)
        self.assertEqual({line["account"] for line in whole["lines"]}, {"411000", "701000"})
        self.assertEqual(self.drill(accounts=["411000"], entryAccounts=["411000", "701000"], entryMode="all")["total"], 1)

    def test_cap_and_page(self):
        self.assertEqual(self.drill()["limit"], 100)
        self.assertEqual(self.drill(limit=99999)["limit"], 500)
        self.assertEqual(self.drill(limit=0)["limit"], 100)
        page = self.drill(limit=4, offset=8)
        self.assertEqual((len(page["lines"]), page["total"], page["offset"]), (1, 9, 8))
        self.assertEqual(page["sumSigned"], 0)  # the sum is of every matching line

    def test_refusals(self):
        for code, bad in (
            ("invalid-month", {"month": "2025-13"}),
            ("invalid-weekday", {"weekday": "8"}),
            ("invalid-amount", {"minAbs": -1}),
            ("invalid-amount", {"maxAbs": "x"}),
            ("invalid-date", {"dateFrom": "01/02/2025"}),
            ("invalid-date", {"dateTo": "2025-02-31"}),
            ("invalid-accounts", {"accounts": ["a b"]}),
            ("invalid-accounts", {"accounts": [str(i) for i in range(51)]}),
            ("invalid-accounts", {"entryAccounts": [str(i) for i in range(26)]}),
        ):
            with self.assertRaisesRegex(Exception, code):
                self.as_staff.gl_drill_down(self.dataset_id, bad)

    def test_the_whitelist_drops_the_rest(self):
        self.assertEqual(self.as_staff.gl_drill_down(self.dataset_id, {"nonsense": "1; drop table"})["total"], 9)

    def test_the_native_list_sees_what_the_drill_counted(self):
        Line = self.env["ea.audit.gl.line"].with_user(self.reader)
        for filter_, expected in (
            ({"accounts": ["411000"]}, 2),
            ({"weekendOnly": True}, 2),
            ({"accounts": ["701000"], "entryAccounts": ["411000"], "wholeEntries": True}, 2),
            ({"minAbs": 1000, "month": "2025-12"}, 2),
        ):
            action = self.as_reader.gl_drill_action(self.dataset_id, filter_)
            self.assertEqual(action["res_model"], "ea.audit.gl.line")
            self.assertEqual(Line.search_count(action["domain"]), expected, filter_)
            self.assertEqual(action["limit"], 100)
        lines = Line.search(self.as_reader.gl_drill_action(self.dataset_id, {"jeNumber": "VE001"})["domain"])
        self.assertEqual(sorted(lines.mapped("account")), ["411000", "701000"])
        grouped = Line.formatted_read_group(self.as_reader.gl_drill_action(self.dataset_id, {"accounts": ["411000"]})["domain"], ["account"], ["signed:sum"])
        self.assertEqual(grouped[0]["signed:sum"], -199000)

    def test_the_list_keeps_the_record_rules(self):
        domain = self.as_staff.gl_drill_action(self.dataset_id, {"accounts": ["411000"]})["domain"]
        self.assertEqual(self.env["ea.audit.gl.line"].with_user(self.outsider).search_count(domain), 0)

    def test_a_bad_filter_is_refused_before_the_list_opens(self):
        with self.assertRaisesRegex(Exception, "invalid-month"):
            self.as_staff.gl_drill_action(self.dataset_id, {"month": "soon"})


@tagged("post_install", "-at_install")
class TestInsights(ConsoleCase):
    def test_nothing_imported(self):
        other = self.make_engagement(year=2024)
        self.seat(other, self.staff, "staff")
        as_staff = other.with_user(self.staff)
        self.assertIsNone(as_staff.gl_preparers_reviewers())
        self.assertIsNone(as_staff.gl_class_volumes())
        self.assertIsNone(as_staff.gl_weekday_analysis())
        self.assertIsNone(as_staff.gl_entry_lag())
        self.assertEqual(as_staff.gl_account_prefixes(), [])
        with self.assertRaisesRegex(Exception, "no-dataset"):
            as_staff.gl_correlation_matrix(["411", "521"])

    def test_roles_against_the_prior_year(self):
        prior = RICH.replace(";Awa;", ";Eve;")
        self.as_staff.create_dataset("journal_entries", "py.csv", to_bytes(prior), mapping=RICH_MAPPING, timing="prior_year")
        result = self.as_staff.gl_preparers_reviewers()
        self.assertTrue(result["hasPy"])
        roles = {role["key"]: role for role in result["roles"]}
        self.assertFalse(roles["recordedBy"]["mapped"])
        self.assertEqual(roles["preparedBy"]["cyCount"], 2)
        self.assertEqual(roles["preparedBy"]["onlyCy"], ["Awa"])
        self.assertEqual(roles["preparedBy"]["onlyPy"], ["Eve"])

    def test_class_volumes(self):
        result = self.as_staff.gl_class_volumes()
        self.assertFalse(result["hasPy"])
        by_class = {row["cls"]: row for row in result["rows"]}
        self.assertEqual(len(by_class), 7)
        self.assertEqual((by_class["4"]["cyLines"], by_class["4"]["cyGross"]), (2, 201000))
        self.assertIsNone(by_class["4"]["pyLines"])
        self.as_staff.create_dataset("journal_entries", "py.csv", to_bytes(RICH), mapping=RICH_MAPPING, timing="prior_year")
        result = self.as_staff.gl_class_volumes()
        self.assertEqual({row["cls"]: row for row in result["rows"]}["4"]["grossPct"], 0)

    def test_weekday(self):
        result = self.as_staff.gl_weekday_analysis()
        self.assertEqual(result["undated"], 0)
        saturday = result["rows"][5]
        self.assertEqual((saturday["dow"], saturday["journals"], saturday["lines"], saturday["gross"]), (5, 1, 2, 300))
        wednesday = result["rows"][2]
        self.assertEqual((wednesday["journals"], wednesday["lines"]), (2, 4))

    def test_entry_lag(self):
        result = self.as_staff.gl_entry_lag()
        self.assertEqual(result["journals"], 2)
        self.assertEqual(result["maxDays"], 5)
        self.assertEqual(result["avgDays"], 2.5)
        self.assertEqual({b["key"]: b["journals"] for b in result["buckets"]}, {"d0": 1, "d1_7": 1, "d8_30": 0, "d31_90": 0, "over90": 0})

    def test_prefixes_and_the_matrix(self):
        prefixes = {row["prefix"]: row for row in self.as_staff.gl_account_prefixes()}
        self.assertEqual(prefixes["411"]["lines"], 2)
        self.assertEqual(prefixes["411"]["name"], "Clients")
        result = self.as_staff.gl_correlation_matrix(["411", "521"])
        self.assertEqual(result["sharedJournals"], 1)
        self.assertEqual(result["matrix"][11][30], 1)
        self.assertEqual(result["prefixes"][0], {"prefix": "411", "lines": 2, "gross": 201000})
        self.assertEqual(len(result["pairs"]), 1)
        for bad in (["411"], ["41a", "521"], ["1", "2"], ["11", "12", "13", "14", "15", "16", "17"]):
            with self.assertRaisesRegex(Exception, "invalid-accounts"):
                self.as_staff.gl_correlation_matrix(bad)


@tagged("post_install", "-at_install")
class TestConsoleScreen(ConsoleCase):
    def test_every_tab_answers_on_the_screen(self):
        console = self.console()
        self.assertIn("Ledger reconciliation", str(console.catalogue_html))
        self.assertIn("201\u202f290", str(console.head_html))
        console.selected_accounts = "411000"
        console.action_run_entry()
        self.assertIn("521000", str(console.entry_html))
        console.write({"corr_a": "411000", "corr_b": "701000"})
        console.action_run_correlation()
        self.assertIn("1 000", str(console.corr_html))
        console.action_swap()
        self.assertEqual(console.corr_a, "701000")
        console.analytic_key = "weekend-postings"
        console.action_run_analytic()
        self.assertIn("Sat", str(console.analytic_html))
        self.assertIn("exceptions requiring audit consideration", str(console.analytic_html))
        console.action_load_insights()
        self.assertIn("Preparers", str(console.insights_html))
        console.prefix_accounts = "411, 521"
        console.action_run_matrix()
        self.assertIn("1 journals", str(console.matrix_html))

    def test_the_screen_reads_in_french(self):
        self.env["res.lang"]._activate_lang("fr_FR")
        console = self.console().with_context(lang="fr_FR")
        console.analytic_key = "weekend-postings"
        console.action_run_analytic()
        self.assertIn("Sam", str(console.analytic_html))
        self.assertIn("02/2025", str(console.analytic_html))
        self.assertIn("Profil des jours", str(console.analytic_html))

    def test_the_wording_rule(self):
        console = self.console()
        for definition in ANALYTICS:
            console.analytic_key = definition["key"]
            console.action_run_analytic()
            text = str(console.analytic_html).lower()
            self.assertNotIn("fraud", text, definition["key"])

    def test_an_unavailable_analytic_says_so(self):
        console = self.console()
        console.analytic_key = "sequence-gaps"
        console.action_run_analytic()
        self.assertIn("o_ea_banner", str(console.analytic_html))

    def test_the_picker_feeds_the_selection(self):
        console = self.console()
        console.account_search = "clien"
        console.action_search_accounts()
        self.assertEqual(console.account_ids.mapped("account"), ["411000"])
        console.account_ids.selected = True
        console.action_add_picked()
        self.assertEqual(console.selected_accounts, "411000")
        self.assertFalse(console.account_ids.selected)

    def test_drills_open_the_native_list(self):
        console = self.console()
        Line = self.env["ea.audit.gl.line"].with_user(self.staff)
        console.selected_accounts = "411000"
        console.write({"drill_account": "701000", "drill_month": "01/2025"})
        action = console.action_drill_entry()
        self.assertEqual(action["res_model"], "ea.audit.gl.line")
        self.assertEqual(Line.search_count(action["domain"]), 2)
        self.assertEqual(action["context"]["search_default_group_entry"], 1)
        console.write({"corr_a": "411000", "corr_b": "701000", "drill_account": False, "drill_month": "2025-01"})
        self.assertEqual(Line.search_count(console.action_drill_correlation()["domain"]), 1)
        console.drill_month = "02/2025"
        self.assertEqual(Line.search_count(console.action_drill_month()["domain"]), 2)
        console.drill_month = "février"
        with self.assertRaisesRegex(Exception, "invalid-month"):
            console.action_drill_month()
        console.write({"filter_accounts": "601000 521000", "filter_min_abs": "100", "filter_max_abs": "150,00"})
        self.assertEqual(Line.search_count(console.action_drill_filter()["domain"]), 3)

    def test_the_analytic_goes_to_excel(self):
        from openpyxl import load_workbook

        console = self.console()
        console.analytic_key = "exact-duplicates"
        action = console.action_export_analytic()
        self.assertIn("field=export_file", action["url"])
        book = load_workbook(io.BytesIO(base64.b64decode(console.export_file)))
        sheet = book.worksheets[0]
        rows = [row for row in sheet.iter_rows(values_only=True)]
        self.assertIn("2025-03", [row[0] for row in rows])
        self.assertIn("gl-exact-duplicates", console.export_filename)

    def test_export_without_a_request_is_refused(self):
        with self.assertRaisesRegex(Exception, "unknown-analytic"):
            self.as_reader.ea_export_xlsx("gl_analytic")

    def test_the_hub_form_offers_the_console(self):
        action = self.console()._ea_reopen()
        self.assertEqual(action["res_model"], "ea.audit.gl.console")
        form = self.env["ea.audit.dataset"].with_user(self.staff).get_view(self.env.ref("ea_audit_tools.view_dataset_form").id)
        self.assertIn("action_open_console", form["arch"])

    def test_the_form_edits_and_another_ledger_clears_the_results(self):
        other = self.as_staff.create_dataset("journal_entries", "gl.csv", to_bytes(RICH), mapping=RICH_MAPPING, timing="post_audit")["datasetId"]
        self.as_staff.gl_build_projection(other)
        console = self.console()
        console.selected_accounts = "411000"
        console.action_run_entry()
        with Form(console) as form:
            form.analytic_key = "benford"
            form.dataset_id = self.env["ea.audit.dataset"].browse(other)
        self.assertEqual(console.analytic_key, "benford")
        self.assertFalse(console.selected_accounts)
        self.assertFalse(console.entry_html)

    def test_the_views_load_for_a_reader(self):
        Console = self.env["ea.audit.gl.console"].with_user(self.reader)
        view = Console.get_view(self.env.ref("ea_audit_tools.view_gl_console_form").id)
        self.assertNotIn('name="action_build_projection"', view["arch"])
        self.assertIn("action_run_analytic", view["arch"])


@tagged("post_install", "-at_install")
class TestLeadFigure(ConsoleCase):
    OPENING_TB = """Compte;Libellé;Solde ouverture débit;Solde ouverture crédit;Mouvement débit;Mouvement crédit
411000;Clients;800;0;1000;900
701000;Ventes;0;800;900;1000
"""

    def setUp(self):
        super().setUp()
        self.import_tb(self.OPENING_TB)
        self.ledger = """Compte;N° écriture;Libellé;Date;Débit;Crédit
411000;A1;x;15/01/2025;1 000,00;
701000;A1;x;15/01/2025;;1 000,00
411000;A2;x;16/01/2025;;900,00
701000;A2;x;16/01/2025;900,00;
"""
        mapping = {"account": "Compte", "jeNumber": "N° écriture", "jeDescription": "Libellé", "journalDate": "Date", "debit": "Débit", "credit": "Crédit"}
        self.dataset_id = self.as_staff.create_dataset("journal_entries", "gl.csv", to_bytes(self.ledger), mapping=mapping)["datasetId"]
        self.as_staff.gl_build_projection(self.dataset_id)

    def line(self, code="411000"):
        return self.env["ea.audit.lead.line"].with_user(self.staff).search([("engagement_id", "=", self.engagement.id), ("account_code", "=", code)])

    def test_opening_plus_drilled_equals_closing(self):
        figure = self.as_reader.gl_reconcile_figure(self.dataset_id, ["411000"], 800, 900)
        self.assertEqual(figure, {"opening": 800, "movements": 100, "lines": 2, "computed": 900, "closing": 900, "gap": 0})
        self.assertEqual(self.as_reader.gl_reconcile_figure(self.dataset_id, ["411000"], 800, 1000)["gap"], 100)

    def test_a_lead_line_arrives_filtered_and_reconciled(self):
        line = self.line()
        action = line.action_open_gl_console()
        console = self.env["ea.audit.gl.console"].with_user(self.staff).browse(action["res_id"])
        self.assertEqual(console.selected_accounts, "411000")
        self.assertTrue(console.figure_set)
        self.assertEqual((console.figure_opening, console.figure_closing), (800, 900))
        self.assertIn("gap 0", str(console.figure_html))
        drill = console.action_drill_figure()
        self.assertEqual(self.env["ea.audit.gl.line"].with_user(self.staff).search_count(drill["domain"]), 2)

    def test_a_schedule_arrives_with_all_its_accounts(self):
        schedule = self.line().schedule_id
        action = schedule.action_open_gl_console()
        console = self.env["ea.audit.gl.console"].with_user(self.staff).browse(action["res_id"])
        self.assertEqual(console.selected_accounts, "411000")
        self.assertEqual(console.figure_closing, schedule.closing)

    def test_no_ledger_no_console(self):
        other = self.make_engagement(year=2024)
        self.seat(other, self.staff, "staff")
        with self.assertRaisesRegex(Exception, "no-dataset"):
            other.with_user(self.staff).gl_open_console()


@tagged("post_install", "-at_install")
class TestWhoReads(ConsoleCase):
    def calls(self, actor):
        return [
            lambda: actor.gl_catalogue(self.dataset_id),
            lambda: actor.gl_run_analytic(self.dataset_id, "benford"),
            lambda: actor.gl_accounts_for(self.dataset_id),
            lambda: actor.gl_entry_analysis(self.dataset_id, ["411000"]),
            lambda: actor.gl_two_account_correlation(self.dataset_id, "411000", "701000"),
            lambda: actor.gl_drill_down(self.dataset_id, {}),
            lambda: actor.gl_drill_action(self.dataset_id, {}),
            lambda: actor.gl_reconcile_figure(self.dataset_id, ["411000"], 0, 0),
            actor.gl_preparers_reviewers,
            actor.gl_class_volumes,
            actor.gl_weekday_analysis,
            actor.gl_entry_lag,
            actor.gl_account_prefixes,
            lambda: actor.gl_correlation_matrix(["411", "521"]),
            lambda: actor.gl_open_console(),
            lambda: actor.with_context(ea_gl_analytic={"dataset": self.dataset_id, "key": "benford"}).ea_export_xlsx("gl_analytic"),
        ]

    def test_an_outsider_is_refused_everywhere(self):
        for call in self.calls(self.as_outsider):
            with self.assertRaisesRegex(Exception, "not-on-this-engagement"):
                call()
        with self.assertRaisesRegex(Exception, "not-on-this-engagement"):
            self.env["ea.audit.gl.console"].with_user(self.outsider).create({"engagement_id": self.engagement.id, "dataset_id": self.dataset_id})

    def test_read_only_and_eqr_members_read(self):
        for actor in (self.as_reader, self.as_eqr):
            for call in self.calls(actor):
                call()
        console = self.console(self.eqr)
        console.action_run_analytic()
        self.assertTrue(console.analytic_html)
        console = self.console(self.reader)
        console.action_load_insights()
        self.assertTrue(console.insights_html)

    def test_an_archived_file_still_answers(self):
        self.engagement.sudo().write({"archived_at": "2026-01-01 00:00:00"})
        self.env.invalidate_all()
        for call in self.calls(self.as_staff):
            call()
        console = self.console()
        console.action_run_analytic()
        self.assertTrue(console.analytic_html)

    def test_another_files_ledger_is_not_this_files(self):
        other = self.make_engagement(year=2024)
        self.seat(other, self.staff, "staff")
        with self.assertRaisesRegex(Exception, "no-dataset"):
            other.with_user(self.staff).gl_run_analytic(self.dataset_id, "benford")
        with self.assertRaisesRegex(Exception, "no-dataset"):
            other.with_user(self.staff).gl_drill_down(self.dataset_id, {})
