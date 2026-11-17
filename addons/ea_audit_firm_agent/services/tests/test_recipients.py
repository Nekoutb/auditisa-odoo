"""A practice space's emails go only to the allowed addresses; the console's reply address is checked. Pure."""

from email.message import EmailMessage

from ..collect import parse_desired
from ..recipients import filter_message, mask, parse_allowlist, valid_reply_to


def message(**headers):
    msg = EmailMessage()
    for key, value in headers.items():
        msg[key.replace("_", "-")] = value
    msg.set_content("x")
    return msg


def test_the_allowlist_takes_addresses_only_in_lower_case():
    assert parse_allowlist("Owner@Exemple.cm\n bad, test@cm-ea.com;") == {"owner@exemple.cm", "test@cm-ea.com"}
    assert parse_allowlist("") == frozenset()


def test_only_allowed_recipients_stay_in_every_header():
    msg = message(To='"Owner" <OWNER@exemple.cm>, other@exemple.cm', Cc="cc@exemple.cm", Bcc="test@cm-ea.com")
    kept, dropped = filter_message(msg, parse_allowlist("owner@exemple.cm test@cm-ea.com"))
    assert kept == ["owner@exemple.cm", "test@cm-ea.com"]
    assert dropped == ["cc@exemple.cm", "other@exemple.cm"]
    assert "other@" not in msg["To"] and "OWNER@exemple.cm" in msg["To"]
    assert msg["Cc"] is None
    assert msg["Bcc"] == "test@cm-ea.com"


def test_an_empty_list_drops_everyone():
    msg = message(To="owner@exemple.cm")
    kept, dropped = filter_message(msg, parse_allowlist(""))
    assert kept == [] and dropped == ["owner@exemple.cm"] and msg["To"] is None


def test_the_log_shows_a_masked_address():
    assert mask("owner@exemple.cm") == "o***@exemple.cm"
    assert mask("nonsense") == "***"


def test_the_reply_address_from_the_console_is_checked():
    assert valid_reply_to("awa@exemple.cm") and valid_reply_to("")
    assert not valid_reply_to("not an address") and not valid_reply_to(None) and not valid_reply_to(["a@b.cm"])
    assert parse_desired(b'{"mail_reply_to": "awa@exemple.cm"}')["mail_reply_to"] == "awa@exemple.cm"
    assert parse_desired(b'{"mail_reply_to": ""}')["mail_reply_to"] == ""
    assert "mail_reply_to" not in parse_desired(b'{"mail_reply_to": "x y"}')
    assert "mail_reply_to" not in parse_desired(b'{}')
