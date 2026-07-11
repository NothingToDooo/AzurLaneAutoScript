import copy
from typing import TYPE_CHECKING

from module.base.button import Button, ButtonGrid
from module.base.timer import Timer
from module.config.utils import dict_to_kv
from module.exception import ScriptError
from module.logger import logger

if TYPE_CHECKING:
    from module.base.base import ModuleBase

INVALID_DEFAULT_OPTION_TEMPLATE = 'Define option_default="{default}", but default is not in option_names={options}'


class Setting:
    def __init__(self, name="Setting", main: ModuleBase | None = None):
        self.name = name
        self._main: ModuleBase | None = main
        self.reset_first = True
        self.need_deselect = False
        self.settings: dict[tuple[str, str], Button] = {}
        self.settings_default: dict[str, str] = {}

    @property
    def main(self) -> ModuleBase:
        if self._main is None:
            msg = f"{self.name} setting is not bound to a module"
            raise ScriptError(msg)
        return self._main

    @main.setter
    def main(self, value: ModuleBase | None) -> None:
        self._main = value

    def add_setting(self, setting, option_buttons, option_names, option_default):
        """option_buttons 与 option_names 必须等长，option_default 必须在 option_names 中。"""
        if isinstance(option_buttons, ButtonGrid):
            option_buttons = option_buttons.buttons
        for option, option_name in zip(option_buttons, option_names, strict=True):
            self.settings[(setting, option_name)] = option

        if option_default not in option_names:
            message = INVALID_DEFAULT_OPTION_TEMPLATE.format(default=option_default, options=option_names)
            raise ScriptError(message)
        self.settings_default[setting] = option_default

    def is_option_active(self, option: Button) -> bool:
        return self.main.image_color_count(
            option, color=(181, 142, 90), threshold=235, count=250
        ) or self.main.image_color_count(option, color=(74, 117, 189), threshold=235, count=250)

    def _product_setting_status(self, **kwargs) -> dict[Button, bool]:
        """kwargs 的值可为单选项、选项列表或 None；None 表示不修改该项。

        返回 Button 到目标启用状态的映射，bool 表示该按钮是否应激活。
        """
        required_options = copy.deepcopy(self.settings_default)
        required_options.update(kwargs)

        status: dict[Button, bool] = {}
        for key, option_button in self.settings.items():
            setting, option_name = key
            required = required_options[setting]
            if required is not None:
                required = required if isinstance(required, list) else [required]
                status[option_button] = option_name in required

        return status

    def show_active_buttons(self):
        active = []
        for key, option_button in self.settings.items():
            setting, option_name = key
            if self.is_option_active(option_button):
                active.append(f"{setting}/{option_name}")

        logger.attr(self.name, ", ".join(active))

    def get_buttons_to_click(self, status: dict[Button, bool]) -> list[Button]:
        click = []
        for option_button, enable in status.items():
            active = self.is_option_active(option_button)
            if enable and not active:
                click.append(option_button)
            if self.need_deselect and not enable and active:
                click.append(option_button)
        return click

    def _set_execute(self, **kwargs):
        status = self._product_setting_status(**kwargs)

        logger.info(f"Setting options {self.name}, {dict_to_kv(kwargs)}")
        skip_first_screenshot = True
        retry = Timer(1, count=2)
        timeout = Timer(10, count=20).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.main.device.screenshot()

            if timeout.reached():
                logger.warning(f"Set {self.name} options timeout, assuming current options are correct.")
                return False

            self.show_active_buttons()
            clicks = self.get_buttons_to_click(status)
            if clicks:
                if retry.reached():
                    for button in clicks:
                        self.main.device.click(button)
                    retry.reset()
            else:
                return True
        return False

    def set(self, **kwargs):
        """kwargs 的值可为单选项、选项列表或 None；None 表示不修改该项。"""
        if self.reset_first:
            self._set_execute()
        return self._set_execute(**kwargs)
