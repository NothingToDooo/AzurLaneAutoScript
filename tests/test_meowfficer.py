from typing import TYPE_CHECKING, override

from module.meowfficer.meowfficer import RewardMeowfficer

if TYPE_CHECKING:
    from module.ui.page import Page


type _DelayValue = bool | tuple[int, int]


class _Config:
    Meowfficer_BuyAmount = 0
    Meowfficer_OverflowCoins = -1
    Meowfficer_FortChoreMeowfficer = False
    MeowfficerTrain_Enable = True
    MeowfficerTrain_Mode = "once"

    def __init__(self) -> None:
        self.delay_calls: list[dict[str, _DelayValue]] = []

    def task_delay(self, **kwargs: _DelayValue) -> None:
        self.delay_calls.append(kwargs)


class _Reward(RewardMeowfficer):
    config: _Config

    def __init__(self) -> None:
        self.config = _Config()
        self.calls: list[str] = []

    @override
    def ui_ensure(self, destination: Page, *, skip_first_screenshot: bool = True) -> bool:
        del destination, skip_first_screenshot
        self.calls.append("ui_ensure")
        return False

    @override
    def wait_meowfficer_buttons(self, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        self.calls.append("wait_meowfficer_buttons")

    @override
    def meow_train(self) -> bool:
        self.calls.append("meow_train")
        return False

    @override
    def meow_is_sunday(self) -> bool:
        return False

    @override
    def meow_enhance(self) -> None:
        self.calls.append("meow_enhance")


def test_run_skips_enhance_for_non_seamless_weekday_training() -> None:
    reward = _Reward()

    reward.run()

    assert reward.calls == ["ui_ensure", "wait_meowfficer_buttons", "meow_train"]
    assert reward.config.delay_calls == [{"minute": (150, 210), "server_update": True}]
