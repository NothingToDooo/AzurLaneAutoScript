import pytest

from module.research.preset_generator import beautify_filter, convert_name, translate


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("  S4-Q1 >\n S4-Q2  ", "S4-Q1 > S4-Q2"),
        (
            ["A" * 35, "B" * 35],
            f"{'A' * 35}\n> {'B' * 35}",
        ),
        ("S4-Q1", "S4-Q1"),
    ],
)
def test_beautify_filter_normalizes_and_wraps(source: str | list[str], expected: str) -> None:
    assert beautify_filter(source) == expected


@pytest.mark.parametrize(
    ("source", "target", "for_simulate", "expected"),
    [
        (
            "S4-Q1 > !4-1 > S4-A2 > S4-Z2",
            "series_9_ta152_only_cube",
            False,
            "S9-Q1 > Q1 > H1 > 1 > S9-E-315 > S9-E-031",
        ),
        (
            "S4-H1 > !4-1 > S4-H2 > !4-2",
            "series_8_305_only",
            False,
            "Q1 > 1 > Q2 > E2 > 2",
        ),
        (
            "S4-A2 > S4-Z2",
            "series_7_la9_only_cube",
            True,
            "S7-A2 > S7-Z2",
        ),
        (
            "S4-Q0.5 > S4-DR0.5 > S4-PRY0.5 > S4-Q1",
            "series_6_203_only_cube",
            False,
            "S6-Q0.5 > S6-DR0.5 > S6-PRY0.5 > Q0.5 > S6-Q1",
        ),
        ("S4-Q1", "unknown", False, None),
    ],
)
def test_translate_applies_target_policy(
    source: str,
    target: str,
    *,
    for_simulate: bool,
    expected: str | None,
) -> None:
    assert translate(source, target=target, for_simulate=for_simulate) == expected


@pytest.mark.parametrize(
    ("series", "equipment_name"),
    [
        (2, "457"),
        (3, "234"),
        (4, "tenrai"),
        (5, "152"),
        (6, "203"),
        (7, "la9"),
        (8, "305"),
        (9, "ta152"),
    ],
)
def test_convert_name_maps_tenrai_for_each_supported_series(series: int, equipment_name: str) -> None:
    assert convert_name("series_4_tenrai_only", series) == f"series_{series}_{equipment_name}_only"


def test_convert_name_keeps_tenrai_for_unknown_series() -> None:
    assert convert_name("series_4_tenrai_only", 10) == "series_10_tenrai_only"
