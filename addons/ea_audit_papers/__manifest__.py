{
    "name": "AuditISA Working Papers",
    "summary": "Paper definitions, answers and history, review notes, conclusions, evidence and the paper renderer",
    "version": "19.0.1.5.0",
    "category": "Accounting/Audit",
    "license": "LGPL-3",
    "author": "AuditISA",
    "depends": ["ea_audit_core", "web", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "security/ea_audit_rules.xml",
        "data/paper_def_data.xml",
        "views/file_item_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ea_audit_papers/static/src/paper/**/*",
            "ea_audit_papers/static/src/docs/**/*",
        ],
    },
    "post_init_hook": "post_init_hook",
    "installable": True,
}
