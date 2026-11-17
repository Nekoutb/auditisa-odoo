"""Execution of the designed procedures (owner's mock-ups of 2026-11-16, mock-proc-exec-*): the
"Substantive procedures" page shows only what was designed; each procedure has its working paper,
with its steps, samples, the tool's work (reconciliation, cut-off), confirmations, evidence, a
conclusion and the findings raised from it."""
import base64
import json

from odoo.tests import tagged

from odoo.addons.ea_audit_core.services.activity_summary import parse_body, translate_summary

from .common import AR_CSV, AR_MAPPING, to_bytes
from .test_gl import LEDGER, MAPPING
from .test_procedure_design import ProcedureDesignCase

#: A sale of the next year, three days after the year end.
NEXT_SALE = """Compte;Intitulé;N° écriture;Libellé;Date;Débit;Crédit;Référence;Journal;Saisi par
411000;Clients;VE101;Facture 101;03/01/2026;2 000,00;;F101;VE;Awa
701000;Ventes;VE101;Facture 101;03/01/2026;;2 000,00;F101;VE;Awa
701000;Ventes;VE102;Facture 102;25/01/2026;;9 000,00;F102;VE;Awa
411000;Clients;VE102;Facture 102;25/01/2026;9 000,00;;F102;VE;Awa
"""


class ExecutionCase(ProcedureDesignCase):
    def setUp(self):
        super().setUp()
        # the procedures exist once the design has run, as when the design page is opened
        self.engagement.sudo()._ea_sync_procedures()

    def proc_page(self, code, actor=None):
        return (actor or self.as_staff).ea_procedure_paper(self.proc(code).id)

    def chips(self, page=None):
        page = page or self.as_staff.ea_substantive_page()
        account = next(a for a in page["accounts"] if a["code"] == "E")
        return {chip["code"]: chip for chip in account["chips"]}

    def ar(self, timing="pre_audit"):
        return self.as_staff.create_dataset("ar_open_items", "ar.csv", to_bytes(AR_CSV), mapping=AR_MAPPING, timing=timing)["datasetId"]

    def ledger(self, content=LEDGER, timing="pre_audit"):
        return self.as_staff.create_dataset("journal_entries", "ledger.csv", to_bytes(content), mapping=MAPPING, timing=timing)["datasetId"]

    def trail(self):
        return [parse_body(body) for body in self.engagement.sudo().message_ids.mapped("body") if parse_body(body)]


@tagged("post_install", "-at_install")
class TestOverview(ExecutionCase):
    def test_only_the_designed_procedures_are_shown(self):
        chips = self.chips()
        mandatory = self.env["ea.audit.designed.procedure"].sudo().search([
            ("engagement_id", "=", self.engagement.id), ("index_code", "=", "E"), ("selected", "=", True),
        ])
        self.assertEqual(set(chips), set(mandatory.mapped("code")))
        self.assertNotIn("E-A2", chips)
        self.as_staff.ea_procedure_choose("E", "E-A2", True)
        self.assertIn("E-A2", self.chips())
        self.as_staff.ea_procedure_choose("E", "E-A2", False)
        self.assertNotIn("E-A2", self.chips())

    def test_an_unfinished_design_is_flagged(self):
        self.assess("E", "higher", "not_rely")
        self.assess("V", "lower", "not_rely")
        account = next(a for a in self.as_staff.ea_substantive_page()["accounts"] if a["code"] == "E")
        self.assertEqual(account["missing"], ["E"])
        self.as_staff.ea_procedure_choose("E", "E-A2", True)
        account = next(a for a in self.as_staff.ea_substantive_page()["accounts"] if a["code"] == "E")
        self.assertEqual(account["missing"], [])

    def test_the_tile_and_the_paper_open(self):
        tile = self.env.ref("ea_audit_tools.tile_substantive")
        self.assertEqual(tile.method, "action_tool_substantive")
        self.assertEqual(self.as_staff.action_tool_substantive()["tag"], "ea_audit_tools.substantive_page")
        action = self.as_staff.ea_exec_open("paper", self.proc("E-M1").id)
        self.assertEqual((action["tag"], action["params"]["procedure_id"]), ("ea_audit_tools.procedure_paper", self.proc("E-M1").id))
        with self.assertRaisesRegex(Exception, "forbidden"):
            self.as_staff.ea_exec_open("unlink")
        filename, content = self.as_staff.ea_export_xlsx("substantive")
        self.assertTrue(filename.endswith(".xlsx") and content)


