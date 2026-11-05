from odoo.exceptions import UserError

from . import controllers
from . import models
from . import wizard


def refuse_firm_database(env):
    """The control plane never shares a database with a firm: it would then sit beside audit data."""
    env.cr.execute(
        "SELECT name FROM ir_module_module WHERE name LIKE %s AND state IN ('installed', 'to install', 'to upgrade')",
        ["ea\\_audit%"],
    )
    found = [row[0] for row in env.cr.fetchall()]
    if found:
        raise UserError(
            "ea_platform_admin ne s'installe pas dans la base d'un cabinet. Modules trouvés : "
            + ", ".join(sorted(found))
        )
