from typing import TYPE_CHECKING

from module.retire import enhancement as enhancement_module
from module.retire.enhancement import Enhancement, EnhanceShipType

if TYPE_CHECKING:
    from collections.abc import Iterable, Sequence

    import pytest

    from module.base.button import Button, MatchOffset
    from module.ui.ui import CheckButton


class _Config:
    def __init__(self, enhance_filter: str | None = None) -> None:
        self.Enhance_Filter = enhance_filter
        self.Enhance_ShipToEnhance = "all"
        self.Enhance_CheckPerCategory = 2
        self.Retirement_RetireMode = "one_click_retire"


class _Enhancement(Enhancement):
    config: _Config

    def __init__(
        self,
        *,
        enhance_filter: str | None = None,
        empty_ship_types: Iterable[EnhanceShipType] = (),
        choose_results: Iterable[tuple[bool, int]] = (),
    ) -> None:
        self.config = _Config(enhance_filter=enhance_filter)
        self.calls = []
        self.empty_ship_types = set(empty_ship_types)
        self.choose_results = list(choose_results)

    def _enhance_enter(
        self,
        *,
        favourite: bool = False,
        ship_type: EnhanceShipType | None = None,
    ) -> bool:
        self.calls.append(("enhance_enter", favourite, ship_type))
        return ship_type not in self.empty_ship_types

    def _enhance_choose(self, ship_count: int, *, skip_first_screenshot: bool = True) -> tuple[bool, int]:
        del skip_first_screenshot
        self.calls.append(("enhance_choose", ship_count))
        if self.choose_results:
            return self.choose_results.pop(0)
        return False, ship_count

    def ui_back(
        self,
        check_button: CheckButton,
        appear_button: Button | None = None,
        offset: MatchOffset | None = (30, 30),
        retry_wait: float = 10,
        *,
        skip_first_screenshot: bool = False,
    ) -> None:
        _ = (appear_button, offset, retry_wait, skip_first_screenshot)
        self.calls.append(("ui_back", check_button.name))

    def _enhance_quit(self) -> None:
        self.calls.append(("enhance_quit",))


def test_enhance_ships_uses_configured_type_order() -> None:
    enhancement = _Enhancement(
        enhance_filter="dd > cl",
        choose_results=[(True, 1), (False, 1), (False, 2)],
    )

    assert enhancement.enhance_ships(favourite=False) == 10

    assert ("enhance_enter", False, "dd") in enhancement.calls
    assert ("enhance_enter", False, "cl") in enhancement.calls
    assert enhancement.calls[-1] == ("enhance_quit",)


def test_enhance_ships_treats_empty_filter_as_no_type_filter() -> None:
    enhancement = _Enhancement(enhance_filter=" > ", choose_results=[(False, 2)])

    assert enhancement.enhance_ships(favourite=True) == 0

    assert ("enhance_enter", True, None) in enhancement.calls


def test_enhance_ships_skips_empty_dock_without_back() -> None:
    enhancement = _Enhancement(enhance_filter="dd", empty_ship_types={"dd"})

    assert enhancement.enhance_ships(favourite=False) == 0

    assert enhancement.calls == [
        ("enhance_enter", False, "dd"),
        ("enhance_quit",),
    ]


def test_enhance_ships_replaces_unknown_type_with_available_type(monkeypatch: pytest.MonkeyPatch) -> None:
    def choose_ship_type(ship_types: Sequence[EnhanceShipType]) -> EnhanceShipType:
        assert "dd" not in ship_types
        return "cl"

    monkeypatch.setattr(enhancement_module, "choice", choose_ship_type)
    enhancement = _Enhancement(enhance_filter="dd > unknown", choose_results=[(False, 2), (False, 2)])

    assert enhancement.enhance_ships(favourite=False) == 0

    assert ("enhance_enter", False, "dd") in enhancement.calls
    assert ("enhance_enter", False, "cl") in enhancement.calls
