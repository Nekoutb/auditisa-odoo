{
    "name": "AuditISA Client Portal",
    "summary": "List of documents requested from the client, and their uploads by client contacts invited by a one-time link",
    "version": "19.0.1.0.1",
    "category": "Accounting/Audit",
    "license": "LGPL-3",
    "author": "AuditISA",
    "depends": ["ea_audit_reports", "portal"],
    "data": [
        "security/ir.model.access.csv",
        "security/ea_audit_portal_rules.xml",
        "data/auth_signup.xml",
        "views/pbc_views.xml",
        "views/portal_templates.xml",
    ],
    "post_init_hook": "post_init_hook",
    "application": False,
    "installable": True,
}
