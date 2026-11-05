from ..messages import Msg, _, dumps, dumps_list, loads, render


def french(source):
    return {
        "Disk %(pct)s%% full": "Disque plein à %(pct)s %%",
        "No heartbeat for %(age)s": "Aucun heartbeat depuis %(age)s",
        "%(count)s days": "%(count)s jours",
        "All is normal": "Tout est normal",
    }.get(source, source)


def test_a_message_is_its_english_text():
    message = _("Disk %(pct)s%% full", pct=85)
    assert message == "Disk 85% full"
    assert "85%" in message
    assert isinstance(message, str)


def test_a_message_with_no_parameter_keeps_its_percent_signs():
    assert _("100% sure") == "100% sure"


def test_it_renders_in_the_readers_language():
    assert render(_("Disk %(pct)s%% full", pct=85), french) == "Disque plein à 85 %"
    assert render(_("All is normal"), french) == "Tout est normal"


def test_nested_messages_are_translated_too():
    message = _("No heartbeat for %(age)s", age=_("%(count)s days", count=3))
    assert message == "No heartbeat for 3 days"
    assert render(message, french) == "Aucun heartbeat depuis 3 jours"


def test_a_stored_message_comes_back_whole():
    message = _("No heartbeat for %(age)s", age=_("%(count)s days", count=3))
    restored = loads(dumps(message))
    assert len(restored) == 1
    assert isinstance(restored[0], Msg)
    assert render(restored[0], french) == "Aucun heartbeat depuis 3 jours"


def test_a_message_without_parameters_is_stored_as_its_source():
    assert dumps(_("All is normal")) == "All is normal"
    assert render(loads("All is normal")[0], french) == "Tout est normal"


def test_a_list_comes_back_in_order():
    stored = dumps_list([_("All is normal"), _("Disk %(pct)s%% full", pct=9)])
    assert [render(item, french) for item in loads(stored)] == ["Tout est normal", "Disque plein à 9 %"]


def test_what_someone_typed_passes_through_untouched():
    assert dumps("Fin de contrat à 100 %") == "Fin de contrat à 100 %"
    assert [render(item, french) for item in loads("Fin de contrat à 100 %")] == ["Fin de contrat à 100 %"]


def test_nothing_stored_is_an_empty_list():
    assert loads(False) == []
    assert loads("") == []


def test_text_that_only_looks_stored_is_kept():
    assert loads('{"t": broken') == ['{"t": broken']
