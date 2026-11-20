"""Reading uploaded statements: the request sent and the answers handled, with a stand-in service."""
import json
import sys
from types import SimpleNamespace

import pytest

import obt_reading as obt_reader
from services import obt
from test_obt import FORM


class FakeMessages:
    def __init__(self, text=None, stop_reason="end_turn"):
        self.text, self.stop_reason, self.sent = text, stop_reason, None

    def create(self, **kwargs):
        self.sent = kwargs
        return SimpleNamespace(stop_reason=self.stop_reason, content=[
            SimpleNamespace(type="thinking", thinking=""), SimpleNamespace(type="text", text=self.text),
        ])


def client(text=None, stop_reason="end_turn"):
    messages = FakeMessages(text, stop_reason)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def test_the_request_carries_the_pages_the_schema_and_no_more():
    fake, messages = client(json.dumps({"year_end": "2025-12-31", "unit": "units", "signed": True, "column": "Net",
                                        "lines": [{"ref": "BZ", "amount": 10, "page": 2}], "net_result_income_statement": None}))
    files = [("bilan.pdf", "application/pdf", b"%PDF-1.4"), ("page3.JPG", "application/octet-stream", b"\xff\xd8")]
    data = obt_reader.read("k", files, obt.reading_instructions(FORM), obt.reading_schema(), client=fake)
    assert data["lines"][0]["ref"] == "BZ"
    sent = messages.sent
    assert sent["model"] == obt_reader.MODEL and sent["fallbacks"] == "default" and sent["betas"] == [obt_reader.FALLBACK_BETA]
    assert sent["output_config"]["format"] == {"type": "json_schema", "schema": obt.reading_schema()}
    blocks = sent["messages"][0]["content"]
    assert [block["type"] for block in blocks] == ["document", "image", "text"]
    assert blocks[1]["source"]["media_type"] == "image/jpeg" and "thinking" not in sent


@pytest.mark.parametrize("files, code", [
    ([], "unsupported"),
    ([("notes.docx", "application/msword", b"x")], "unsupported"),
    ([("big.pdf", "application/pdf", b"0" * (obt_reader.MAX_BYTES + 1))], "too_large"),
])
def test_files_the_service_cannot_take(files, code):
    fake, _ = client("{}")
    with pytest.raises(obt_reader.ReadingError) as caught:
        obt_reader.read("k", files, "x", {}, client=fake)
    assert caught.value.code == code


@pytest.mark.parametrize("text, stop, code", [
    ("not json", "end_turn", "unreadable"),
    ("[1, 2]", "end_turn", "unreadable"),
    ('{"lines": []}', "refusal", "refused"),
    ('{"lines": [', "max_tokens", "unreadable"),
])
def test_answers_that_give_no_table(text, stop, code):
    fake, _ = client(text, stop)
    with pytest.raises(obt_reader.ReadingError) as caught:
        obt_reader.read("k", [("a.png", "image/png", b"x")], "x", {}, client=fake)
    assert caught.value.code == code


def test_no_key_and_no_package():
    with pytest.raises(obt_reader.ReadingError) as caught:
        obt_reader.read("", [("a.png", "image/png", b"x")], "x", {})
    assert caught.value.code == "no_key"
    saved = sys.modules.get("anthropic")
    sys.modules["anthropic"] = None   # an import of it fails, as on a server not updated yet
    try:
        with pytest.raises(obt_reader.ReadingError) as caught:
            obt_reader.read("k", [("a.png", "image/png", b"x")], "x", {})
        assert caught.value.code == "not_installed"
    finally:
        if saved is None:
            sys.modules.pop("anthropic", None)
        else:
            sys.modules["anthropic"] = saved
