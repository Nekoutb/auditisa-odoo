def post_init_hook(env):
    """Tasks that existed before the addon get their paper."""
    env["ea.audit.file.item"].sudo().search([])._ea_ensure_papers()
