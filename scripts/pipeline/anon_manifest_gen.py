#!/usr/bin/env python3
"""Writes deploy/firm/anon-manifest.json from a database's columns and the policy below.

    # Against a database with every addon of the release installed:
    psql -X -At -F$'\\t' -c "<COLUMNS_SQL>"    NAME > columns.tsv
    psql -X -At -F$'\\t' -c "<SELECTIONS_SQL>" NAME > selections.tsv
    psql -X -At -c "SELECT model FROM ir_model ORDER BY 1" NAME > models.txt
    # Then, on your computer:
    scripts/pipeline/anon_manifest_gen.py columns.tsv selections.tsv models.txt deploy/firm/anon-manifest.json

Run it when a release adds a table or a text column: the export stops until it is listed, on purpose.
Read the diff: a table this script does not name in REFERENCE or PURGE, and is not a wizard, becomes
`firm`, so its text is replaced. That is the safe side, but it may break a screen on staging. A table
in REFERENCE keeps its text as it is, so nothing a firm can type belongs there; the final scan still
reads it.
"""

import json
import re
import sys
from pathlib import Path

COLUMNS_SQL = """
SELECT c.table_name, c.column_name, c.data_type, coalesce(f.ttype, ''), coalesce(f.model, ''), coalesce(m.transient::text, '')
  FROM information_schema.columns c
  JOIN information_schema.tables t ON t.table_schema = c.table_schema AND t.table_name = c.table_name AND t.table_type = 'BASE TABLE'
  LEFT JOIN (SELECT model, transient, replace(model, '.', '_') tbl FROM ir_model) m ON m.tbl = c.table_name
  LEFT JOIN ir_model_fields f ON f.model = m.model AND f.name = c.column_name
 WHERE c.table_schema = 'public' ORDER BY 1, c.ordinal_position
"""
SELECTIONS_SQL = """
SELECT f.model, f.name, count(s.id) FROM ir_model_fields f LEFT JOIN ir_model_fields_selection s ON s.field_id = f.id
 WHERE f.ttype = 'selection' AND f.store GROUP BY 1, 2
"""

# Defined by the modules, the same at every firm. Kept as they are, and still searched.
REFERENCE = {
    "decimal_precision", "digest_digest", "digest_tip", "ir_act_client", "ir_act_report_xml", "ir_act_server",
    "ir_act_url", "ir_act_window", "ir_act_window_view", "ir_actions", "ir_actions_todo", "ir_asset", "ir_cron",
    "ir_config_parameter", "ir_embedded_actions", "ir_model", "ir_model_access", "ir_model_constraint", "ir_model_data",
    "ir_model_fields", "ir_model_fields_selection", "ir_model_inherit", "ir_model_relation", "ir_module_category",
    "ir_module_module", "ir_module_module_dependency", "ir_module_module_exclusion", "ir_rule", "ir_sequence",
    "ir_ui_menu", "ir_ui_view", "iap_service", "hr_contract_type", "hr_departure_reason", "hr_payroll_structure_type",
    "hr_resume_line_type", "mail_activity_type", "mail_message_subtype", "mail_template", "properties_base_definition",
    "report_layout", "report_paperformat", "res_country", "res_country_group", "res_country_state", "res_currency",
    "res_groups", "res_groups_privilege", "res_lang", "res_partner_industry", "resource_calendar",
    "resource_calendar_attendance", "sms_template", "spreadsheet_dashboard", "spreadsheet_dashboard_group",
    "uom_uom", "web_tour_tour", "web_tour_tour_step", "account_analytic_plan", "account_analytic_applicability",
    # The product's own definitions.
    "ea_audit_assertion", "ea_audit_paper_def", "ea_audit_task_template", "ea_audit_tool_tile", "ea_audit_wp_template",
    "ea_audit_grouping_rule", "ea_audit_public_holiday", "ea_audit_signoff_policy", "ea_audit_signoff_task_rule",
}

