from types import SimpleNamespace

from module.daily import assets as daily_assets
from module.daily.daily import Daily


class _Device:
    def __init__(self) -> None:
        self.clicks = []
        self.screenshot_count = 0

    def click(self, button) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _Daily(Daily):
    def __init__(self, *, use_skip: bool = True) -> None:
        self.config = SimpleNamespace(Daily_UseDailySkip=use_skip)
        self.device = _Device()
        self.appear_results = {}
        self.appear_then_click_results = {}
        self.get_items_results = []
        self.automation_confirm_results = []
        self.additional_results = []
        self.popup_results = []
        self.info_bar_results = []
        self.combat_results = []

    @staticmethod
    def _next(results):
        if results:
            return results.pop(0)
        return False

    def set_appear(self, button, *, results: list[bool]) -> None:
        self.appear_results[button.name] = results

    def set_appear_then_click(self, button, *, results: list[bool]) -> None:
        self.appear_then_click_results[button.name] = results

    def appear(self, button, **_kwargs):
        return self._next(self.appear_results.setdefault(button.name, []))

    def appear_then_click(self, button, **_kwargs):
        result = self._next(self.appear_then_click_results.setdefault(button.name, []))
        if result:
            self.device.click(button)
        return result

    def handle_get_items(self):
        return self._next(self.get_items_results)

    def handle_combat_automation_confirm(self):
        return self._next(self.automation_confirm_results)

    def handle_daily_additional(self):
        return self._next(self.additional_results)

    def handle_popup_confirm(self, popup):
        assert popup == "DAILY_SKIP"
        return self._next(self.popup_results)

    def info_bar_count(self):
        return self._next(self.info_bar_results)

    def combat_appear(self):
        return self._next(self.combat_results)


def test_daily_enter_clicks_entry_before_rewards() -> None:
    daily = _Daily()
    daily.set_appear(daily_assets.DAILY_ENTER_CHECK, results=[True, False, False])
    daily.set_appear(daily_assets.DAILY_SKIP, results=[True])
    daily.set_appear_then_click(daily_assets.DAILY_SKIP, results=[False])
    daily.get_items_results = [True, False]

    assert daily.daily_enter(daily_assets.DAILY_MISSION_1) is False

    assert daily.device.clicks == [daily_assets.DAILY_MISSION_1]
    assert daily.device.screenshot_count == 2


def test_daily_enter_uses_skip_button_when_enabled() -> None:
    daily = _Daily(use_skip=True)
    daily.set_appear(daily_assets.DAILY_ENTER_CHECK, results=[False, False])
    daily.set_appear(daily_assets.DAILY_SKIP, results=[False])
    daily.set_appear_then_click(daily_assets.DAILY_SKIP, results=[True, False])
    daily.combat_results = [True]

    assert daily.daily_enter(daily_assets.DAILY_MISSION_1) is True

    assert daily.device.clicks == [daily_assets.DAILY_SKIP]


def test_daily_enter_returns_true_when_combat_appears() -> None:
    daily = _Daily(use_skip=False)
    daily.set_appear(daily_assets.DAILY_ENTER_CHECK, results=[False, False])
    daily.set_appear(daily_assets.DAILY_SKIP, results=[False])
    daily.set_appear_then_click(daily_assets.DAILY_NORMAL_RUN, results=[False])
    daily.combat_results = [True]

    assert daily.daily_enter(daily_assets.DAILY_MISSION_1) is True