@tagged("post_install", "-at_install")
class TestControlsFirst(ExecutionCase):
    """Owner's ruling of 2026-11-18: under Controls reliance the controls are tested before the
    substantive procedures; the page warns while they are not concluded, and never blocks."""

    WARNING = "This engagement relies on controls: test the controls first. Substantive procedures depend on their result."

    def test_no_warning_under_substantive_only(self):
        self.answer_profile()
        self.assertFalse(self.as_staff.ea_substantive_page()["controlsFirst"])

    def test_no_warning_without_a_questionnaire(self):
        self.assertFalse(self.as_staff.ea_substantive_page()["controlsFirst"])

    def test_a_warning_until_the_tests_of_controls_are_concluded(self):
        self.answer_profile(q19_approach="controls")
        page = self.as_staff.ea_substantive_page()
        self.assertEqual(page["controlsFirst"], self.WARNING)
        # a warning only: the procedures are listed as before
        self.assertTrue(self.chips(page))
        items = self.env["ea.audit.file.item"].sudo().search([
            ("engagement_id", "=", self.engagement.id), ("code", "in", ["E1.1", "E1.2"]),
        ])
        self.assertEqual(len(items), 2)
        items[:1].state = "prepared"
        self.assertTrue(self.as_staff.ea_substantive_page()["controlsFirst"])
        items.write({"state": "prepared"})
        self.assertFalse(self.as_staff.ea_substantive_page()["controlsFirst"])

    def test_the_warning_reads_in_french(self):
        self.answer_profile(q19_approach="controls")
        self.env["res.lang"]._activate_lang("fr_FR")
        self.staff.lang = "fr_FR"
        page = self.engagement.with_user(self.staff).with_context(lang="fr_FR").ea_substantive_page()
        self.assertTrue(page["controlsFirst"].startswith("Cette mission s'appuie sur les contrôles"))


