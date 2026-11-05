{
    "name": "AuditISA Firm Agent",
    "summary": "Heartbeat of a firm's server, its first administrator's one-time link, mail gate",
    "version": "19.0.1.0.0",
    "category": "Accounting/Audit",
    "license": "LGPL-3",
    "author": "AuditISA",
    # Deliberately no ea_audit_* dependency: the agent only counts, and reads no audit record.
    "depends": ["base", "web"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/first_admin_templates.xml",
        "views/access_log_views.xml",
    ],
    "installable": True,
}
