{
    "name": "AuditISA Firm Agent",
    "summary": "Heartbeat of a firm's server, its first administrator's one-time link, mail gate",
    "version": "19.0.1.2.0",
    "category": "Accounting/Audit",
    "license": "LGPL-3",
    "author": "AuditISA",
    # No audit addon here: the agent only counts, and reads no audit record. ea_audit_addons is the
    # switch of optional add-ons, whose list of codes the heartbeat reports.
    "depends": ["base", "web", "ea_audit_addons"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/first_admin_templates.xml",
        "views/access_log_views.xml",
        "views/support_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ea_audit_firm_agent/static/src/js/report_problem.js",
        ],
    },
    "installable": True,
}
