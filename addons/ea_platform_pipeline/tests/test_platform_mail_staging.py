"""The staging server (test.auditisa.com) never sends email: it never gets a platform address."""

import os
import tempfile

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.ea_platform_admin.tests.common import PlatformCase


@tagged("post_install", "-at_install")
class TestStagingNeverSends(PlatformCase):
    def test_the_staging_server_is_refused_a_platform_address(self):
        self.env["ir.config_parameter"].sudo().set_param("ea_platform.mail_parent_domain", "cm-ea.com")
        with tempfile.TemporaryDirectory() as folder:
            staging = self.env["platform.firm"]._pipeline_enrol_staging(os.path.join(folder, "token"))
        with self.assertRaisesRegex(UserError, "never sends email"):
            staging.with_user(self.operator).action_pmail_give()
        self.assertEqual(staging.pmail_state, "none")

