"""Plain pytest, no Odoo. The core's services package imports Odoo in its __init__, so the
decision tree is loaded straight from its file: it uses the standard library only."""
import importlib.util
import os
import sys

_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "services", "engagement_profile.py")
_spec = importlib.util.spec_from_file_location("engagement_profile", _PATH)
engagement_profile = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(engagement_profile)
sys.modules["engagement_profile"] = engagement_profile
