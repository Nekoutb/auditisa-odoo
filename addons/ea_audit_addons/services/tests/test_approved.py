import pytest

from ea_audit_addons.services.approved import parse_approved, read_approved


def test_a_good_list_reads_back_sorted_and_once():
    assert parse_approved('{"on":["ea_client_b","ea_client_a","ea_client_b"]}') == ["ea_client_a", "ea_client_b"]


def test_an_empty_list_is_a_request_for_everything_off():
    assert parse_approved('{"on":[]}') == []


@pytest.mark.parametrize("text", [
    "", "null", "[]", "{}", '{"on":"x"}', '{"on":[1]}', '{"on":["Bad Code"]}', '{"on":["a;rm -rf /"]}',
    '{"on":["' + "a" * 41 + '"]}', '{"on":[' + ",".join(f'"code_{n}"' for n in range(25)) + "]}", "not json",
])
def test_anything_else_changes_nothing(text):
    assert parse_approved(text) is None


def test_no_file_changes_nothing(tmp_path):
    assert read_approved(str(tmp_path / "absent.json")) is None


def test_a_file_is_read(tmp_path):
    path = tmp_path / "approved.json"
    path.write_text('{"on":["ea_client_a"]}', encoding="ascii")
    assert read_approved(str(path)) == ["ea_client_a"]
