"""lib/letters.ts: the wording of the engagement, governance, management and representation
letters. The texts live in letter_texts.py as they stand in the source, (French, English)."""
from .docx_builder import block
from .letter_texts import TEXTS

LETTER_CODES = {
    "engagement": "P1.4",
    "planning_tcwg": "C5.11",
    "rep_affirmation": "C3.1",
    "rep_complementary": "C3.1",
    "management_letter": "C5.11",
    "tcwg_completion": "C5.11",
}
LETTER_KINDS = tuple(LETTER_CODES)

_LEGAL_FORM_LABELS = {
    "OTHER": ("Autre", "Other"),
    "SA_AG": ("SA (administrateur général)", "SA (general administrator)"),
    "SA": ("SA (conseil d'administration)", "SA (board of directors)"),
}
_INDEPENDENCE = (
    "Les déclarations d'indépendance des membres de l'équipe ont été obtenues en dehors du système ; les déclarations signées sont classées en P2.1, signé par l'associé responsable. Les risques identifiés et les sauvegardes appliquées y sont consignés.",
    "The engagement team's independence declarations were obtained outside the system; the signed declarations are filed on P2.1, which the engagement partner signs. Any threat identified and the safeguards applied are recorded there.",
)
_TITLE_KEYS = {
    "engagement": "engagement_letter",
    "planning_tcwg": "planning_communication_to_those_charged_with",
    "rep_affirmation": "affirmation_letter_before_the_board_s",
    "rep_complementary": "complementary_representation_letter_after_the_board",
    "tcwg_completion": "report_to_those_charged_with_governance",
    "management_letter": "management_letter_isa_265",
}


def legal_form_label(form, fr):
    pair = _LEGAL_FORM_LABELS.get(form)
    return (pair[0] if fr else pair[1]) if pair else form


def framework_label(raw, fr=True):
    value = (raw or "").strip().lower()
    if value in ("", "syscohada"):
        return "SYSCOHADA révisé (AUDCIF)" if fr else "Revised SYSCOHADA (AUDCIF)"
    return "IFRS" if value == "ifrs" else raw.strip()


def end_sentence(text):
    text = text.strip()
    return text if text.endswith((".", "!", "?", "…")) else text + "."


def fcfa(amount, fr=True):
    """No decimals; grouped with a French space in French, a comma in English."""
    rounded = int(round(amount or 0))
    digits = "{:,}".format(abs(rounded))
    return ("-" if rounded < 0 else "") + (digits.replace(",", " ") if fr else digits)


def mandate_years(mandate_type):
    """AUSCGIE art. 704: 2 fiscal years if named in the statutes, 6 if appointed by the AGO."""
    return 2 if mandate_type == "statutes" else 6


def mandate_expiry_year(mandate_type, start_year):
    return start_year + mandate_years(mandate_type) - 1


def independence_statement(fr):
    return _INDEPENDENCE[0 if fr else 1]


def letter_title(kind, fr):
    return TEXTS[_TITLE_KEYS[kind]][0 if fr else 1]


