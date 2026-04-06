import pytest

from custom_components.flipper_rc.parsers import (
    parse_key_value_payload,
    parse_subghz_command,
    parse_subghz_file_command,
)


def test_parse_key_value_payload_splits_once():
    payload = "path=/ext/subghz/foo=bar.sub,repeat=2"
    data = parse_key_value_payload(payload, "invalid")
    assert data["path"] == "/ext/subghz/foo=bar.sub"
    assert data["repeat"] == "2"


def test_parse_subghz_command_key_value_success():
    parsed = parse_subghz_command("subghz:key=0x123456,freq=433920000,te=350,repeat=3,antenna=1")
    assert parsed == {
        "key": 0x123456,
        "frequency": 433920000,
        "te": 350,
        "repeat": 3,
        "antenna": 1,
    }


def test_parse_subghz_command_positional_success():
    parsed = parse_subghz_command("subghz:0x123456,433920000,350,1,0")
    assert parsed == {
        "key": 0x123456,
        "frequency": 433920000,
        "te": 350,
        "repeat": 1,
        "antenna": 0,
    }


def test_parse_subghz_command_rejects_bad_antenna():
    with pytest.raises(ValueError, match="antenna"):
        parse_subghz_command("subghz:key=0x123456,freq=433920000,antenna=2")


def test_parse_subghz_file_command_key_value_success():
    parsed = parse_subghz_file_command("subghz-file:path=/ext/subghz/test.sub,repeat=2,antenna=1")
    assert parsed == {
        "path": "/ext/subghz/test.sub",
        "repeat": 2,
        "antenna": 1,
    }


def test_parse_subghz_file_command_positional_success():
    parsed = parse_subghz_file_command("subghz-file:/ext/subghz/test.sub,3,0")
    assert parsed == {
        "path": "/ext/subghz/test.sub",
        "repeat": 3,
        "antenna": 0,
    }


def test_parse_subghz_file_command_rejects_non_ext_path():
    with pytest.raises(ValueError, match="must start with"):
        parse_subghz_file_command("subghz-file:path=/int/subghz/test.sub,repeat=1")


def test_parse_subghz_file_command_accepts_subghz_root():
    parsed = parse_subghz_file_command("subghz-file:path=/subghz/test.sub,repeat=1,antenna=0")
    assert parsed == {
        "path": "/subghz/test.sub",
        "repeat": 1,
        "antenna": 0,
    }
