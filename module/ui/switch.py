from typing import TYPE_CHECKING, TypedDict

from module.base.timer import Timer
from module.exception import ScriptError
from module.logger import logger

if TYPE_CHECKING:
    from module.base.base import ModuleBase
    from module.base.button import Button, MatchOffset


class SwitchState(TypedDict):
    state: str
    check_button: Button
    click_button: Button
    offset: MatchOffset


UNKNOWN_STATE_NAME_MESSAGE = 'Cannot use "unknown" as state name'
INVALID_SWITCH_STATE_TEMPLATE = "Switch {name} received an invalid state: {state}"


class Switch:
    """在多个已知状态间检测并重试切换。

    is_selector=True 时点击目标项；否则点击当前开关位置。
    """

    def __init__(
        self,
        name: str = "Switch",
        *,
        is_selector: bool = False,
        offset: MatchOffset = 0,
    ) -> None:
        self.name = name
        self.is_selector = is_selector
        self._offset = offset
        self.state_list: list[SwitchState] = []
        self.set_unknown_timer = Timer(5, count=10)
        self.set_click_timer = Timer(1, count=2)
        self.wait_timeout = Timer(2, count=4)

    def add_state(
        self,
        state: str,
        check_button: Button,
        click_button: Button | None = None,
        offset: MatchOffset = 0,
    ) -> None:
        """'unknown' 是检测保留值，不能注册为状态名。"""
        if state == "unknown":
            raise ScriptError(UNKNOWN_STATE_NAME_MESSAGE)
        self.state_list.append(
            {
                "state": state,
                "check_button": check_button,
                "click_button": click_button if click_button is not None else check_button,
                "offset": offset or self._offset,
            }
        )

    @property
    def offset(self) -> MatchOffset:
        return self._offset

    @offset.setter
    def offset(self, value: MatchOffset) -> None:
        self._offset = value
        for data in self.state_list:
            data["offset"] = value

    def appear(self, main: ModuleBase) -> bool:
        return self.get(main=main) != "unknown"

    def get(self, main: ModuleBase) -> str:
        """未匹配任何已知状态时返回 'unknown'。"""
        for data in self.state_list:
            if main.appear(data["check_button"], offset=data["offset"]):
                return data["state"]

        return "unknown"

    def click(self, state: str, main: ModuleBase) -> None:
        button = self.get_data(state)["click_button"]
        main.device.click(button)

    def get_data(self, state: str) -> SwitchState:
        """状态未注册时抛出 ScriptError。"""
        for row in self.state_list:
            if row["state"] == state:
                return row

        message = INVALID_SWITCH_STATE_TEMPLATE.format(name=self.name, state=state)
        raise ScriptError(message)

    def handle_additional(self, _main: ModuleBase) -> bool:  # ruff:ignore[no-self-use]
        """额外弹窗处理钩子；默认表示未处理。"""
        return False

    def set(
        self,
        state: str,
        main: ModuleBase,
        *,
        skip_first_screenshot: bool = True,
    ) -> bool:
        logger.info(f"{self.name} set to {state}")
        self.get_data(state)

        changed = False
        has_unknown = False
        unknown_timer = self.set_unknown_timer.reset()
        click_timer = self.set_click_timer.clear()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            current = self.get(main=main)
            logger.attr(self.name, current)

            if current == state:
                return changed

            if self.handle_additional(main):
                continue

            if current == "unknown":
                if unknown_timer.reached():
                    logger.warning(f"Switch {self.name} has states evaluated to unknown, asset should be re-verified")
                    has_unknown = True
                    unknown_timer.reset()
                # 短暂 unknown 通常是切换动画，不点击；持续超时则可能是未注册的新状态。
                # 此时忽略新状态，仍允许在已知状态间切换。
                if not has_unknown:
                    continue
            else:
                unknown_timer.reset()

            if click_timer.reached():
                # 选择器点击目标；普通开关点击当前状态，unknown 没有可点位置时退回目标状态。
                click_state = state if self.is_selector or current == "unknown" else current
                self.click(click_state, main=main)
                changed = True
                click_timer.reset()
                unknown_timer.reset()
        return changed

    def wait(self, main: ModuleBase, *, skip_first_screenshot: bool = True) -> bool:
        timeout = self.wait_timeout.reset()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                main.device.screenshot()

            current = self.get(main=main)
            logger.attr(self.name, current)

            if current != "unknown":
                return True
            if timeout.reached():
                logger.warning(f"{self.name} wait activated timeout")
                return False

            if self.handle_additional(main):
                continue
        return False
