from typing import TYPE_CHECKING, override

import numpy as np

from module.handler.assets import POPUP_CONFIRM
from module.shop.assets import (
    SHOP_BUY_CONFIRM_MISTAKE,
    SHOP_CLICK_SAFE_AREA,
    SHOP_REFRESH,
    SHOP_REFRESH_CHECK,
)
from module.shop.ui import ShopUI
from module.ui.assets import SHOP_BACK_ARROW

if TYPE_CHECKING:
    from collections.abc import Iterable, Iterator, Mapping

    from module.base.base import _HasArea
    from module.base.button import Button, MatchOffset
    from module.base.timer import Timer
    from module.base.type_alias import Area, Color, ImageArray


class _FakeDevice:
    def __init__(self) -> None:
        self.image = np.zeros((1, 1, 3), dtype=np.uint8)
        self.clicked = []

    def click(self, button: Button) -> None:
        self.clicked.append(button)


class _FakeShopUI(ShopUI):
    device: _FakeDevice

    def __init__(
        self,
        *,
        appear_results: Mapping[Button, Iterable[bool]] | None = None,
        color_results: Mapping[Color, Iterable[bool]] | None = None,
        popup_results: Iterable[bool] | None = None,
    ) -> None:
        self.device = _FakeDevice()
        self.appear_results = {id(button): list(results) for button, results in (appear_results or {}).items()}
        self.color_results = {color: list(results) for color, results in (color_results or {}).items()}
        self.popup_results = list(popup_results or [])
        self.interval_cleared = []
        self.ui_click_calls = []
        self.info_bar_handle_count = 0

    @override
    def loop(self, *, skip_first: bool = True, timeout: float | Timer | None = None) -> Iterator[ImageArray]:
        del skip_first, timeout
        return iter([self.device.image] * 6)

    def _pop_button_result(self, button: Button) -> bool:
        results = self.appear_results.get(id(button), [])
        if results:
            return results.pop(0)
        return False

    def appear(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return self._pop_button_result(button)

    @override
    def image_color_count(
        self,
        button: ImageArray | Button | _HasArea | Area,
        color: Color,
        threshold: int = 221,
        count: int = 50,
    ) -> bool:
        del button, threshold, count
        results = self.color_results.get(color, [])
        if results:
            return results.pop(0)
        return False

    @override
    def interval_clear(
        self,
        button: Button | list[Button] | tuple[Button, ...] | None,
        interval: float = 3,
    ) -> None:
        del interval
        if isinstance(button, (list, tuple)):
            self.interval_cleared.extend(button)
        elif button is not None:
            self.interval_cleared.append(button)

    def handle_popup_confirm(
        self,
        name: str = "",
        offset: MatchOffset | None = None,
        interval: float = 2,
    ) -> bool:
        _ = (name, offset, interval)
        if self.popup_results:
            return self.popup_results.pop(0)
        return False

    def ui_click(self, *args: object, **kwargs: object) -> None:
        self.ui_click_calls.append((args, kwargs))

    def handle_info_bar(self) -> bool:
        self.info_bar_handle_count += 1
        return True


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
