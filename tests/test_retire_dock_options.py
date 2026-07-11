from typing import Any

from module.retire import assets as retire_assets
from module.retire.dock import Dock, DockFilterOptions, dock_filter_options


class _Device:
    def __init__(self) -> None:
        self.screenshot_count = 0

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _DockFilterProbe(Dock):
    device: Any

    def __init__(self) -> None:
        self.device = _Device()
        self.appear_calls: list[tuple[object, dict[str, object]]] = []
        self.appear_then_click_calls: list[tuple[object, dict[str, object]]] = []
        self.confirm_results: list[bool] = []

    def interval_clear(self, button: object, *_args: object, **_kwargs: object) -> None:
        _ = button

    def loop(self, *_args: object, **_kwargs: object):
        return range(1)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        self.appear_calls.append((button, kwargs))
        if button is retire_assets.DOCK_FILTER_CONFIRM:
            return self.confirm_results.pop(0)
        return button is retire_assets.DOCK_CHECK

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        self.appear_then_click_calls.append((button, kwargs))
        return False


def test_dock_filter_options_override_existing_options() -> None:
    options = dock_filter_options(
        DockFilterOptions(index="cv", wait_loading=False),
        {"rarity": "common", "extra": "enhanceable"},
    )

    assert options.index == "cv"
    assert options.rarity == "common"
    assert options.extra == "enhanceable"
    assert options.wait_loading is False


def test_dock_filter_uses_current_cn_layout() -> None:
    dock = object.__new__(Dock)
    setting = dock.dock_filter

    assert setting.settings[("sort", "rarity")].area[:2] == (218, 36)
    assert setting.settings[("index", "all")].area[:2] == (218, 109)
    assert setting.settings[("faction", "all")].area[:2] == (218, 239)
    assert ("faction", "pedreria") in setting.settings
    assert setting.settings[("rarity", "all")].area[:2] == (218, 427)
    assert setting.settings[("extra", "no_limit")].area[:2] == (218, 499)


def test_dock_filter_enter_uses_expanded_confirm_offset() -> None:
    dock = _DockFilterProbe()
    dock.confirm_results = [True]

    dock.dock_filter_enter()

    assert dock.appear_calls == [(retire_assets.DOCK_FILTER_CONFIRM, {"offset": (20, 60)})]


def test_dock_filter_confirm_uses_expanded_confirm_offset() -> None:
    dock = _DockFilterProbe()
    dock.confirm_results = [True, False]

    dock.dock_filter_confirm(wait_loading=False)

    confirm_appear_calls = [call for call in dock.appear_calls if call[0] is retire_assets.DOCK_FILTER_CONFIRM]
    assert confirm_appear_calls == [
        (retire_assets.DOCK_FILTER_CONFIRM, {"offset": (20, 60)}),
        (retire_assets.DOCK_FILTER_CONFIRM, {"offset": (20, 60)}),
    ]
    assert dock.appear_then_click_calls == [(retire_assets.DOCK_FILTER_CONFIRM, {"offset": (20, 60), "interval": 3})]