# Rows that all go: chatter, logs, files, sessions, credentials. Nothing here is a figure.
PURGE = {
    "account_analytic_distribution_model", "auth_passkey_key", "ir_default", "mail_canned_response", "mail_ice_server",
    "mail_gateway_allowed", "auth_totp_device", "base_import_mapping", "bus_bus",
    "discuss_call_history", "discuss_channel", "discuss_channel_member", "discuss_channel_rtc_session",
    "discuss_gif_favorite", "discuss_voice_metadata", "fetchmail_server", "html_editor_converter_test",
    "html_editor_converter_test_sub", "iap_account", "ir_actions_server_history", "ir_attachment", "ir_cron_progress",
    "ir_cron_trigger", "ir_exports", "ir_exports_line", "ir_filters", "ir_logging", "ir_mail_server", "ir_profile",
    "ir_sequence_date_range", "ir_ui_view_custom", "mail_activity", "mail_alias_domain", "mail_blacklist", "mail_followers",
    "mail_guest", "mail_link_preview", "mail_mail", "mail_message", "mail_message_link_preview", "mail_message_reaction",
    "mail_message_schedule", "mail_message_translation", "mail_notification", "mail_presence", "mail_push",
    "mail_push_device", "mail_scheduled_message", "mail_tracking_value", "phone_blacklist", "privacy_log",
    "rating_rating", "res_device_log", "res_users_apikeys", "res_users_deletion", "res_users_log", "res_users_settings",
    "res_users_settings_embedded_action", "res_users_settings_volumes", "sms_sms", "sms_tracker", "snailmail_letter",
    "spreadsheet_dashboard_share",
    # The firm's own logs and alerts name people and addresses.
    "ea_audit_firm_log", "ea_firm_access_log", "ea_audit_notification", "ea_audit_notice",
}

# Column rules in firm tables, first match wins. The default is `text`: replaced.
BY_NAME = [
    (r"(^|_)(password|passwd|secret|token|totp|apikey|api_key|private_key|invite_digest|signup_type)($|_)", "null"),
    (r"(email_normalized|email_cc|email_from|email_to|reply_to|work_email|private_email|^email$|_email$)", "email"),
    (r"(^|_)(phone|mobile|fax)($|_)", "phone"),
    (r"^(vat|niu|ssnid|sinid|passport_id|permit_no|visa_no|identification_id|barcode|pin|company_registry|registration_number|"
     r"acc_number|sanitized_acc_number|acc_holder_name|account_token|tax_number|ref|bank_acc_number|bic)$", "idnum"),
    (r"^(website|.*_url|url|image_url|avatar_url|.*_link)$", "null"),
    (r"(^|_)(sha256|content_hash|checksum|digest)$", "hash"),
    (r"^(preparer|reviewer|approver|actor_name|target_name|display_name_typed|owner|recipient|intermediary_name|"
     r"interested|parties|contact_name|emergency_contact)$", "person"),
]

# Kept when it matches, replaced when it does not.
PATTERNS = {
    "ACCOUNT": {"re": r"^[0-9][0-9.\-]{0,31}$", "else": "digits"},
    "CODE": {"re": r"^[A-Z]{1,4}[0-9]{0,4}([._\-][A-Za-z0-9]{1,12}){0,4}$"},
    "FIELD_KEY": {"re": r"^([a-zA-Z][a-zA-Z0-9]{0,6}(_[A-Za-z0-9]{1,24}){1,6}|[a-z][0-9]{1,3})$"},
    "WORD": {"re": r"^[a-z][a-z0-9_\-]{0,47}$"},
    "HEX": {"re": r"^[0-9a-f]{16,64}$", "else": "blank"},
    "MIME": {"re": r"^[a-z]+/[a-z0-9.+\-]{1,80}$", "else": "blank"},
    "CURRENCY": {"re": r"^[A-Z]{3}$", "else": "blank"},
    "COUNTRY": {"re": r"^[A-Z]{2}$", "else": "blank"},
    "LANG": {"re": r"^[a-z]{2,3}(_[A-Z]{2})?(@[a-z]+)?$", "else": "blank"},
    "TZ": {"re": r"^[A-Za-z_]+(/[A-Za-z_\-]+){0,2}$", "else": "blank"},
    "COLOR": {"re": r"^#[0-9a-fA-F]{3,8}$", "else": "blank"},
    "MODEL": {"re": r"^[a-z][a-z0-9_.]{0,63}(,[0-9]{1,12})?$", "else": "blank"},
    # A selection whose values Odoo works out at run time: one token, no space.
    "TOKEN": {"re": r"^[A-Za-z0-9_.:/+\-]{1,64}$", "else": "blank"},
    "TREE_PATH": {"re": r"^([0-9]{1,12}/){1,64}$", "else": "blank"},
}

