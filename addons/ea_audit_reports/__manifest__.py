{
    "name": "AuditISA Reports",
    "summary": "Completion gates, opinion and auditor's report, letters, archive, retention and legal hold, export bundle",
    "version": "19.0.1.0.0",
    "category": "Accounting/Audit",
    "license": "LGPL-3",
    "author": "AuditISA",
    "depends": ["ea_audit_tools", "ea_audit_papers", "web"],
    "data": [
        "security/ir.model.access.csv",
        "security/ea_audit_reports_rules.xml",
        "report/document_report.xml",
        "views/document_views.xml",
        "views/wizard_views.xml",
        "views/conclusion_views.xml",
        "views/company_views.xml",
    ],
    "assets": {
        "web.assets_backend": ["ea_audit_reports/static/src/scss/reports.scss"],
    },
    "post_init_hook": "post_init_hook",
    "application": False,
    "installable": True,
}
