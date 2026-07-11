from dataclasses import dataclass, replace
from types import SimpleNamespace
from typing import TYPE_CHECKING, TypedDict, Unpack

import pytest

from module.exception import GameNotRunningError
from module.raid import assets as raid_assets
from module.ui import assets as ui_assets
from module.ui.page import Page
from module.ui.ui import UI
from module.ui_white import assets as ui_white_assets

if TYPE_CHECKING:
    from module.base.button import Button


class _FakePage(Page):
    def __init__(self, name: str = "page_test", check_button: Button = ui_assets.GOTO_MAIN) -> None:
        self.name = name
        self.check_button = check_button

    def __str__(self) -> str:
        return self.name


class _FakeDevice:
    def __init__(self, *, has_cached_image: bool = True, app_running: bool = True) -> None:
        self.has_cached_image = has_cached_image
        self.app_running = app_running
        self.screenshot_count = 0
        self.app_is_running_count = 0
        self.orientation_count = 0

    def screenshot(self) -> None:
        self.screenshot_count += 1

    def app_is_running(self) -> bool:
        self.app_is_running_count += 1
        return self.app_running

    def get_orientation(self) -> None:
        self.orientation_count += 1


@dataclass(frozen=True, slots=True)
class _FakeUIOptions:
    visible_page: Page | None = None
    visible_after_checks: int = 0
    recover_buttons: tuple[Button, ...] = ()
    additional_results: tuple[bool, ...] = ()
    has_cached_image: bool = True
    app_running: bool = True


class _FakeUISettings(TypedDict, total=False):
    visible_page: Page | None
    visible_after_checks: int
    recover_buttons: tuple[Button, ...]
    additional_results: tuple[bool, ...]
    has_cached_image: bool
    app_running: bool


def _fake_ui_options(
    options: _FakeUIOptions | None = None,
    settings: _FakeUISettings | None = None,
) -> _FakeUIOptions:
    options = _FakeUIOptions() if options is None else options
    if settings:
        options = replace(options, **settings)
    return options


class _FakeUI(UI):
    config: SimpleNamespace
    device: _FakeDevice
    ui_current: Page | None

    def __init__(
        self,
        options: _FakeUIOptions | None = None,
        **settings: Unpack[_FakeUISettings],
    ) -> None:
        options = _fake_ui_options(options, settings)
        self.device = _FakeDevice(has_cached_image=options.has_cached_image, app_running=options.app_running)
        self.config = SimpleNamespace(
            SERVER="cn",
        )
        self.ui_current = None
        self.visible_page = options.visible_page
        self.visible_after_checks = options.visible_after_checks
        self.page_check_count = 0
        self.recover_buttons = list(options.recover_buttons)
        self.appear_then_click_calls = []
        self.additional_results = list(options.additional_results)
        self.additional_calls = 0

    def ui_page_appear(self, page: Page, *_args: object, **_kwargs: object) -> bool:
        self.page_check_count += 1
        return page is self.visible_page and self.page_check_count > self.visible_after_checks

    def appear_then_click(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        self.appear_then_click_calls.append(button)
        if self.recover_buttons and button == self.recover_buttons[0]:
            self.recover_buttons.pop(0)
            return True
        return False

    def ui_additional(self, *, get_ship: bool = True) -> bool:
        del get_ship
        self.additional_calls += 1
        if self.additional_results:
            return self.additional_results.pop(0)
        return False


def test_ui_get_current_page_uses_cached_first_screenshot(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage()
    monkeypatch.setattr(Page, "iter_pages", lambda: [page])
    ui = _FakeUI(visible_page=page, has_cached_image=True)

    assert ui.ui_get_current_page() is page
    assert ui.ui_current is page
    assert ui.device.screenshot_count == 0


def test_ui_get_current_page_screenshots_without_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage()
    monkeypatch.setattr(Page, "iter_pages", lambda: [page])
    ui = _FakeUI(visible_page=page, has_cached_image=False)

    assert ui.ui_get_current_page() is page
    assert ui.device.screenshot_count == 1


def test_ui_get_current_page_recovers_with_home_button(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage()
    monkeypatch.setattr(Page, "iter_pages", lambda: [page])
    ui = _FakeUI(visible_page=page, visible_after_checks=1, recover_buttons=[ui_assets.GOTO_MAIN])

    assert ui.ui_get_current_page() is page
    assert ui.appear_then_click_calls == [ui_assets.GOTO_MAIN]


def test_ui_get_current_page_recovers_with_additional_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    page = _FakePage()
    monkeypatch.setattr(Page, "iter_pages", lambda: [page])
    ui = _FakeUI(visible_page=page, visible_after_checks=1, additional_results=[True])

    assert ui.ui_get_current_page() is page
    assert ui.appear_then_click_calls == [
        ui_assets.GOTO_MAIN,
        ui_white_assets.GOTO_MAIN_WHITE,
        raid_assets.RPG_HOME,
    ]
    assert ui.additional_calls == 1


def test_ui_get_current_page_raises_when_app_is_not_running(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Page, "iter_pages", list)
    ui = _FakeUI(app_running=False)

    with pytest.raises(GameNotRunningError):
        ui.ui_get_current_page()

    assert ui.device.app_is_running_count == 1