KEEP_BY_NAME = {
    "index_code": "CODE", "sub_index": "CODE", "section_code": "CODE", "fs_ref": "CODE", "source_code": "CODE",
    "code": "CODE", "fn": "CODE", "ref": "CODE",
    "field_key": "FIELD_KEY", "key": "FIELD_KEY", "journal_code": "CODE",
    "account": "ACCOUNT", "account_code": "ACCOUNT", "account_prefix": "ACCOUNT", "dr_account": "ACCOUNT", "cr_account": "ACCOUNT",
    "definition_hash": "HEX", "mime": "MIME", "mimetype": "MIME", "currency": "CURRENCY", "country": "COUNTRY",
    "res_model": "MODEL", "model": "MODEL", "res_name": "text",
    "lang": "LANG", "tz": "TZ", "primary_color": "COLOR", "secondary_color": "COLOR",
    "assertion": "WORD", "framework": "WORD", "engine": "WORD", "method": "WORD", "stage": "WORD", "source": "WORD",
    "tod_level": "WORD", "cra_level": "WORD", "group": "WORD", "unit": "WORD", "account_type": "WORD",
    "account_class": "WORD", "version_kind": "WORD", "rule": "WORD", "seed": "WORD", "extent": "WORD",
    "ir_basis": "WORD", "cr_basis": "WORD", "layers": "WORD",
    "notification_type": "WORD", "email_formatted": "email", "parent_path": "TREE_PATH",
    "email_primary_color": "COLOR", "email_secondary_color": "COLOR",
}

# By `table.column`, ahead of everything above.
EXACT = {
    "res_partner.name": "party",
    "res_partner.complete_name": "party",
    "res_partner.display_name": "party",
    "res_partner.commercial_company_name": "company",
    "res_partner.company_name": "company",
    "res_company.name": "company",
    "res_bank.name": "company",
    "ea_audit_client.name": "company",
    "ea_audit_client.niu": "idnum",
    "ea_audit_client.registration_number": "idnum",
    "ea_audit_portal_contact.name": "person",
    "ea_audit_gl_line.third_party_name": "company",
    "ea_audit_gl_line.third_party_code": "idnum",
    "ea_audit_scot_control.owner": "person",
    "hr_employee.name": "person",
    "hr_employee.work_contact_id": "text",
    "resource_resource.name": "person",
    "res_users.login": "login",
    "ea_audit_paper_answer.value": "answer",
    "ea_audit_paper_answer_history.before": "answer",
    "ea_audit_paper_answer_history.after": "answer",
    "mail_alias.alias_defaults": "emptydict",
    "mail_alias.alias_name": "null",
    "mail_alias.alias_full_name": "null",
    "ea_audit_document.code": "keep:CODE",
    "ea_audit_automation_run.title": "text",
    "ea_audit_notice.title": "text",
}

# Searched for, though its rule is `text`: these name the client without being a person or company rule.
HARVEST_ALSO = [
    "ea_audit_engagement.name", "ea_audit_client.address", "res_partner.street", "res_partner.street2",
    "hr_employee.name", "hr_employee.private_street", "resource_resource.name", "ea_audit_portal_contact.name",
    "ea_audit_gl_line.preparer", "ea_audit_gl_line.reviewer", "ea_audit_gl_line.approver",
]
# Rows that go, but whose names may have been copied somewhere that is kept.
HARVEST_PURGED = {
    "ea_audit_firm_log": ["actor_name", "target_name"],
    "mail_message": ["email_from", "author_guest_name"],
    "mail_mail": ["email_to"],
}
# Words of Odoo and of the product that would match in every view, whoever the firm is.
HARVEST_IGNORE = [
    "OdooBot", "Administrator", "Public user", "Default User Template", "Portal User Template", "Mitchell Admin",
    "Marc Demo", "Joel Willis", "My Company", "YourCompany", "Paris", "Douala", "Yaoundé", "Cameroon", "Cameroun",
    "France", "example.com", "odoo.com",
    # Odoo's own sample partners, quoted in its view and mail templates. They are on a demo database only.
    "Brandon Freeman", "Lumber Inc", "Audrey Peterson", "Acme Corporation", "info@yourcompany.com",
    "mark.brown23@example.com", "Renovations", "Rénovations", "Pleasant Hill", "Brisbane", "Reserve",
]
# External ids of our addons on these models are removed: they can spell a person's or a client's name.
XMLID_SCRUB_MODELS = [
    "res.partner", "res.users", "hr.employee", "resource.resource", "res.company", "ea.audit.client", "ea.audit.engagement",
    "ea.audit.team.member", "ea.audit.portal.contact", "project.project", "project.task",
]
# Tokens free text may keep: the answers a paper records.
SAFE_WORDS = [
    "yes", "no", "na", "n/a", "oui", "non", "true", "false", "none", "low", "medium", "moderate", "high",
    "effective", "ineffective", "support", "recurring", "passed", "failed", "warning", "ok", "ko", "done", "open",
]
# Column headers of an imported ledger or trial balance: they stay, so rows remain readable.
JSON_KEY_WORDS = [
    "Date", "Compte", "Débit", "Crédit", "Journal", "Libellé", "Approuvé", "Intitulé", "Préparé", "Référence",
    "N° écriture", "Mouvement débit", "Mouvement crédit", "Solde ouverture débit", "Solde ouverture crédit",
    "Solde clôture débit", "Solde clôture crédit", "Tiers", "Montant", "Centre de coût", "Pièce", "Lettrage", "Solde",
    "Account", "Debit", "Credit", "Description", "Reference", "Amount", "Balance", "Name",
]
CONFIG_KEEP = [
    r"analytic\.project_plan", r"auth_signup\.(invitation_scope|reset_password)", r"base\.default_max_email_size",
    r"base\.login_cooldown_(after|duration)", r"base_setup\.show_effect", r"base\.template_portal_user_id",
    r"database\.create_date", r"digest\.default_digest_(emails|id)", r"mail\.activity\.gc\.delete_overdue_years",
    r"mail\.restrict\.template\.rendering",
]
SCAN = {
    "email_domains_allowed": [],  # Filled below from what the module data shows.
    "patterns": {
        "tax-number": r"\b[MPAS][0-9]{12}[A-Z]\b",
        "cameroon-phone": r"(?<![0-9])\+?237[ .\-]?[26][0-9]([ .\-]?[0-9]){7}(?![0-9])",
        "trade-register": r"\bRC/[A-Z]{3}/[0-9]{4}/[A-Z]/[0-9]+\b",
        "bank-account": r"\b[A-Z]{2}[0-9]{2}[A-Z0-9 ]{14,30}[0-9]\b",
    },
    "ignore": {},
}
ALLOWED_DOMAINS = [
    "anon.invalid", "example.com", "example.org", "odoo.com", "yourcompany.com", "yourcompany.example.com",
    "domain.com", "email.com", "company.com", "gmail.com", "outlook.com", "microsoft.com",
    # In the authors' lines and examples of the modules Odoo ships.
    "26house.com", "osbzr.com", "e-mail.com",
]


