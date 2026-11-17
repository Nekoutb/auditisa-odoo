"""The payroll register's optional columns (owner, 2026-11-17): the mandatory fields stay as they
were, thirteen optional columns are added for the payroll analytical review, each marked
"Improves the analysis", and the downloadable template is read back column for column."""
from services.dataset_mapping import ANALYSIS_HINT, EXTRA_FIELDS, FIELDS, all_fields, guess_map, hint_keys
from services.import_matching import analysis_keys, amount_columns, date_columns, detect_mapping, missing_fields, required_keys

OPTIONAL = [
    "category", "department", "hireDate", "leavingDate", "baseSalary", "allowances", "benefitsInKind", "overtime",
    "incomeTax", "socialEmployee", "socialEmployer", "otherEmployerCharges", "period",
]
ABBREVIATIONS = ("IRPP", "CNPS", "CNSS", "HS ", "Emp.", "No.", "Nb")


def test_the_mandatory_fields_do_not_change():
    assert [f["key"] for f in FIELDS["payroll_register"]] == ["party", "partyName", "amount", "net"]
    assert required_keys("payroll_register") == ["party", "partyName", "amount"]
    assert all_fields("payroll_register")[:4] == FIELDS["payroll_register"]
    mapping = {"party": "Matricule", "partyName": "Nom", "amount": "Brut"}
    assert missing_fields("payroll_register", mapping) == []


def test_the_optional_columns_carry_the_hint():
    extra = EXTRA_FIELDS["payroll_register"]
    assert [f["key"] for f in extra] == OPTIONAL
    assert hint_keys("payroll_register") == OPTIONAL == analysis_keys("payroll_register")
    assert not any(f.get("required") for f in extra)
    assert ANALYSIS_HINT == {"en": "Improves the analysis", "fr": "Améliore l'analyse"}
    for field in extra:
        assert field["en"] and field["fr"]
        assert not any(word in field["en"] for word in ABBREVIATIONS), field["en"]
    labels = {f["key"]: f["en"] for f in extra}
    assert labels["incomeTax"] == "Income tax withheld"
    assert labels["socialEmployee"] == "Social security, employee share"
    assert labels["socialEmployer"] == "Social security, employer share"
    # the other kinds gain no hint
    assert hint_keys("fixed_asset_register") == [] and analysis_keys("trial_balance") == []


def test_the_template_is_read_back_column_for_column():
    for language in ("en", "fr"):
        headers = [f[language] for f in all_fields("payroll_register")]
        mapping = guess_map("payroll_register", headers)
        assert mapping == {f["key"]: f[language] for f in all_fields("payroll_register")}, language


def test_a_client_file_finds_its_optional_columns():
    headers = [
        "Matricule", "Nom et prénom", "Catégorie", "Service", "Date d'embauche", "Date de sortie", "Salaire de base",
        "Primes", "Avantages en nature", "Heures supplémentaires", "Retenue IRPP", "CNPS salarié", "CNPS patronale",
        "Autres charges patronales", "Mois", "Salaire brut", "Net à payer",
    ]
    guessed, _sources = detect_mapping("payroll_register", {"headers": headers, "rows": []})
    assert guessed["party"] == "Matricule" and guessed["partyName"] == "Nom et prénom"
    assert guessed["amount"] == "Salaire brut" and guessed["net"] == "Net à payer"
    assert guessed["socialEmployee"] == "CNPS salarié" and guessed["socialEmployer"] == "CNPS patronale"
    assert guessed["department"] == "Service" and guessed["incomeTax"] == "Retenue IRPP"
    assert guessed["hireDate"] == "Date d'embauche" and guessed["leavingDate"] == "Date de sortie"
    assert guessed["period"] == "Mois" and guessed["baseSalary"] == "Salaire de base"
    assert set(OPTIONAL) <= set(guessed)
    assert set(date_columns("payroll_register", guessed)) == {"Date d'embauche", "Date de sortie"}
    assert {"Salaire de base", "CNPS patronale", "Retenue IRPP"} <= set(amount_columns("payroll_register", guessed))


def test_an_old_file_with_the_four_columns_still_maps_as_before():
    headers = ["Matricule", "Nom", "Brut", "Net"]
    guessed, _sources = detect_mapping("payroll_register", {"headers": headers, "rows": []})
    assert guessed == {"party": "Matricule", "partyName": "Nom", "amount": "Brut", "net": "Net"}
