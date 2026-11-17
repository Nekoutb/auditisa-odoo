"""Plain pytest, no Odoo: the manual's tools (static/manual/tools) go on the path, standard library only."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static", "manual", "tools"))
