from types import SimpleNamespace

import pytest

from module.base.filter import Filter

_DASH_CODEPOINTS = (
    0x2010,
    0x2011,
    0x2012,
    0x2013,
    0x2014,
    0x2015,
    0x2212,
    0xFF0D,
    0xFE63,
    0xFE58,
    0x2043,
)


@pytest.mark.parametrize(
    "codepoint",
    _DASH_CODEPOINTS,
    ids=[f"U+{value:04X}" for value in _DASH_CODEPOINTS],
)
def test_filter_load_normalizes_unicode_dashes(codepoint: int) -> None:
    candidate = SimpleNamespace(group="foo", name="bar")
    selector = Filter[SimpleNamespace](r"([a-z]+)-([a-z]+)", ["group", "name"])

    selector.load(f"foo{chr(codepoint)}bar")

    assert selector.filter_raw == ["foo-bar"]
    assert selector.apply([candidate]) == [candidate]