def build_letter(kind, f, fr):
    """The blocks of one letter. ``f`` is the dict of LetterFields, snake-cased; dates in it
    arrive formatted DD/MM/YYYY."""
    index = 0 if fr else 1

    def t(key, **params):
        return TEXTS[key][index].format(**params)

    def p(text):
        return block("p", text)

    def b(text):
        return block("b", text)

    client, year, end = f["client_name"], f["fiscal_year"], f["period_end"]
    framework = framework_label(f.get("framework"), fr)
    period = {"f_fiscalYear": year, "fmtDate_f_periodEnd": end, "frameworkLabel_f_framework": framework, "framework": framework}
    out = [block("title", letter_title(kind, fr))]
    if kind == "engagement":
        out.append(p("%s (%s)" % (client, legal_form_label(f.get("legal_form"), fr))))
        identity = []
        if f.get("address"):
            identity.append(t("address_f_address", f_address=f["address"]))
        if f.get("registration_number"):
            identity.append(("RCCM : %s" if fr else "RCCM: %s") % f["registration_number"])
        if f.get("niu"):
            identity.append(("NIU : %s" if fr else "NIU: %s") % f["niu"])
        if identity:
            out.append(p(" · ".join(identity)))
        out += [
            p(t("fiscal_year_f_fiscalyear_period_end", **period)),
            b(t("objective_and_scope_of_the_audit")),
            p(t("the_objective_of_our_engagement_is", **period)),
            b(t("the_auditor_s_responsibilities")),
            p(t("we_are_responsible_for_forming_and")),
            b(t("management_s_responsibilities")),
            p(t("management_is_responsible_for_the_preparation", **period)),
            b(t("expected_form_and_content_of_the")),
            p(t("we_will_issue_an_auditor_s")),
        ]
        if f.get("mandate_type") and f.get("mandate_start_year"):
            out.append(p(t(
                "mandate_mandateyears_f_mandatetype_fiscal_years",
                mandateYears_f_mandateType=mandate_years(f["mandate_type"]),
                f_mandateStartYear=f["mandate_start_year"],
                expiry=mandate_expiry_year(f["mandate_type"], f["mandate_start_year"]),
            )))
        if f.get("co_cac"):
            out.append(b(t("co_commissariat_variant_the_engagement_is")))
        out += [p(t("experts_and_staff_assisting_the_statutory")), p(t("signatures_the_firm_the_client"))]
    elif kind == "planning_tcwg":
        planning = f.get("planning") or {}
        out.append(p("%s — %s %s" % (client, t("year_ended"), end)))
        if planning.get("addressees"):
            out.append(p(("%s : %s" if fr else "%s: %s") % (t("addressees"), planning["addressees"])))
        out += [b(t("planned_scope_and_timing_of_the")), p(t("we_audit_the_financial_statements_for", **period))]
        if planning.get("scope"):
            out.append(p(end_sentence(planning["scope"])))
        out.append(b(t("significant_risks_identified_isa_260_15")))
        if planning.get("risks"):
            out += [p("• %s" % end_sentence(risk)) for risk in planning["risks"]]
        else:
            out.append(p(t("no_significant_risk_is_recorded_on")))
        out.append(b(t("materiality_isa_320")))
        materiality = planning.get("materiality")
        if materiality:
            out.append(p(t(
                "materiality_for_the_financial_statements_as",
                fcfa_pl_materiality_overall=fcfa(materiality["overall"], fr),
                fcfa_pl_materiality_performance=fcfa(materiality["performance"], fr),
                fcfa_pl_materiality_trivial=fcfa(materiality["trivial"], fr),
            )))
        else:
            out.append(p(t("materiality_has_not_yet_been_approved")))
        out.append(b(t("audit_team")))
        if planning.get("team"):
            out += [p("• %s — %s" % (name, role)) for name, role in planning["team"]]
        else:
            out.append(p(t("the_team_has_not_yet_been")))
        out += [b(t("independence_isa_260_17")), p(t("the_firm_and_the_team_comply")), b(t("the_statutory_auditor"))]
    elif kind == "rep_affirmation":
        uncorrected = f.get("uncorrected") or []
        out += [
            p("%s — %s (%s)" % (client, year, end)),
            b(t("management_s_responsibilities_isa_580_1011")),
            p(t("we_have_fulfilled_our_responsibilities_as", **period)),
            p(t("we_have_provided_you_with_all")),
            b(t("other_representations")),
            p(t("to_the_best_of_our_knowledge")),
        ]
        out += [p("• %s" % rep) for rep in f.get("specific_representations") or []]
        out.append(b(t("uncorrected_misstatements_isa_450_14")))
        if not uncorrected:
            out.append(p(t("no_uncorrected_misstatements_have_been_communicated")))
        else:
            out.append(p(t(
                "we_believe_the_effects_of_the", uncorrected_length=len(uncorrected),
                fcfa_total=fcfa(sum(m["amount"] for m in uncorrected), fr),
            )))
            out += [p("• %s — %s FCFA" % (m["description"], fcfa(m["amount"], fr))) for m in uncorrected]
        out.append(b(t("signatures_managing_director_head_of_accounting")))
    elif kind == "rep_complementary":
        out += [
            p("%s — %s (%s)" % (client, year, end)),
            p(t("following_the_board_s_approval_of")),
            b(t("signatures_chairman_of_the_board_managing")),
        ]
    elif kind == "tcwg_completion":
        uncorrected = f.get("uncorrected") or []
        out += [p("%s — %s (%s)" % (client, year, end)), b(t("significant_findings_from_the_audit_isa"))]
        matters = f.get("significant_matters") or []
        out += [p("• %s" % m) for m in matters] or [p(t("no_significant_matter_recorded_on_c1"))]
        out.append(b(t("uncorrected_misstatements_isa_450_12")))
        if not uncorrected:
            out.append(p(t("no_uncorrected_misstatements")))
        else:
            out.append(p(t(
                "uncorrected_length_uncorrected_misstatement_s_total", uncorrected_length=len(uncorrected),
                fcfa_total=fcfa(sum(m["amount"] for m in uncorrected), fr),
            )))
            out += [p("• %s — %s FCFA" % (m["description"], fcfa(m["amount"], fr))) for m in uncorrected]
        out.append(b(t("deficiencies_in_internal_control_isa_265")))
        points = f.get("c1_points") or []
        out += [p("• %s" % point) for point in points] or [p(t("no_significant_deficiency_identified"))]
        out += [b(t("independence_isa_260_17_2")), p(independence_statement(fr)), b(t("the_statutory_auditor_2"))]
    else:
        out += [p("%s — %s" % (client, year)), p(t("we_bring_to_your_attention_the"))]
        out += [p("• %s" % point) for point in f.get("c1_points") or []]
    return out
