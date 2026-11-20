"""Opening Balance Testing (owner's mock-ups "obt" v4, 20/11/2026): upload, read or type, check, compare."""
import base64
import json
from unittest.mock import patch

from odoo.tests import tagged

from odoo.addons.ea_audit_tools.models import obt as obt_model
from odoo.addons.ea_audit_tools import obt_reading as obt_reader

from .common import ToolsCase

PDF = base64.b64encode(b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj\n").decode()

# The prior-year statements of BALANCED_CSV's opening balances, Customers 200 higher (a difference).
READING = {
    "year_end": "2024-12-31", "unit": "units", "signed": True, "column": "Net 2024",
    "lines": [
        {"ref": "AK", "amount": 4000, "page": 1}, {"ref": "AI", "amount": 4000, "page": 1},
        {"ref": "BI", "amount": 1000, "page": 1}, {"ref": "BS", "amount": 700, "page": 1},
        {"ref": "BZ", "amount": 5700, "page": 1},
        {"ref": "CA", "amount": 5000, "page": 2}, {"ref": "DJ", "amount": 700, "page": 2},
        {"ref": "DZ", "amount": 5700, "page": 2},
    ],
    "net_result_income_statement": None,
}


@tagged("post_install", "-at_install")
class TestOpeningBalanceTesting(ToolsCase):
    def setUp(self):
        super().setUp()
        self.import_tb()

    def page(self, actor=None):
        return (actor or self.as_staff).ea_obt_page()

    def upload(self):
        return self.as_staff.ea_obt_upload([{"name": "etats-2024.pdf", "content": PDF}])

    def read(self, reading=READING, key="sk-test"):
        with patch.object(obt_model, "read_key", return_value=key), \
                patch.object(obt_model, "reading_installed", return_value=True), \
                patch.object(obt_reader, "read", return_value=json.loads(json.dumps(reading))) as reader:
            page = self.as_staff.ea_obt_read()
        return page, reader

    def test_an_empty_page_starts_at_the_upload(self):
        page = self.page()
        self.assertEqual(page["step"], "upload")
        self.assertEqual(page["tb"]["file"], "balance.csv")
        self.assertFalse(page["reading"]["available"])   # no key on a test server
        self.assertFalse(self.env["ea.audit.obt"].sudo().search([("engagement_id", "=", self.engagement.id)]))

    def test_upload_read_check_confirm_and_the_differences(self):
        page = self.upload()
        self.assertEqual([f["name"] for f in page["files"]], ["etats-2024.pdf"])
        page, reader = self.read()
        files = reader.call_args.args[1]
        self.assertEqual(files[0][1], "application/pdf")
        self.assertTrue(files[0][2].startswith(b"%PDF"))
        self.assertEqual(page["step"], "check")
        rows = {row["ref"]: row for row in page["check"]["rows"]}
        self.assertEqual((rows["BI"]["amount"], rows["BI"]["page"]), (1000, 1))
        self.assertTrue(all(check["ok"] for check in page["check"]["checks"]))
        # a figure corrected keeps who corrected it
        page = self.as_staff.ea_obt_set("DJ", 700.0)
        page = self.as_staff.ea_obt_set("BI", 1000.0)
        self.assertFalse({row["ref"]: row for row in page["check"]["rows"]}["BI"]["corrected"])
        page = self.as_staff.ea_obt_confirm()
        result = page["result"]
        self.assertEqual(page["step"], "result")
        assets = {row["ref"]: row for row in result["assets"]}
        self.assertLessEqual({"AI", "AK", "AZ", "BG", "BI", "BK", "BT", "BS", "BZ"}, set(assets))
        self.assertNotIn("AE", assets)   # a line with nothing on either side is not shown
        self.assertFalse(assets["BI"]["agrees"])
        self.assertEqual(result["score"]["differences"], 2)    # BI and DJ
        self.assertEqual([d["ref"] for d in result["differences"]], ["BI", "DJ"])
        self.assertTrue(result["warning"])
        self.assertTrue(result["exportDifferencesUrl"])
        # warned on the tile and on E6.5
        self.assertIn("2", self.engagement.sudo()._ea_obt_warning())
        tile = self.env.ref("ea_audit_tools.tile_obt").with_user(self.staff).with_context(ea_engagement_id=self.engagement.id)
        self.assertIn("2", tile.upload_chip)
        # every difference appreciated: the warning goes
        self.as_staff.ea_obt_appreciate("BI", "Audit adjustment n°4 not posted in the books.")
        self.assertIn("1", self.engagement.sudo()._ea_obt_warning())
        page = self.as_staff.ea_obt_appreciate("DJ", "Same adjustment on the suppliers.")
        self.assertEqual(self.engagement.sudo()._ea_obt_warning(), "")
        self.assertEqual(page["result"]["differences"][0]["appreciation"], "Audit adjustment n°4 not posted in the books.")
        # an agreeing line takes no appreciation
        with self.assertRaises(Exception):
            self.as_staff.ea_obt_appreciate("CA", "x")

    def test_typed_by_hand_and_a_correction_after_a_reading(self):
        self.upload()
        page = self.as_staff.ea_obt_by_hand()
        self.assertEqual((page["step"], page["meta"]["source"]), ("check", "hand"))
        for ref, amount in (("AK", 4000), ("BI", 800), ("BS", 700), ("CA", 5000), ("DJ", 500)):
            page = self.as_staff.ea_obt_set(ref, amount)
        page = self.as_staff.ea_obt_confirm()
        self.assertEqual(page["result"]["score"]["differences"], 0)
        self.assertEqual(page["result"]["warning"], "")
        tile = self.env.ref("ea_audit_tools.tile_obt").with_user(self.staff).with_context(ea_engagement_id=self.engagement.id)
        self.assertTrue(tile.uploaded)
        # back to the statements, read, then a figure read and changed is marked
        self.as_staff.ea_obt_change()
        self.read()
        page = self.as_staff.ea_obt_set("BI", 800)
        row = {row["ref"]: row for row in page["check"]["rows"]}["BI"]
        self.assertTrue(row["corrected"])
        self.assertIn(self.staff.name, row["correctedBy"])

    def test_a_reading_problem_is_said_and_nothing_is_lost(self):
        self.upload()
        with patch.object(obt_model, "read_key", return_value="sk-test"), \
                patch.object(obt_reader, "read", side_effect=obt_reader.ReadingError("key_refused")):
            page = self.as_staff.ea_obt_read()
        self.assertEqual(page["step"], "upload")
        self.assertIn("key", page["meta"]["error"])
        self.assertEqual(len(page["files"]), 1)
        self.assertFalse(self.engagement.sudo()._ea_obt_record().line_ids)

    def test_the_uses_of_this_month_are_counted_for_the_console(self):
        self.upload()
        self.read()
        usage = json.loads(self.env["ir.config_parameter"].sudo().get_param(obt_model.PARAM_USAGE))
        self.assertEqual((usage["documents"], usage["pages"]), (1, 1))

    def test_who_may_change_it(self):
        with self.assertRaises(Exception):
            self.as_reader.ea_obt_upload([{"name": "a.pdf", "content": PDF}])
        with self.assertRaises(Exception):
            self.as_outsider.ea_obt_page()
        with self.assertRaises(Exception):
            self.as_eqr.ea_obt_by_hand()
        self.assertTrue(self.page(self.as_reader)["readonly"])
        with self.assertRaises(Exception):
            self.as_staff.ea_obt_upload([{"name": "notes.docx", "content": PDF}])
        # a record is never written through the plain ORM
        self.upload()
        record = self.env["ea.audit.obt"].with_user(self.staff).search([("engagement_id", "=", self.engagement.id)])
        with self.assertRaises(Exception):
            record.write({"step": "result"})

    def test_a_p_account_is_placed_once_for_the_client(self):
        self.import_tb(
            "Compte;Libellé;Solde ouverture débit;Solde ouverture crédit;Mouvement débit;Mouvement crédit\n"
            "101000;Capital;0;900;0;0\n218500;Frais;1000;0;0;0\n291900;Dépréciation;0;100;0;0\n"
            "601000;Achats;0;0;10;0\n701000;Ventes;0;0;0;10\n",
            filename="p.csv",
        )
        self.upload()
        self.as_staff.ea_obt_by_hand()
        self.as_staff.ea_obt_set("CA", 900)
        page = self.as_staff.ea_obt_confirm()
        self.assertEqual([item["account"] for item in page["result"]["choose"]], ["291900"])
        page = self.as_staff.ea_obt_place("291900", "AF")
        self.assertEqual(page["result"]["choose"], [])
        placement = self.env["ea.audit.obt.placement"].sudo().search([("client_id", "=", self.engagement.client_id.id)])
        self.assertEqual((placement.account, placement.ref), ("291900", "AF"))

    def test_the_extracts(self):
        self.upload()
        self.read()
        self.as_staff.ea_obt_confirm()
        name, content = self.as_staff.ea_export_xlsx("obt")
        self.assertTrue(name.startswith("opening-balance-testing") and content[:2] == b"PK")
        name, content = self.as_staff.ea_export_xlsx("obt_differences")
        self.assertTrue(name.startswith("opening-balance-differences") and content[:2] == b"PK")

    def test_e65_links_to_the_tool_with_its_warning(self):
        self.upload()
        self.read()
        self.as_staff.ea_obt_confirm()
        self.engagement.sudo()._ea_ensure_task("E6.5")
        item = self.env["ea.audit.file.item"].sudo().search([("engagement_id", "=", self.engagement.id), ("code", "=", "E6.5")], limit=1)
        item._ea_ensure_papers()
        # what the paper's screen receives: its Tools card
        payload = item.with_user(self.staff).get_paper_payload()
        link = next(link for link in payload["tools"] if link["en"] == "Opening Balance Testing")
        self.assertIn("2", link["note_en"])
        self.assertIn("écart", link["note_fr"])
        self.assertEqual(link["action"]["tag"], "ea_audit_tools.obt_page")
