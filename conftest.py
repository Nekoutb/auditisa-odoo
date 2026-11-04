"""Lets pytest import addons/<addon>/services without Odoo.

An addon's __init__.py imports its models, and those import Odoo. Importing a test from
addons/<addon>/services/tests/ would normally run that __init__.py first. Each addon is therefore
registered here as an empty package, so only services/ is executed. Services stay pure: stdlib
and requirements.txt only, relative imports inside the addon, nothing from odoo.
"""

import sys
import types
from pathlib import Path

ADDONS = Path(__file__).parent / "addons"

for manifest in ADDONS.glob("*/__manifest__.py"):
    addon = manifest.parent
    package = types.ModuleType(addon.name)
    package.__path__ = [str(addon)]
    sys.modules.setdefault(addon.name, package)