@tagged("post_install", "-at_install")
class TestWorkingPaper(ExecutionCase):
    def test_started_then_done_then_reopened(self):
        proc = self.proc("E-M4")
        page = self.proc_page("E-M4")
        self.assertEqual(page["state"], "draft")
        self.assertTrue(page["steps"])
        self.assertIn(page["assertions"][0]["code"], ("V", "P"))
        page = self.as_staff.ea_proc_step(proc.id, 0, True)
        self.assertEqual(proc.state, "started")
        self.assertTrue(page["steps"][0]["done"])
        with self.assertRaisesRegex(Exception, "procedure-not-finished"):
            self.as_staff.ea_proc_done(proc.id)
        for step in page["steps"]:
            self.as_staff.ea_proc_step(proc.id, step["index"], True)
        self.as_staff.ea_proc_save(proc.id, {"conclusion": "satisfactory", "note": "Allowance reasonable."})
        page = self.as_staff.ea_proc_done(proc.id)
        self.assertEqual((proc.state, proc.done_by_id, page["locked"]), ("done", self.staff, True))
        self.assertTrue(proc.done_at)
        with self.assertRaisesRegex(Exception, "procedure-done"):
            self.as_staff.ea_proc_save(proc.id, {"note": "changed"})
        self.as_staff.ea_proc_reopen(proc.id)
        self.assertEqual((proc.state, proc.done_by_id.id), ("started", False))
        lines = [summary for action, summary in self.trail() if action in ("procedure_done", "procedure_reopened")]
        self.assertIn("Procedure E E-M4 done: satisfactory", lines)
        self.assertIn("Procedure E E-M4 reopened", lines)
        french = translate_summary("procedure_done", "Procedure E E-M4 done: satisfactory", "fr_FR")
        self.assertIn("terminée", french)
        self.assertIn("aucune exception", french)

    def test_a_reader_reads_but_does_not_change(self):
        proc = self.proc("E-M4")
        with self.assertRaises(Exception):
            self.as_reader.with_user(self.reader2).ea_proc_step(proc.id, 0, True)
        with self.assertRaises(Exception):
            self.as_outsider.ea_procedure_paper(proc.id)

    def test_the_sample_drawn_for_the_procedure(self):
        self.as_staff.ea_procedure_choose("E", "E-A2", True)
        proc = self.proc("E-A2")
        page = self.as_staff.ea_procedure_paper(proc.id)
        self.assertEqual((page["mode"], page["samples"], page["canDraw"]), ("sample", [], True))
        dataset = self.ar()
        run = self.as_staff.run_sampling(dataset, "random", 2, seed="abc", designed_procedure=proc).sudo()
        page = self.as_staff.ea_procedure_paper(proc.id)
        sample = page["samples"][0]
        self.assertEqual((sample["id"], sample["size"]), (run.id, 2))
        row = sample["rows"][0]
        page = self.as_staff.ea_proc_sample_item(proc.id, run.id, row["rowNo"], {"audited": row["book"], "how": "receipt"})
        self.assertEqual(page["samples"][0]["rows"][0]["result"], "agreed")
        self.assertEqual(self.chips()["E-A2"]["items"], "1/2")

    def test_a_finding_is_raised_with_its_source(self):
        proc = self.proc("E-M4")
        page = self.as_staff.ea_proc_finding(proc.id, "Allowance understated", 5000, "misstatement", True)
        finding = self.env["ea.audit.finding"].sudo().search([("source_model", "=", "ea.audit.designed.procedure"), ("source_id", "=", proc.id)])
        self.assertEqual(len(finding), 1)
        self.assertEqual((finding.route, finding.amount), ("b5", 5000))
        self.assertEqual(page["findings"][0]["id"], finding.id)
        self.as_staff.ea_proc_finding(proc.id, "Approval missing", None, "deficiency")
        overview = self.as_staff.ea_substantive_page()
        self.assertEqual(overview["stats"]["findings"], 2)
        self.assertTrue(self.chips(overview)["E-M4"]["flag"])
        action = self.as_staff.ea_exec_open("finding", finding.id)
        self.assertEqual(action["params"]["finding_id"], finding.id)

    def test_a_misstatement_reaches_the_summary_with_its_source(self):
        """Owner's ruling of 2026-11-16: the summary's lines come from the papers' conclusions,
        each one showing the procedure, the account and the paper, and opening the paper."""
        proc = self.proc("E-M4")
        self.assertCode("invalid-type", self.as_staff.ea_proc_finding, proc.id, "x", 10, "misstatement", True, None, None, "411", "701", "disclosure")
        page = self.as_staff.ea_proc_finding(
            proc.id, "Allowance understated", 5000, "misstatement", True, None, None, "659100", "491000", "judgmental",
        )
        self.assertEqual(page["misstatements"]["count"], 1)
        self.assertEqual(page["findings"][0]["accounts"], "Dr 659100 / Cr 491000")
        finding = self.env["ea.audit.finding"].sudo().browse(page["findings"][0]["id"])
        entry = self.env["ea.audit.sad.entry"].sudo().search([("misstatement_id", "=", finding.misstatement_id.id)])
        self.assertEqual((entry.dr_account, entry.cr_account, entry.dr_amount, entry.mtype), ("659100", "491000", 5000, "judgmental"))
        self.assertEqual(entry.source_procedure_id, proc)
        self.assertTrue(entry.source_label.startswith("E-M4 · "))
        self.assertTrue(entry.source_label.endswith(proc.file_item_id.code))
        sad = self.as_staff.ea_sad_page()
        row = next(r for bucket in sad["rows"].values() for r in bucket if r["id"] == entry.id)
        self.assertEqual((row["sourceProcId"], row["byHand"]), (proc.id, False))
        action = self.as_staff.ea_sad_page_open("source", entry.id)
        self.assertEqual((action["tag"], action["params"]["procedure_id"]), ("ea_audit_tools.procedure_paper", proc.id))

    def test_a_projection_flows_through_the_procedure_that_owns_the_sample(self):
        proc = self.proc("E-M4")
        run = self.as_staff.run_sampling(self.ar(), "random", 2, seed="abc", designed_procedure=proc).sudo()
        # every item of the sample wrong: the projection is the whole population, far above trivial
        result = run.with_user(self.staff).evaluate(run.summary["sampledValue"])
        self.assertTrue(result["raisedToB5"])
        entry = self.env["ea.audit.sad.entry"].sudo().search([("engagement_id", "=", self.engagement.id)])
        self.assertEqual((entry.mtype, entry.source_procedure_id), ("projected", proc))
        findings = self.as_staff.ea_procedure_paper(proc.id)["findings"]
        self.assertEqual([f["route"] for f in findings], ["b5"])

    def test_evidence_is_filed_on_the_task(self):
        proc = self.proc("E-M4")
        content = base64.b64encode(b"allowance schedule").decode()
        page = self.as_staff.ea_proc_upload(proc.id, "allowance.txt", content)
        self.assertEqual([f["name"] for f in page["evidence"]], ["allowance.txt"])
        row = self.env["ea.audit.task.attachment"].sudo().browse(page["evidence"][0]["id"])
        self.assertEqual((row.designed_procedure_id, row.code), (proc, "E4.1"))


