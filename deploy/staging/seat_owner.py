# Run with `odoo shell`, the password file open on descriptor 3. staging-rebuild.sh does it.
# Same as /root/add_contact_user.py, except that an archived engagement is left alone: its immutability trigger
# refuses any new team member, which stopped that script on a copy holding an archived file.
# Prints ids and counts only.
import os

from odoo import fields

LOGIN = os.environ.get("SEAT_LOGIN", "contact@cm-ea.com")
with os.fdopen(3, encoding="utf-8") as handle:
    password = handle.read().strip()
assert len(password) >= 12, "the password file looks wrong"
Users = env["res.users"].sudo().with_context(no_reset_password=True, mail_create_nosubscribe=True, active_test=False)
user = Users.search([("login", "=", LOGIN)], limit=1)
groups = [(4, env.ref("base.group_user").id), (4, env.ref("ea_audit_core.group_firm_admin").id)]
if user:
    user.write({"group_ids": groups, "active": True})
else:
    user = Users.create({"name": "Contact CM-EA", "login": LOGIN, "email": LOGIN, "lang": "fr_FR",
                         "tz": "Africa/Douala", "group_ids": groups})
user.write({"password": password})
password = None
Member = env["ea.audit.team.member"].sudo()
Engagement = env["ea.audit.engagement"].sudo()
domain = [("archived_at", "=", False)] if "archived_at" in Engagement._fields else []
engagements = Engagement.search(domain)
added = 0
for engagement in engagements:
    row = Member.search([("engagement_id", "=", engagement.id), ("user_id", "=", user.id)], limit=1)
    if row:
        if row.state != "accepted":
            row.write({"state": "accepted"})
    else:
        Member.create({"engagement_id": engagement.id, "user_id": user.id, "team_role": "director",
                       "state": "accepted", "responded_at": fields.Datetime.now()})
        added += 1
env.cr.commit()
print("RESULT user", user.id, "missions", len(engagements), "added", added)
print("RESULT visible", env["ea.audit.engagement"].with_user(user).search_count([]))
