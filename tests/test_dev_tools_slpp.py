import pytest

from dev_tools.slpp import ParseError, slpp


def test_slpp_decodes_nested_numeric_keys() -> None:
    raw = "{点={2={0={叫={醒={我={this=true}}}}}}}"

    assert slpp.decode(raw) == {"点": {2: {0: {"叫": {"醒": {"我": {"this": True}}}}}}}


def test_slpp_decodes_comma_values_as_indexed_entries() -> None:
    assert slpp.decode("{foo,bar}") == {0: "foo", 1: "bar"}


def test_slpp_keeps_comment_like_dashes_inside_strings() -> None:
    raw = '{profiles="跨越虚无，为重樱带来希望和未来吧---------- "}'

    assert slpp.decode(raw) == {"profiles": "跨越虚无，为重樱带来希望和未来吧---------- "}


def test_slpp_rejects_malformed_negative_number() -> None:
    with pytest.raises(ParseError):
        slpp.decode("{value = -x}")
