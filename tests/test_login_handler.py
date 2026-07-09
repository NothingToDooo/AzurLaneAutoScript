from typing import ClassVar, override

import pytest

from module.handler import assets as handler_assets
from module.handler import login as login_module
from module.handler.login import LoginHandler
from module.ui.assets import BACK_ARROW, EVENT_LIST_CHECK, GOTO_MAIN


class _Timer:
    next_index: ClassVar[int] = 0
    reached_results: ClassVar[dict[int, list[bool]]] = {}

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def start(self) -> _Timer:
        return self

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> None:
        pass


class _Device:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []
        self.clicks: list[tuple[object, dict[str, object]]] = []

    def stuck_record_clear(self) -> None:
        self.calls.append(("stuck_record_clear",))

    def click_record_clear(self) -> None:
        self.calls.append(("click_record_clear",))

    def screenshot(self) -> None:
        self.calls.append(("screenshot",))

    def get_orientation(self) -> None:
        self.calls.append(("get_orientation",))

    def click_record_add(self, button: object) -> None:
        self.calls.append(("click_record_add", button))

    def click_record_check(self) -> None:
        self.calls.append(("click_record_check",))

    def click(self, button: object, **kwargs: object) -> None:
        self.clicks.append((button, kwargs))


class _LoginHandler(LoginHandler):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.main_results: list[bool] = []
        self.match_results: dict[str, list[bool]] = {}
        self.appear_results: dict[str, list[bool]] = {}
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.user_agreement_results: list[bool] = []
        self.popup_results: list[bool] = []
        self.urgent_results: list[bool] = []
        self.main_popup_results: list[bool] = []

    def login(self) -> bool:
        return self._handle_app_login()

    def _next_result[T](self, results: list[T], *, default: T) -> T:
        if results:
            return results.pop(0)
        return default

    def _button_name(self, button: object) -> str:
        return getattr(button, "name", repr(button))

    def is_in_main(self, *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("is_in_main",))
        return self._next_result(self.main_results, default=False)

    def match_template_color(self, button: object, *_args: object, **kwargs: object) -> bool:
        name = self._button_name(button)
        self.calls.append(("match_template_color", name, kwargs))
        return self._next_result(self.match_results.get(name, []), default=False)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        name = self._button_name(button)
        self.calls.append(("appear", name, kwargs))
        return self._next_result(self.appear_results.get(name, []), default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        name = self._button_name(button)
        self.calls.append(("appear_then_click", name, kwargs))
        return self._next_result(self.appear_then_click_results.get(name, []), default=False)

    def handle_cn_user_agreement(self) -> bool:
        self.calls.append(("handle_cn_user_agreement",))
        return self._next_result(self.user_agreement_results, default=False)

    def handle_popup_confirm(self, name: str = "", *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def handle_urgent_commission(self) -> bool:
        self.calls.append(("handle_urgent_commission",))
        return self._next_result(self.urgent_results, default=False)

    @override
    def ui_page_main_popups(self, get_ship: bool = False) -> bool:
        self.calls.append(("ui_page_main_popups", get_ship))
        return self._next_result(self.main_popup_results, default=False)


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    monkeypatch.setattr(login_module, "Timer", _Timer)


def test_app_login_confirms_main_page() -> None:
    handler = _LoginHandler()
    handler.main_results = [True]
    _Timer.reached_results = {0: [True]}

    assert handler.login() is True

    assert handler.device.calls == [
        ("stuck_record_clear",),
        ("click_record_clear",),
        ("screenshot",),
    ]


def test_app_login_clicks_login_and_handles_main_popup() -> None:
    handler = _LoginHandler()
    handler.match_results = {handler_assets.LOGIN_CHECK.name: [True]}
    handler.main_popup_results = [True]

    assert handler.login() is True

    assert handler.device.clicks == [(handler_assets.LOGIN_CHECK, {})]
    assert ("ui_page_main_popups", True) in handler.calls


def test_app_login_handles_android_no_respond() -> None:
    handler = _LoginHandler()
    handler.appear_results = {handler_assets.ANDROID_NO_RESPOND.name: [True, False]}
    handler.main_popup_results = [False, True]

    assert handler.login() is True

    assert ("click_record_add", handler_assets.ANDROID_NO_RESPOND) in handler.device.calls
    assert ("click_record_check",) in handler.device.calls
    assert handler.device.clicks == [(handler_assets.ANDROID_NO_RESPOND, {"control_check": False})]


def test_app_login_leaves_event_list_with_back_arrow() -> None:
    handler = _LoginHandler()
    handler.appear_results = {EVENT_LIST_CHECK.name: [True, False]}
    handler.main_popup_results = [False, True]

    assert handler.login() is True

    assert handler.device.clicks == [(BACK_ARROW, {})]


def test_app_login_clicks_goto_main() -> None:
    handler = _LoginHandler()
    handler.appear_then_click_results = {GOTO_MAIN.name: [True, False]}
    handler.main_popup_results = [False, True]

    assert handler.login() is True

    assert ("appear_then_click", GOTO_MAIN.name, {"offset": (30, 30), "interval": 5}) in handler.calls
