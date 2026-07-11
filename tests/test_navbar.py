from types import SimpleNamespace
from typing import TYPE_CHECKING

from module.base.base import ModuleBase
from module.ui.navbar import Navbar, NavbarTarget

if TYPE_CHECKING:
    from collections.abc import Iterable


class _FakeDevice:
    def __init__(self) -> None:
        self.clicked = []
        self.screenshot_count = 0

    def click(self, button: str) -> None:
        self.clicked.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _FakeMain(ModuleBase):
    device: _FakeDevice

    def __init__(self) -> None:
        self.device = _FakeDevice()


class _FakeNavbar(Navbar):
    def __init__(
        self,
        info_results: Iterable[tuple[int | None, int | None, int | None]],
        obstruct_results: Iterable[bool] = (),
    ) -> None:
        self.grids = SimpleNamespace(buttons=["button_0", "button_1", "button_2"])
        self.name = "TEST_NAVBAR"
        self.info_results = list(info_results)
        self.obstruct_results = list(obstruct_results)
        self.info_mains: list[ModuleBase] = []
        self.obstruct_mains: list[ModuleBase] = []

    def get_info(self, main: ModuleBase) -> tuple[int | None, int | None, int | None]:
        self.info_mains.append(main)
        return self.info_results.pop(0)

    def _shop_obstruct_handle(self, main: ModuleBase) -> bool:
        self.obstruct_mains.append(main)
        if self.obstruct_results:
            return self.obstruct_results.pop(0)
        return False


def test_navbar_set_rejects_missing_direction() -> None:
    navbar = _FakeNavbar(info_results=[])
    main = _FakeMain()

    assert not navbar.set(main, NavbarTarget())
    assert main.device.clicked == []


def test_navbar_set_clicks_left_index_then_stops() -> None:
    navbar = _FakeNavbar(info_results=[(0, 0, 2), (1, 0, 2)])
    main = _FakeMain()

    assert navbar.set(main, NavbarTarget(left=2))
    assert main.device.clicked == ["button_1"]
    assert main.device.screenshot_count == 1


def test_navbar_set_maps_bottom_to_right_index() -> None:
    navbar = _FakeNavbar(info_results=[(0, 0, 2), (2, 0, 2)])
    main = _FakeMain()

    assert navbar.set(main, NavbarTarget(bottom=1))
    assert main.device.clicked == ["button_2"]


def test_navbar_set_waits_for_visible_nav_info() -> None:
    navbar = _FakeNavbar(info_results=[(None, None, None), (1, 0, 2)])
    main = _FakeMain()

    assert navbar.set(main, NavbarTarget(left=2))
    assert main.device.clicked == []


def test_navbar_set_handles_shop_obstruction_before_reading_info() -> None:
    navbar = _FakeNavbar(info_results=[(1, 0, 2)], obstruct_results=[True, False])
    main = _FakeMain()

    assert navbar.set(main, NavbarTarget(left=2))
    assert navbar.info_mains == [main]
    assert navbar.obstruct_mains == [main, main]
