{
    "name": "AuditISA Pipeline",
    "summary": "Development, staging, production for the Odoo tool: promotion, rollback, anonymised staging rebuild. Control plane only.",
    "version": "19.0.1.1.0",
    "category": "Administration",
    "license": "LGPL-3",
    "author": "AuditISA",
    # Control plane only, like ea_platform_admin: build_release.sh leaves every ea_platform_* out of the
    # bundle a firm receives, and firm-update.sh refuses a bundle that holds one.
    "depends": ["ea_platform_admin"],
    "data": [
        "security/ir.model.access.csv",
        "data/pipeline_data.xml",
        "data/environment_data.xml",
        "views/pipeline_views.xml",
        "views/firm_views.xml",
        "wizard/confirm_views.xml",
        "views/environment_views.xml",
        "views/menus.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "ea_platform_pipeline/static/src/scss/pipeline.scss",
            "ea_platform_pipeline/static/src/scss/environments.scss",
        ],
    },
    "installable": True,
}
