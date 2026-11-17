"""The sign-in, invitation and new-password pages read as AuditISA, in English and French (2026-11-17).

Plain pytest on the template file and the French catalogue: no Odoo needed."""
import re
import xml.etree.ElementTree as ET
from pathlib import Path

ADDON = Path(__file__).parents[2]
TEMPLATES = ADDON / "views" / "login_templates.xml"


def _templates():
    return {t.get("id"): t for t in ET.parse(TEMPLATES).getroot().iter("template")}


def _text(node):
    return " ".join("".join(node.itertext()).split())


def _french():
    """msgid -> msgstr of the module's French catalogue (single-line entries)."""
    po = (ADDON / "i18n" / "fr.po").read_text(encoding="utf-8")
    return dict(re.findall(r'^msgid "(.+)"\r?\nmsgstr "(.*)"', po, re.M))


def test_the_invitation_page_welcomes_and_sets_a_password():
    page = _text(_templates()["signup_welcome"])
    assert "Welcome to" in page
    assert "Choose your password to finish setting up your account." in page
    assert "Set my password" in page


def test_the_invitation_page_drops_the_sign_in_link_and_locks_the_email_from_the_link():
    template = _templates()["signup_welcome"]
    removed = [x.get("expr") for x in template.iter("xpath") if x.get("position") == "replace" and not len(x)]
    assert any("/web/login" in expr for expr in removed)
    login = [x for x in template.iter("xpath") if x.get("expr") == "//input[@name='login']"][0]
    assert "token and not invalid_token" in login.find("attribute").text


def test_a_new_password_link_saves_a_new_password():
    page = _text(_templates()["reset_password_welcome"])
    assert "Save my new password" in page
    assert "Welcome to" in page


def test_no_powered_by_odoo_and_no_passkey_button():
    templates = _templates()
    footer = templates["login_layout_no_odoo"]
    assert any("www.odoo.com" in x.get("expr") and x.get("position") == "replace" for x in footer.iter("xpath"))
    passkey = templates["login_no_passkey"]
    assert int(passkey.get("priority")) > 16  # after auth_passkey's own addition
    assert "passkey_login_link" in passkey.find("xpath/t").get("t-value")


def test_every_new_line_has_its_french():
    french = _french()
    for text in ("Welcome to", "Choose your password to finish setting up your account.",
                 "Choose a new password for your account.", "Set my password", "Save my new password"):
        assert french.get(text), text
    assert french["Set my password"] == "Enregistrer mon mot de passe"


def test_the_sign_in_pages_wear_the_firm_green():
    """Review of 2026-11-17: primary buttons and links in the application's green, not Odoo's violet."""
    footer = _templates()["login_layout_no_odoo"]
    shell = (ADDON / "static" / "src" / "scss" / "shell.scss").read_text(encoding="utf-8")
    green = re.search(r"--ea-green:\s*(#[0-9a-f]{6})", shell).group(1)
    style = footer.find("xpath/style")
    assert style is not None and green in style.text
    assert ".btn-primary" in style.text and "a:not(.btn)" in style.text
    # placed before the footer's condition is rewritten, while the xpath still finds it
    exprs = [(x.get("expr"), x.get("position")) for x in footer.iter("xpath")]
    footer_div = "//div[@t-if='not disable_footer']"
    assert exprs.index((footer_div, "before")) < exprs.index((footer_div, "attributes"))
