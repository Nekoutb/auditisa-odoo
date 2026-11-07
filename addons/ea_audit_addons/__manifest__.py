{
    "name": "AuditISA Client Add-on Switches",
    "summary": "The per-firm switch of optional client add-ons: off hides them and keeps their data",
    "version": "19.0.1.0.0",
    "category": "Accounting/Audit",
    "license": "LGPL-3",
    "author": "AuditISA",
    # Deliberately no ea_audit_* dependency: this is a switch, and it reads no audit record.
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
    ],
    "installable": True,
}
