{
    "name": "AuditISA Screens",
    "summary": "The firm's top bar, home, engagement dashboard and task lists, on the core models",
    "version": "19.0.1.0.0",
    "category": "Accounting/Audit",
    "license": "LGPL-3",
    "author": "AuditISA",
    "depends": ["ea_audit_core", "ea_audit_papers", "ea_audit_tools", "web", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/ea_audit_ui_rules.xml",
        "views/webclient_templates.xml",
        "views/actions.xml",
        "views/engagement_views.xml",
    ],
    "demo": [
        "demo/demo_data.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ea_audit_ui/static/src/scss/shell.scss",
            "ea_audit_ui/static/src/scss/grid.scss",
            "ea_audit_ui/static/src/js/**/*",
            "ea_audit_ui/static/src/xml/**/*",
        ],
    },
    "installable": True,
}
