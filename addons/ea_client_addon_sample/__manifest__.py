{
    "name": "SAMPLE: Client notes",
    "summary": "Sample client add-on, to prove the path: a small notes screen. Not a product feature.",
    "version": "19.0.1.0.0",
    "category": "Accounting/Audit",
    "license": "LGPL-3",
    "author": "AuditISA",
    "depends": ["ea_audit_addons"],
    "data": [
        "security/feature.xml",
        "security/ir.model.access.csv",
        "views/note_views.xml",
    ],
    "installable": True,
    # This line is what makes an add-on optional, per firm. See docs/runbook/CLIENT-ADDONS.md.
    "ea_client_addon": True,
    "ea_client_addon_sample": True,
}