@tagged("post_install", "-at_install")
class TestToolWork(ExecutionCase):
    def test_reconciliation_and_its_missing_data(self):
        proc = self.proc("E-M1")
        recon = self.as_staff.ea_procedure_paper(proc.id)["recon"]
        self.assertEqual(recon["state"], "no-subledger")
        self.assertEqual(recon["gl"], 900)  # 411000: 800 + 1 000 - 900
        self.ar()
        recon = self.as_staff.ea_procedure_paper(proc.id)["recon"]
        self.assertEqual((recon["sub"], recon["difference"], recon["state"]), (350, -550, "difference"))
        self.assertEqual(recon["parties"][0]["name"], "Beta")
        page = self.as_staff.ea_proc_explain(proc.id, "add", None, {"text": "Receipts after cut-off", "amount": "-550", "cleared": True})
        self.assertEqual((page["recon"]["state"], page["recon"]["unexplained"]), ("explained", 0))
        self.assertEqual(proc.state, "started")
        page = self.as_staff.ea_proc_explain(proc.id, "remove", 0)
        self.assertEqual(page["recon"]["state"], "difference")

    def test_cutoff_selection_reads_both_ledgers_and_freezes(self):
        proc = self.proc("E-M3")
        page = self.as_staff.ea_procedure_paper(proc.id)
        self.assertEqual(page["mode"], "cutoff")
        self.assertFalse(page["selection"]["hasCurrent"])
        with self.assertRaisesRegex(Exception, "no-dataset"):
            self.as_staff.ea_proc_select(proc.id, 10, 100)
        self.ledger()
        page = self.as_staff.ea_proc_select(proc.id, 10, 100)
        self.assertEqual([(i["side"], i["entry"]) for i in page["selection"]["items"]], [("before", "BQ001")])
        self.assertFalse(page["selection"]["hasNext"])
        self.ledger(NEXT_SALE, timing="subsequent")
        page = self.as_staff.ea_proc_select(proc.id, 10, 100)
        selection = page["selection"]
        self.assertEqual([(i["side"], i["entry"], i["amount"]) for i in selection["items"]], [("before", "BQ001", -1000), ("after", "VE101", 2000)])
        self.assertTrue(selection["hasNext"])
        self.assertTrue(selection["sentence"])
        self.assertTrue(selection["warning"])  # the next-year ledger reaches 25 days only
        runs = proc.run_ids.filtered(lambda r: r.method == "cutoff")
        self.assertEqual(len(runs), 1)  # selected again in place
        sampling = self.as_staff.ea_sampling_page()
        card = next(c for c in sampling["tod"] if c["id"] == runs.id)
        self.assertEqual((card["procedureId"], card["stats"]["items"]), (proc.id, 2))
        key = selection["items"][1]["key"]
        page = self.as_staff.ea_proc_select_item(proc.id, key, {"period": "no", "doc": True, "note": "Delivered in 2026"})
        self.assertTrue(page["selection"]["frozen"])
        self.assertEqual(page["selection"]["counts"], {"done": 1, "wrong": 1, "total": 2})
        with self.assertRaisesRegex(Exception, "selection-frozen"):
            self.as_staff.ea_proc_select(proc.id, 5, 100)
        with self.assertRaisesRegex(Exception, "selection-on-paper"):
            runs.with_user(self.staff).ea_sampling_item(key, {"note": "x"})
        page = self.as_staff.ea_proc_finding(proc.id, "Sale VE101 recorded in the wrong period", 2000, "misstatement", True, key)
        self.assertTrue(page["selection"]["items"][1]["finding"])
        self.assertTrue(any(action == "procedure_selection" for action, _summary in self.trail()))
        # every entry answered before the procedure can be done
        self.as_staff.ea_proc_save(proc.id, {"conclusion": "exceptions", "note": "One sale in the wrong period."})
        for step in page["steps"]:
            self.as_staff.ea_proc_step(proc.id, step["index"], True)
        with self.assertRaisesRegex(Exception, "procedure-not-finished"):
            self.as_staff.ea_proc_done(proc.id)
        self.as_staff.ea_proc_select_item(proc.id, selection["items"][0]["key"], {"period": "yes"})
        self.as_staff.ea_proc_done(proc.id)
        self.assertEqual(proc.state, "done")

    def test_confirmations_and_their_difference(self):
        self.ar()
        proc = self.proc("E-M2")
        page = self.as_staff.ea_procedure_paper(proc.id)
        self.assertIsNotNone(page["confirm"])
        self.assertIn("Alpha", [p["name"] for p in page["confirm"]["parties"]])
        page = self.as_staff.ea_proc_confirm(proc.id, "add", None, {"party": "Alpha"})
        row = page["confirm"]["rows"][0]
        self.assertEqual((row["book"], row["state"]), (100, "waiting"))
        page = self.as_staff.ea_proc_confirm(proc.id, "update", row["id"], {"status": "received", "confirmed": "90"})
        row = page["confirm"]["rows"][0]
        self.assertEqual((row["difference"], row["state"]), (-10, "difference"))
        page = self.as_staff.ea_proc_confirm_finding(proc.id, row["id"])
        row = page["confirm"]["rows"][0]
        self.assertTrue(row["finding"])
        finding = self.env["ea.audit.finding"].browse(row["finding"]).sudo()
        self.assertEqual((finding.amount, finding.source_id), (-10, proc.id))
        with self.assertRaisesRegex(Exception, "invalid-value"):
            self.as_staff.ea_proc_confirm_finding(proc.id, row["id"])
        page = self.as_staff.ea_proc_confirm(proc.id, "update", row["id"], {"status": "no_reply"})
        self.assertEqual(page["confirm"]["rows"][0]["state"], "alternative")

    def test_confirmations_are_their_own_procedure(self):
        # owner, 2026-11-16: no confirmations block on other procedures; earlier requests stay, read only
        proc = self.proc("E-M4")
        page = self.as_staff.ea_procedure_paper(proc.id)
        self.assertIsNone(page["confirm"])
        self.assertNotIn("canAddConfirm", page)
        with self.assertRaisesRegex(Exception, "invalid-value"):
            self.as_staff.ea_proc_confirm(proc.id, "enable")
        with self.assertRaisesRegex(Exception, "invalid-value"):
            self.as_staff.ea_proc_confirm(proc.id, "add", None, {"party": "Lawyer Ndi", "book": "0"})
        self.env["ea.audit.confirmation"].sudo().create({
            "engagement_id": self.engagement.id, "designed_procedure_id": proc.id, "party": "Lawyer Ndi",
        })
        page = self.as_staff.ea_procedure_paper(proc.id)
        self.assertEqual((page["confirm"]["rows"][0]["party"], page["confirm"]["editable"]), ("Lawyer Ndi", False))

    def test_the_tool_proposes_the_customers_to_confirm(self):
        self.ar()
        proc = self.proc("E-M2")
        page = self.as_staff.ea_procedure_paper(proc.id)
        self.assertEqual((page["mode"], page["confirm"]["editable"], page["confirm"]["side"]), ("confirm", True, "customers"))
        page = self.as_staff.ea_proc_confirm(proc.id, "pick")
        self.assertEqual([(r["party"], r["book"]) for r in page["confirm"]["rows"]], [("Beta", 250), ("Alpha", 100)])
        page = self.as_staff.ea_proc_confirm(proc.id, "pick")  # nobody twice
        self.assertEqual(len(page["confirm"]["rows"]), 2)

    def test_tabs_in_working_order_and_the_account_link(self):
        self.as_staff.ea_procedure_choose("E", "E-A2", True)
        page = self.proc_page("E-M1")
        codes = [t["code"] for t in page["tabs"]]
        self.assertEqual(codes[0], "E-M1")
        self.assertEqual(codes[-1], "E-A2")
        action = self.as_staff.ea_exec_open("account", "E")
        self.assertEqual(action["params"]["procedure_id"], self.proc("E-M1").id)
        account = next(a for a in self.as_staff.ea_substantive_page()["accounts"] if a["code"] == "E")
        self.assertEqual((account["state"], account["ownOnly"]), ("open", False))
        self.as_staff.ea_proc_step(self.proc("E-M1").id, 0, True)
        account = next(a for a in self.as_staff.ea_substantive_page()["accounts"] if a["code"] == "E")
        self.assertEqual(account["state"], "started")


