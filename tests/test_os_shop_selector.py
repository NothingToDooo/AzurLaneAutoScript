import pytest

from module.os_shop.selector import FILTER_REGEX


@pytest.mark.parametrize(
    ("name", "expected_groups"),
    [
        ("ActionPoint", ("ActionPoint", None, None)),
        ("LoggerAbyssalT6", ("Logger", "Abyssal", "T6")),
        ("PlateRandomT4", ("PlateRandom", None, "T4")),
        ("OrdnanceTestingReportCombatT2", ("OrdnanceTestingReport", "Combat", "T2")),
    ],
)
def test_filter_regex_preserves_shop_item_groups(
    name: str,
    expected_groups: tuple[str, str | None, str | None],
) -> None:
    match = FILTER_REGEX.fullmatch(name)

    assert match is not None
    assert match.groups() == expected_groups
