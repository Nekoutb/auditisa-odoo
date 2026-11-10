"""No more release signatures and no more 7-day wait on practice (owner's decision of 2026-11-10).

Drops the offline attestation of each release and the "practice wait skipped" record of each promotion.
A promotion that is still a draft keeps everything else; its pre-checks run again when it is started.
Each step does nothing if it was already done.
"""

COLUMNS = {
    "platform_release": ("attestation",),
    "platform_pipeline_promotion": (
        "hold_override", "hold_override_reason", "hold_override_by_id", "hold_override_at",
    ),
}


def migrate(cr, version):
    for table, columns in COLUMNS.items():
        for column in columns:
            cr.execute(f'ALTER TABLE IF EXISTS "{table}" DROP COLUMN IF EXISTS "{column}" CASCADE')
    # Pre-checks recorded under the old rules (signature, 7 days) do not hold any more.
    cr.execute("SELECT to_regclass('platform_pipeline_promotion')")
    if cr.fetchone()[0]:
        cr.execute("UPDATE platform_pipeline_promotion SET checks_ok = FALSE WHERE state = 'draft'")
