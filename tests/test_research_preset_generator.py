import pytest

from module.research.preset_generator import convert_name


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
    ],
)
def test_convert_name_maps_tenrai_for_each_supported_series(series: int, equipment_name: str) -> None:
    assert convert_name("series_4_tenrai_only", series) == f"series_{series}_{equipment_name}_only"


def test_convert_name_keeps_tenrai_for_unknown_series() -> None:
    assert convert_name("series_4_tenrai_only", 9) == "series_9_tenrai_only"