def rule_for(table, column, data_type, ttype, dynamic_selection):
    exact = EXACT.get(f"{table}.{column}")
    if exact:
        return exact
    if data_type == "bytea":
        return "null"
    if data_type in ("jsonb", "json"):
        return "json"
    if ttype == "selection":
        return "keep:TOKEN" if dynamic_selection else "sel"
    if ttype == "html":
        return "html"
    keep = KEEP_BY_NAME.get(column)
    if keep:
        return f"keep:{keep}" if keep in PATTERNS else keep
    for pattern, rule in BY_NAME:
        if re.search(pattern, column):
            return rule
    return "text"


def main(columns_tsv, selections_tsv, models_txt, output):
    dynamic = set()
    for line in Path(selections_tsv).read_text(encoding="utf-8").splitlines():
        model, field, count = line.split("\t")
        if count == "0":
            dynamic.add((model, field))
    inventory, meta, transient = {}, {}, {}
    for line in Path(columns_tsv).read_text(encoding="utf-8").splitlines():
        table, column, data_type, ttype, model, is_transient = line.split("\t")[:6]
        inventory.setdefault(table, {})[column] = data_type
        meta[(table, column)] = (ttype, (model, column) in dynamic)
        if is_transient:
            transient[table] = is_transient == "true"
    tables = {}
    for table, columns in sorted(inventory.items()):
        inspected = {name: kind for name, kind in columns.items()
                     if kind in ("character varying", "text", "character", "jsonb", "json", "bytea")}
        if table in PURGE or transient.get(table):
            tables[table] = {"class": "purge"}
        elif not inspected:
            tables[table] = {"class": "relation"}
        elif table in REFERENCE:
            tables[table] = {"class": "reference", "columns": dict.fromkeys(sorted(inspected), "keep")}
        else:
            rules = {}
            for name, kind in inspected.items():
                ttype, is_dynamic = meta.get((table, name), ("", False))
                rules[name] = rule_for(table, name, kind, ttype, is_dynamic)
            tables[table] = {"class": "firm", "columns": rules}
    scan = dict(SCAN)
    scan["email_domains_allowed"] = ALLOWED_DOMAINS
    manifest = {
        "schema": 1,
        "patterns": PATTERNS,
        "models": Path(models_txt).read_text(encoding="utf-8").split(),
        "tables": tables,
        "harvest_also": HARVEST_ALSO,
        "harvest_purged": HARVEST_PURGED,
        "harvest_ignore": HARVEST_IGNORE,
        "xmlid_scrub_models": XMLID_SCRUB_MODELS,
        "safe_words": SAFE_WORDS,
        "json_key_words": JSON_KEY_WORDS,
        "config_keep": CONFIG_KEEP,
        "scan": scan,
    }
    Path(output).write_text(json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    counts = {}
    for entry in tables.values():
        counts[entry["class"]] = counts.get(entry["class"], 0) + 1
    print(counts)


if __name__ == "__main__":
    if len(sys.argv) != 5:
        sys.exit(__doc__)
    main(*sys.argv[1:])