#: A trial balance with fixed assets (K: 231 cost, 2831 depreciation) and inventory (F: 311).
TB_KF = """Compte;Libellé;Solde ouverture débit;Solde ouverture crédit;Mouvement débit;Mouvement crédit
101000;Capital;0;5200;0;0
231000;Bâtiments;4000;0;0;0
283100;Amortissements bâtiments;0;400;0;0
311000;Marchandises;600;0;0;0
401000;Fournisseurs;0;500;400;500
411000;Clients;800;0;1000;900
521000;Banque;700;0;900;900
601000;Achats;0;0;2000;0
701000;Ventes;0;0;0;2000
"""

FAR_CSV = """Numero;Designation;Categorie;Date acquisition;Taux;Compte;Cout;Amortissements;VNC;VNC ouverture;Acquisitions;Cessions;Dotation
I1;Immeuble siege;Batiments;02/01/2021;2,5;231000;4000;500;3500;3600;0;0;100
"""
FAR_MAPPING = {
    "item": "Numero", "itemDescription": "Designation", "amount": "Cout", "depreciation": "Amortissements", "nbv": "VNC",
    "category": "Categorie", "acquisitionDate": "Date acquisition", "depreciationRate": "Taux", "account": "Compte", "openingNbv": "VNC ouverture", "additions": "Acquisitions",
    "disposals": "Cessions", "charge": "Dotation",
}

STOCK_CSV = """Article;Designation;Quantite;PU;Montant;Magasin
CB-016;Cable 16mm;1200;10;12000;Store A
TR-250;Transformateur 250 kVA;4;2000;8000;Yard
MB-02;Coffret compteur;85;20;1700;Store B
VI-01;Vis;100;1;100;Store B
"""
STOCK_MAPPING = {"item": "Article", "itemDescription": "Designation", "quantity": "Quantite", "unitPrice": "PU", "amount": "Montant", "location": "Magasin"}


