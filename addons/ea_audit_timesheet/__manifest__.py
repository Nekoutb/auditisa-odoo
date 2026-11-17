{
    "name": "AuditISA Time and Firm Administration",
    "summary": "Feuille de temps on hr_timesheet with the firm's weekly deadline; the firm administrator's users and mail screens",
    "version": "19.0.1.0.1",
    "category": "Accounting/Audit",
    "license": "LGPL-3",
    "author": "AuditISA",
    "depends": ["ea_audit_ui", "hr", "project", "hr_timesheet", "auth_signup"],
    "data": [
        "security/ir.model.access.csv",
        "security/rules.xml",
        "data/auth_signup.xml",
        "views/actions.xml",
        "views/report_views.xml",
        "views/engagement_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ea_audit_timesheet/static/src/scss/timesheet.scss",
            "ea_audit_timesheet/static/src/js/**/*",
            "ea_audit_timesheet/static/src/xml/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
}
