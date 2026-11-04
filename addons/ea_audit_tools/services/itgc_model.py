"""lib/itgc-model.ts: the S2.3/S2.5 IT-applications board's key rule."""
import re

IT_STRATEGIES = ["rely_itgc", "test_direct", "substantive_only"]


def new_app_key(name):
    """The stable key of an application: the slug of its name at creation."""
    slug = re.sub("[^a-z0-9]+", "-", name.lower())
    return slug.strip("-")[:40] or "app"
