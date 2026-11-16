"""Execution of the designed procedures (owner's mock-ups of 2026-11-16, mock-proc-exec-*): the
"Substantive procedures" page shows only what was designed; each procedure has its working paper,
with its steps, samples, the tool's work (reconciliation, cut-off), confirmations, evidence, a
conclusion and the findings raised from it."""
import base64

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

    def test_a_confirmations_block_can_be_added_anywhere(self):
        proc = self.proc("E-M4")
        page = self.as_staff.ea_procedure_paper(proc.id)
        self.assertIsNone(page["confirm"])
        self.assertTrue(page["canAddConfirm"])
        page = self.as_staff.ea_proc_confirm(proc.id, "enable")
        self.assertIsNotNone(page["confirm"])
        page = self.as_staff.ea_proc_confirm(proc.id, "add", None, {"party": "Lawyer Ndi", "book": "0"})
        self.assertEqual(page["confirm"]["rows"][0]["party"], "Lawyer Ndi")