class SubstantiveTwoCase(ExecutionCase):
    """Receivables, fixed assets and inventories significant (mock-sub2-*)."""

    def import_tb(self, content=TB_KF, filename="balance.csv", timing="pre_audit", actor=None):
        return super().import_tb(content, filename, timing, actor)

    def significant(self, code, assertions):
        engagement = self.engagement.sudo()
        engagement._ea_sync_significance()
        record = self.env["ea.audit.significance"].sudo().search([("engagement_id", "=", engagement.id), ("index_code", "=", code)], limit=1)
        self.assertTrue(record, code)
        record.with_user(self.staff)._ea_save({
            "status": "significant", "justification": "Significatif",
            "assertion_ids": [(6, 0, self.env["ea.audit.assertion"]._ea_from_codes(assertions).ids)],
        })
        engagement._ea_sync_cra()
        engagement._ea_sync_procedures()

    def code_proc(self, index_code, code):
        return self.env["ea.audit.designed.procedure"].sudo().search([
            ("engagement_id", "=", self.engagement.id), ("index_code", "=", index_code), ("code", "=", code),
        ])


@tagged("post_install", "-at_install")
class TestFixedAssetReconciliation(SubstantiveTwoCase):
    def test_register_against_the_ledger(self):
        self.significant("K", ["E", "V"])
        proc = self.code_proc("K", "K-M1")
        self.assertTrue(proc.selected)
        page = self.as_staff.ea_procedure_paper(proc.id)
        self.assertEqual((page["mode"], page["far"]["state"]), ("far", "no-register"))
        self.as_staff.create_dataset("fixed_asset_register", "far.csv", to_bytes(FAR_CSV), mapping=FAR_MAPPING)
        far = self.as_staff.ea_procedure_paper(proc.id)["far"]
        cost, dep, nbv = (far["sections"][name] for name in ("cost", "depreciation", "nbv"))
        # bought 2 January 2021 at 4,000, 2.5% a year: 400 depreciated before 2025, 100 in 2025
        row = cost["rows"][0]
        # rows by the register's account (owner, 2026-11-17), the category as information
        self.assertTrue(far["byAccount"])
        self.assertEqual((row["label"], row["opening"], row["additions"], row["closing"], row["ledger"], cost["state"]), ("231000", 4000, 0, 4000, 4000, "agrees"))
        self.assertEqual(row["categories"], ["Batiments"])
        row = dep["rows"][0]
        # the depreciation account worked out from the cost account: 231000 -> 2831
        self.assertEqual(row["label"], "2831")
        self.assertEqual((row["opening"], row["charge"], row["closing"], row["ledger"], row["difference"], dep["state"]), (400, 100, 500, 400, 100, "difference"))
        self.assertEqual((dep["charge"]["computed"], dep["charge"]["register"], dep["charge"]["registerDifference"]), (100, 100, 0))
        self.assertEqual((nbv["total"]["closing"], nbv["total"]["ledger"], nbv["total"]["difference"], nbv["state"]), (3500, 3600, -100, "difference"))
        page = self.as_staff.ea_procedure_paper(proc.id)
        self.assertTrue(page["toTick"]["explain"])
        for step in page["steps"]:
            self.as_staff.ea_proc_step(proc.id, step["index"], True)
        self.as_staff.ea_proc_save(proc.id, {"conclusion": "exceptions", "note": "Charge of 2025 not booked."})
        page = self.as_staff.ea_proc_far(proc.id, "The charge of 2025 is not booked in the ledger.", "depreciation")
        self.assertEqual(page["far"]["sections"]["depreciation"]["state"], "explained")
        with self.assertRaisesRegex(Exception, "procedure-not-finished"):
            self.as_staff.ea_proc_done(proc.id)
        self.as_staff.ea_proc_far(proc.id, "Same: the charge of 2025.", "nbv")
        self.as_staff.ea_proc_done(proc.id)
        self.assertEqual(proc.state, "done")

    def test_a_register_without_dates_asks_for_them(self):
        self.significant("K", ["E", "V"])
        proc = self.code_proc("K", "K-M1")
        dataset = self.as_staff.create_dataset("fixed_asset_register", "far.csv", to_bytes(FAR_CSV), mapping=FAR_MAPPING)["datasetId"]
        # an upload of before the mandatory columns: its matching has no date nor rate
        record = self.env["ea.audit.dataset"].sudo().browse(dataset)
        old = {key: value for key, value in record.mapping.items() if key not in ("acquisitionDate", "depreciationRate")}
        self.env.cr.execute("UPDATE ea_audit_dataset SET mapping = %s WHERE id = %s", [json.dumps(old), dataset])
        record.invalidate_recordset()
        far = self.as_staff.ea_procedure_paper(proc.id)["far"]
        self.assertEqual((far["state"], far["missingColumns"]), ("no-dates", ["acquisitionDate", "depreciationRate"]))

    def test_without_the_account_column_the_categories_stay(self):
        self.significant("K", ["E", "V"])
        proc = self.code_proc("K", "K-M1")
        mapping = {key: value for key, value in FAR_MAPPING.items() if key != "account"}
        self.as_staff.create_dataset("fixed_asset_register", "far.csv", to_bytes(FAR_CSV), mapping=mapping)
        far = self.as_staff.ea_procedure_paper(proc.id)["far"]
        self.assertFalse(far["byAccount"])
        self.assertEqual([row["label"] for row in far["sections"]["cost"]["rows"]], ["Batiments"])
        self.assertEqual(far["sections"]["cost"]["total"]["ledger"], 4000)

    def test_the_register_account_columns_and_its_own_amounts(self):
        self.significant("K", ["E", "V"])
        proc = self.code_proc("K", "K-M1")
        mapping = dict(FAR_MAPPING, depAccount="Compte amort", chargeAccount="Compte dotation", disposalsCost="Cessions brutes")
        self.as_staff.create_dataset("fixed_asset_register", "far.csv", to_bytes(FAR_ACCOUNTS), mapping=mapping)
        far = self.as_staff.ea_procedure_paper(proc.id)["far"]
        cost, dep = far["sections"]["cost"], far["sections"]["depreciation"]
        # an addition of 250 on a building bought in 2021: the register's amount is used, and noticed
        self.assertEqual((cost["rows"][0]["additions"], cost["rows"][0]["closing"], cost["rows"][0]["notices"]), (250, 4250, ["I1"]))
        self.assertEqual((far["noticeCount"], far["notices"]), (1, ["I1"]))
        self.assertEqual([(row["label"], row["ledger"]) for row in dep["rows"]], [("2831", 400)])
        self.assertTrue(far["byExpenseAccount"])
        self.assertEqual([(row["label"], row["computed"], row["ledger"]) for row in dep["charge"]["rows"]], [("6811", 100, 0)])


