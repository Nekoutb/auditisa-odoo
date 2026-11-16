"""Plain pytest, no Odoo: the addon folder goes on the path and ``services`` is imported
as a top-level package, so the addon's own __init__ (which will import Odoo) never runs."""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
