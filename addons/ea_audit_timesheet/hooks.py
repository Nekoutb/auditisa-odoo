INTERNAL_PROJECTS = ("Formation", "Congés", "Administration")


def post_init_hook(env):
    """Files that exist before the addon get their project, the firm its first internal ones."""
    env["ea.audit.engagement"].sudo().with_context(active_test=False).search([])._ea_ts_ensure_project()
    Project = env["project.project"].sudo()
    for name in INTERNAL_PROJECTS:
        if not Project.search_count([("ea_is_internal", "=", True), ("name", "=", name)]):
            Project._ea_ts_create_internal(name)
