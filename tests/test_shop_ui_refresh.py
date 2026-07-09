from module.handler.assets import POPUP_CONFIRM
from module.shop.assets import (
    SHOP_BUY_CONFIRM_MISTAKE,
    SHOP_CLICK_SAFE_AREA,
    SHOP_REFRESH,
    SHOP_REFRESH_CHECK,
)
from module.shop.ui import ShopUI
from module.ui.assets import SHOP_BACK_ARROW


class _FakeDevice:
    def __init__(self) -> None:
        self.clicked = []

    def click(self, button) -> None:
        self.clicked.append(button)


class _FakeShopUI(ShopUI):
    device: _FakeDevice

    def __init__(self, *, appear_results=None, color_results=None, popup_results=None) -> None:
        self.device = _FakeDevice()
        self.appear_results = {id(button): list(results) for button, results in (appear_results or {}).items()}
        self.color_results = {color: list(results) for color, results in (color_results or {}).items()}
        self.popup_results = list(popup_results or [])
        self.interval_cleared = []
        self.ui_click_calls = []
        self.info_bar_handle_count = 0

    def loop(self, *_args: object, **_kwargs: object):
        return range(6)

    def _pop_button_result(self, button) -> bool:
        results = self.appear_results.get(id(button), [])
        if results:
            return results.pop(0)
        return False

    def appear(self, button, *_args: object, **_kwargs) -> bool:
        return self._pop_button_result(button)

    def image_color_count(self, button, color, threshold=221, count=50) -> bool:
        _ = (button, threshold, count)
        results = self.color_results.get(color, [])
        if results:
            return results.pop(0)
        return False

    def interval_clear(self, button, *_args: object, **_kwargs: object) -> None:
        self.interval_cleared.append(button)

    def handle_popup_confirm(self, name="", offset=None, interval=2) -> bool:
        _ = (name, offset, interval)
        if self.popup_results:
            return self.popup_results.pop(0)
        return False

    def ui_click(self, *args, **kwargs) -> None:
        self.ui_click_calls.append((args, kwargs))

    def handle_info_bar(self) -> None:
        self.info_bar_handle_count += 1


def test_shop_refresh_clicks_available_refresh_and_confirms() -> None:
    ui = _FakeShopUI(
        appear_results={
            POPUP_CONFIRM: [False, True],
            SHOP_REFRESH_CHECK: [True],
            SHOP_BACK_ARROW: [False, True],
            SHOP_BUY_CONFIRM_MISTAKE: [False],
        },
        color_results={(49, 142, 207): [True]},
        popup_results=[True],
    )

    assert ui.shop_refresh()
    assert ui.device.clicked == [SHOP_REFRESH]
    assert ui.info_bar_handle_count == 1


def test_shop_refresh_handles_buy_confirm_mistake() -> None:
    ui = _FakeShopUI(
        appear_results={
            POPUP_CONFIRM: [True],
            SHOP_BACK_ARROW: [False],
            SHOP_BUY_CONFIRM_MISTAKE: [True],
        }
    )

    assert not ui.shop_refresh()
    assert ui.ui_click_calls == [
        (
            (SHOP_CLICK_SAFE_AREA,),
            {
                "appear_button": POPUP_CONFIRM,
                "check_button": SHOP_BACK_ARROW,
                "offset": (20, 30),
                "skip_first_screenshot": True,
            },
        )
    ]
    assert ui.info_bar_handle_count == 1


def test_shop_refresh_clears_interval_when_refresh_state_unknown() -> None:
    ui = _FakeShopUI(
        appear_results={
            SHOP_REFRESH_CHECK: [True],
            SHOP_BACK_ARROW: [True],
        },
        color_results={
            (49, 142, 207): [False],
            (54, 117, 161): [False],
            (52, 74, 94): [False],
        },
    )

    assert not ui.shop_refresh()
    assert ui.interval_cleared == [SHOP_REFRESH]
    assert ui.info_bar_handle_count == 1
