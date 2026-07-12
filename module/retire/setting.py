from typing import TYPE_CHECKING, Literal

from module.base.decorator import cached_property
from module.retire.assets import (
    RETIRE_SETTING_1,
    RETIRE_SETTING_2,
    RETIRE_SETTING_3,
    RETIRE_SETTING_4,
    RETIRE_SETTING_5_ALL,
    RETIRE_SETTING_5_PRESERVE,
    RETIRE_SETTING_ENTER,
    RETIRE_SETTING_QUIT,
)
from module.ui.setting import Setting
from module.ui.ui import UI

if TYPE_CHECKING:
    from module.base.button import Button

type QuickRetireFilter5 = Literal["keep_limit_break", "all"]


class QuickRetireSetting(Setting):
    def is_option_active(self, option: Button) -> bool:
        return self.main.image_color_count(option, color=(255, 255, 255), threshold=221, count=50)


class QuickRetireSettingHandler(UI):
    def _retire_setting_enter(self) -> None:
        """从退役页进入快速退役设置。"""
        self.ui_click(
            RETIRE_SETTING_ENTER,
            check_button=RETIRE_SETTING_QUIT,
            offset=(30, 100),
            retry_wait=3,
            skip_first_screenshot=True,
        )

    def _retire_setting_quit(self) -> None:
        """从快速退役设置返回退役页。"""
        self.ui_click(
            RETIRE_SETTING_QUIT,
            check_button=RETIRE_SETTING_ENTER,
            offset=(30, 100),
            retry_wait=3,
            skip_first_screenshot=True,
        )

    @cached_property
    def retire_setting(self) -> QuickRetireSetting:
        setting = QuickRetireSetting(name="RETIRE", main=self)
        setting.reset_first = False
        setting.add_setting(
            setting="filter_1", option_buttons=[RETIRE_SETTING_1], option_names=["R"], option_default="R"
        )
        setting.add_setting(
            setting="filter_2", option_buttons=[RETIRE_SETTING_2], option_names=["E"], option_default="E"
        )
        setting.add_setting(
            setting="filter_3", option_buttons=[RETIRE_SETTING_3], option_names=["N"], option_default="N"
        )
        setting.add_setting(
            setting="filter_4", option_buttons=[RETIRE_SETTING_4], option_names=["all"], option_default="all"
        )
        setting.add_setting(
            setting="filter_5",
            option_buttons=[RETIRE_SETTING_5_PRESERVE, RETIRE_SETTING_5_ALL],
            option_names=["keep_limit_break", "all"],
            option_default="all",
        )
        return setting

    def quick_retire_setting_set(self, filter_5: QuickRetireFilter5 | None = "all") -> None:
        """前三项固定优先 R、E、N，满破同名舰固定不保留。

        第五项接受 keep_limit_break、all 或 None，结束后返回退役页。
        """
        self._retire_setting_enter()
        self.retire_setting.set(filter_5=filter_5)
        self._retire_setting_quit()

    @staticmethod
    def server_support_quick_retire_setting_fallback() -> bool:
        return True