FAR_ACCOUNTS = """Numero;Designation;Categorie;Date acquisition;Taux;Compte;Compte amort;Compte dotation;Cout;Amortissements;VNC;VNC ouverture;Acquisitions;Cessions;Cessions brutes;Dotation
I1;Immeuble siege;Batiments;02/01/2021;2,5;231000;2831;6811;4000;500;3500;3600;250;0;;100
"""

FAR_MOVES = """Code;Designation;Categorie;Date acquisition;Taux;Compte;Cout;Date cession;Prix cession
I1;Immeuble siege;Batiments;02/01/2021;2,5;231000;4000;;
I2;Camion;Materiel;30/06/2025;20;245000;900;;
I3;Imprimante;Materiel;01/03/2025;25;244000;10;;
I4;Ancien camion;Materiel;01/01/2020;20;245000;200;30/09/2025;50
"""


@tagged("post_install", "-at_install")
class TestAdditionsAndDisposals(SubstantiveTwoCase):
    def test_the_sample_is_drawn_on_the_paper_and_vouched(self):
        self.significant("K", ["E", "V"])
        self.approve()
        proc = self.code_proc("K", "K-M2")
        self.assertTrue(proc.selected)
        self.assertEqual(self.as_staff.ea_procedure_paper(proc.id)["mode"], "vouch")
        # "Draw the sample" from the design opens this paper, where the sample is drawn
        action = self.as_staff.ea_procedure_draw(proc.id)
        self.assertEqual((action["type"], action["params"]["procedure_id"]), ("ir.actions.client", proc.id))
        with self.assertRaisesRegex(Exception, "no-dataset"):
            self.as_staff.ea_proc_vouch(proc.id, "draw")
        self.as_staff.create_dataset("fixed_asset_register", "far.csv", to_bytes(FAR_MOVES))
        page = self.as_staff.ea_proc_vouch(proc.id, "draw")
        vouch = page["vouch"]
        self.assertEqual((vouch["summary"]["additions"], vouch["summary"]["disposals"]), (2, 1))
        by_key = {item["key"]: item for item in vouch["items"]}
        # data rows 1 to 4: the truck bought in 2025 is above the threshold, a key item; the
        # building is no addition of the year
        self.assertEqual(by_key["A2"]["reason"], "key")
        self.assertNotIn("A1", by_key)
        run = proc.run_ids.filtered(lambda r: r.method == "vouch")
        self.assertEqual((len(run), run.designed_procedure_id), (1, proc))
        self.assertEqual(page["toTick"]["items"], len(vouch["items"]))
        page = self.as_staff.ea_proc_vouch(proc.id, "item", "A2", {"exists": "yes", "cost": "no", "note": "Invoice of 850."})
        item = next(i for i in page["vouch"]["items"] if i["key"] == "A2")
        self.assertEqual((item["state"], item["answers"]["cost"]), ("exception", "no"))
        self.assertEqual(run.item_results["A2"]["ok"], "no")
        with self.assertRaisesRegex(Exception, "selection-frozen"):
            self.as_staff.ea_proc_vouch(proc.id, "draw")
        with self.assertRaisesRegex(Exception, "invalid-value"):
            self.as_staff.ea_proc_vouch(proc.id, "item", "A2", {"removed": "yes"})
        page = self.as_staff.ea_proc_finding(proc.id, "Camion: cost does not agree to the invoice", amount=50, trivial_confirmed=True, item_key="vouch:A2")
        self.assertTrue(run.item_results["A2"]["finding"])
        self.assertTrue(page["findings"])
        sampling = self.as_staff.ea_sampling_page()
        card = next(c for c in sampling["tod"] if c["id"] == run.id)
        self.assertEqual(card["procedureId"], proc.id)


