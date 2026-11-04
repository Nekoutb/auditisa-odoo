"""Plain pytest, no Odoo: `pytest addons/ea_audit_papers/tests/pure`. The services package
is imported on its own so that the addon's __init__.py (and Odoo) is never loaded."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
