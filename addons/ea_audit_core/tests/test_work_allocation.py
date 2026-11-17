"""Work allocation (owner's mock-up of 2026-11-18): partner approval set by itself, the reviewer who
is also the preparer refused, a person below the minimum saved with a warning, signatures untouched."""
from odoo.tests import tagged

from .common import EaAuditCase


@tagged("post_install", "-at_install")
class TestWorkAllocation(EaAuditCase):
    def setUp(self):
        super().setUp()
        self.outputs_exist()
        self.engagement = self.make_engagement()
        for user, role in ((self.manager, "manager"), (self.senior, "senior"), (self.staff, "staff")):
            self.seat(self.engagement, user, role)
        self.as_manager = self.engagement.with_user(self.manager)
        self.e44 = self.item(self.engagement, "E4.4")

    def trail(self, action):
        return self.env["ea.audit.activity"].sudo().search([
            ("engagement_id", "=", self.engagement.id), ("action", "=", action),
        ])

    def live_signoffs(self, item):
        return item.signoff_ids.filtered(lambda s: not s.voided_at and not s.invalidated_at)

    # ------------------------------------------------------------------ partner approval

    def test_partner_approval_goes_to_the_engagement_partner_by_itself(self):
        for item in self.engagement.sudo().file_item_ids:
            required = self.Policy._ea_effective_rule(item.code)["partner_required"]
            self.assertEqual(item.partner_approver_id, self.partner if required else self.env["res.users"], item.code)
        self.assertEqual(self.item(self.engagement, "P1.1").partner_approver_id, self.partner)
        self.assertFalse(self.e44.partner_approver_id)
        # nobody types it in
        self.assertCode("forbidden", self.e44.with_user(self.manager).write, {"partner_approver_id": self.partner.id})

    def test_a_task_that_comes_onto_the_file_later_goes_to_the_partner(self):
        self.engagement.with_user(self.partner).write({"joint_auditors": "yes"})
        c59 = self.item(self.engagement, "C5.9")
        self.assertFalse(c59.conditional)
        self.assertEqual(c59.partner_approver_id, self.partner)
        # a task created on the file (a scope change) after the firm asked the partner's approval on it
        self.TaskRule.with_user(self.partner).save_task_rules([
            {"code": "P4.2", "min_preparer": None, "min_reviewer": None, "partner_required": True},
        ])
        self.assertFalse(self.item(self.engagement, "P4.2"))
        template = self.env["ea.audit.task.template"].sudo().search([("code", "=", "P4.2")])
        item = self.env["ea.audit.file.item"].sudo().create({"engagement_id": self.engagement.id, "template_id": template.id})
        self.assertEqual(item.partner_approver_id, self.partner)

    def test_transferring_the_partner_role_moves_partner_approval(self):
        self.engagement.with_user(self.partner).transfer_engagement_partner(self.partner2.id, "director")
        items = self.engagement.sudo().file_item_ids
        self.assertEqual(self.item(self.engagement, "P1.1").partner_approver_id, self.partner2)
        self.assertFalse(items.filtered(lambda i: i.partner_approver_id == self.partner))
        self.assertTrue(self.trail("partner_approval_assigned"))

    # ------------------------------------------------------------------ saving

    def test_the_reviewer_cannot_be_the_preparer(self):
        self.assertCode(
            "preparer-equals-approver", self.as_manager.ea_allocate_tasks,
            [{"id": self.e44.id, "preparer_id": self.senior.id, "approver_id": self.senior.id}],
        )
        self.assertFalse(self.e44.preparer_id or self.e44.approver_id)

    def test_below_the_minimum_warns_but_saves(self):
        s31 = self.item(self.engagement, "S3.1")  # a senior or above prepares, a manager or above reviews
        result = self.as_manager.ea_allocate_tasks([
            {"id": s31.id, "preparer_id": self.staff.id, "approver_id": self.senior.id},
        ])
        self.assertEqual((s31.preparer_id, s31.approver_id), (self.staff, self.senior))
        self.assertEqual(
            {(w["box"], w["role"]) for w in result["warnings"]}, {("preparer", "senior"), ("reviewer", "manager")},
        )
        self.assertTrue(self.trail("tasks_assigned"))
        # signing still follows the sign-off policy
        self.set_phase(self.engagement, "execution")
        self.assertCode("role-below-task-minimum-senior", self.sign, self.staff, self.engagement, "S3.1", "preparer")
        # and the tasks screen keeps its refusal
        self.assertCode(
            "role-below-task-minimum-senior", self.item(self.engagement, "S4.1").with_user(self.manager).assign_tasks,
            self.staff.id, "preparer",
        )

    def test_preparer_and_reviewer_swap_in_one_save(self):
        self.as_manager.ea_allocate_tasks([{"id": self.e44.id, "preparer_id": self.senior.id, "approver_id": self.manager.id}])
        self.as_manager.ea_allocate_tasks([{"id": self.e44.id, "preparer_id": self.manager.id, "approver_id": self.senior.id}])
        self.assertEqual((self.e44.preparer_id, self.e44.approver_id), (self.manager, self.senior))

    def test_reallocating_never_touches_a_signature(self):
        self.as_manager.ea_allocate_tasks([{"id": self.e44.id, "preparer_id": self.staff.id, "approver_id": self.senior.id}])
        signature = self.env["ea.audit.signoff"].sudo().create({
            "file_item_id": self.e44.id, "kind": "workpaper", "role": "preparer", "user_id": self.staff.id,
        })
        self.e44.sudo().state = "prepared"
        self.as_manager.ea_allocate_tasks([{"id": self.e44.id, "preparer_id": self.senior.id, "approver_id": self.manager.id}])
        self.assertEqual(self.live_signoffs(self.e44), signature)
        self.assertEqual(self.e44.state, "prepared")
        self.assertEqual(self.e44.preparer_id, self.senior)

    def test_only_the_partner_and_the_managers_allocate(self):
        change = [{"id": self.e44.id, "preparer_id": self.staff.id}]
        self.assertCode("team-manager-only", self.engagement.with_user(self.senior).ea_allocate_tasks, change)
        self.assertEqual(self.engagement.with_user(self.partner).ea_allocate_tasks(change)["saved"], 1)
        # only accepted members of the team, never the quality reviewer
        self.seat(self.engagement, self.partner3, "senior", state="invited")
        self.assertCode("not-found", self.as_manager.ea_allocate_tasks, [{"id": self.e44.id, "approver_id": self.partner3.id}])
        self.assertCode("not-found", self.as_manager.ea_allocate_tasks, [{"id": self.e44.id, "approver_id": self.outsider.id}])
        other = self.make_engagement(2024)
        self.assertCode("not-found", self.as_manager.ea_allocate_tasks, [{"id": self.item(other, "E4.4").id, "preparer_id": False}])
