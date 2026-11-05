{
    "name": "AuditISA OHADA Legal Register",
    "summary": "Statutory deadlines, regulated agreements, art. 715 report, alert procedure, criminal facts, securities attestation, equity monitoring, joint auditor file, art. 525 certification",
    "version": "19.0.1.0.0",
    "category": "Accounting/Audit",
    "license": "LGPL-3",
    "author": "AuditISA",
    "depends": ["ea_audit_reports"],
    "data": [
        "security/ir.model.access.csv",
        "security/ea_audit_legal_rules.xml",
        "data/cron.xml",
        "views/legal_views.xml",
        "views/wizard_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "application": False,
    "installable": True,
}