@tagged("post_install", "-at_install")
class TestCountAttendance(SubstantiveTwoCase):
    def test_before_during_after_and_both_directions(self):
        self.significant("F", ["E", "C"])
        proc = self.code_proc("F", "F-M1")
        page = self.as_staff.ea_procedure_paper(proc.id)
        self.assertEqual((page["mode"], page["steps"], page["count"]["hasListing"]), ("count", [], False))
        with self.assertRaisesRegex(Exception, "no-dataset"):
            self.as_staff.ea_proc_count(proc.id, "draw", None, {"size": 2})
        self.as_staff.create_dataset("inventory_listing", "stock.csv", to_bytes(STOCK_CSV), mapping=STOCK_MAPPING)
        page = self.as_staff.ea_proc_count(proc.id, "draw", None, {"size": 2})
        sheet = page["count"]["sheet"]
        self.assertEqual(len(sheet), 2)
        self.assertEqual((sheet[0]["item"], sheet[0]["reason"], sheet[0]["location"], sheet[0]["sheet"]), ("CB-016", "top", "Store A", 1200))
        run = proc._ea_count_run()
        self.assertEqual((run.method, run.designed_procedure_id), ("count", proc))
        page = self.as_staff.ea_proc_count(proc.id, "item", sheet[0]["key"], {"counted": "1199"})
        item = page["count"]["sheet"][0]
        self.assertEqual((item["difference"], item["state"]), (-1, "diff"))
        with self.assertRaisesRegex(Exception, "selection-frozen"):
            self.as_staff.ea_proc_count(proc.id, "draw", None, {"size": 3})
        self.as_staff.ea_proc_finding(
            proc.id, "CB-016: 1 unit short", amount="50", dr_account="603", cr_account="311", item_key="count:%s" % item["key"],
        )
        page = self.as_staff.ea_procedure_paper(proc.id)
        self.assertTrue(page["count"]["sheet"][0]["finding"])
        self.as_staff.ea_proc_count(proc.id, "item", sheet[1]["key"], {"counted": str(sheet[1]["sheet"])})
        page = self.as_staff.ea_proc_count(proc.id, "floor_add", None, {"item": "MB-02", "counted": "85"})
        self.assertEqual(page["count"]["floor"][0]["state"], "missing")
        page = self.as_staff.ea_proc_count(proc.id, "floor_update", 0, {"sheet": "85"})
        self.assertEqual(page["count"]["floor"][0]["state"], "ok")
        page = self.as_staff.ea_proc_count(proc.id, "roll", None, {"countDate": "2025-12-15", "count": "21000", "receipts": "1000", "issues": "200"})
        roll = page["count"]["roll"]
        self.assertTrue(roll["needed"] and roll["finalFromUpload"])
        self.assertEqual((roll["expected"], roll["final"], roll["difference"]), (21800, 21800, 0))
        self.as_staff.ea_proc_save(proc.id, {"conclusion": "exceptions", "note": "One shortage on cables."})
        with self.assertRaisesRegex(Exception, "procedure-not-finished"):
            self.as_staff.ea_proc_done(proc.id)
        for key in page["count"]["checks"]:
            page = self.as_staff.ea_proc_count(proc.id, "check", key, {"done": True})
        self.assertEqual(page["toTick"], {"steps": 0, "items": 0, "explain": False})
        self.as_staff.ea_proc_done(proc.id)
        self.assertEqual(proc.state, "done")
        # the Sampling page reads the test counts, answered on the working paper
        self.as_staff.ea_sampling_page()
