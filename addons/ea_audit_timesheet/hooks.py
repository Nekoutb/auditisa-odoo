INTERNAL_PROJECTS = (
    ("Training", "Formation"),
    ("Leave", "Congés"),
    ("Administration", "Administration"),
)


def post_init_hook(env):
    """Files that exist before the addon get their project, the firm its first internal
    ones, named in both languages (a project's name is translatable data)."""
    env["ea.audit.engagement"].sudo().with_context(active_test=False).search([])._ea_ts_ensure_project()
    # hr_timesheet's installation leaves two zero-hour "Analysis" lines on its own project
    env.cr.execute("DELETE FROM account_analytic_line WHERE project_id IS NOT NULL AND unit_amount = 0 AND name = 'Analysis'")
    env["res.lang"]._activate_lang("fr_FR")
    Project = env["project.project"].sudo().with_context(lang="en_US")
    for name, french in INTERNAL_PROJECTS:
        if not Project.search_count([("ea_is_internal", "=", True), ("name", "=", name)]):
            project = Project._ea_ts_create_internal(name)
            project.update_field_translations("name", {"fr_FR": french})
