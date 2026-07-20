from typing import Literal

from module.combat.assets import GET_ITEMS_1
from module.exception import GameStuckError
from module.handler import assets as handler_assets
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.template.assets import TEMPLATE_FORMATION_1, TEMPLATE_FORMATION_2, TEMPLATE_FORMATION_3
from module.ui.switch import Switch

# 2023.10.19，每行图标从 2 个增加到 3 个。
FORMATION = Switch("Formation", offset=(100, 200))
FORMATION.add_state("line_ahead", check_button=handler_assets.FORMATION_1)
FORMATION.add_state("double_line", check_button=handler_assets.FORMATION_2)
FORMATION.add_state("diamond", check_button=handler_assets.FORMATION_3)

SUBMARINE_HUNT = Switch("Submarine_hunt", offset=(200, 200))
SUBMARINE_HUNT.add_state("on", check_button=handler_assets.SUBMARINE_HUNT_ON)
SUBMARINE_HUNT.add_state("off", check_button=handler_assets.SUBMARINE_HUNT_OFF)

SUBMARINE_VIEW = Switch("Submarine_view", offset=(100, 200))
SUBMARINE_VIEW.add_state("on", check_button=handler_assets.SUBMARINE_VIEW_ON)
SUBMARINE_VIEW.add_state("off", check_button=handler_assets.SUBMARINE_VIEW_OFF)

MOB_MOVE_OFFSET = (120, 200)
AIR_STRIKE_OFFSET = (120, 200)
STRATEGY_TRANSITION_BUDGET = 30.0


class StrategyHandler(InfoHandler):
    fleet_1_formation_fixed = False
    fleet_2_formation_fixed = False

    def strategy_open(self, *, skip_first_screenshot: bool = True) -> None:
        logger.info("Strategy open")
        for _ in self.loop(skip_first=skip_first_screenshot, timeout=STRATEGY_TRANSITION_BUDGET):
            if self.appear(handler_assets.STRATEGY_OPENED, offset=200):
                break

            if self.appear(handler_assets.IN_MAP, interval=5) and not self.appear(
                handler_assets.STRATEGY_OPENED, offset=200
            ):
                self.device.click(handler_assets.STRATEGY_OPEN)
                continue

            # 处理漏掉的神秘事件。
            if self.appear_then_click(GET_ITEMS_1, offset=5):
                continue
        else:
            self._raise_strategy_transition_exhausted("open")

    def strategy_close(self, *, skip_first_screenshot: bool = True) -> None:
        logger.info("Strategy close")
        for _ in self.loop(skip_first=skip_first_screenshot, timeout=STRATEGY_TRANSITION_BUDGET):
            if self.appear_then_click(handler_assets.STRATEGY_OPENED, offset=200, interval=5):
                continue

            if self.appear(handler_assets.IN_MAP, offset=200):
                break
        else:
            self._raise_strategy_transition_exhausted("close")

    def strategy_set_execute(
        self,
        formation: Literal["line_ahead", "double_line", "diamond"] | None = None,
        *,
        sub_view: bool | None = None,
        sub_hunt: bool | None = None,
    ) -> None:
        """在 STRATEGY_OPENED 中设置阵型；formation 接受 line_ahead、double_line、diamond 或 None。"""
        logger.info(f"Strategy set: formation={formation}, submarine_view={sub_view}, submarine_hunt={sub_hunt}")

        if formation is not None:
            FORMATION.set(formation, main=self)
        if sub_view is not None:
            if SUBMARINE_VIEW.appear(main=self):
                SUBMARINE_VIEW.set("on" if sub_view else "off", main=self)
            else:
                logger.warning("Setting up submarine_view but no icon appears")
        if sub_hunt is not None:
            if SUBMARINE_HUNT.appear(main=self):
                SUBMARINE_HUNT.set("on" if sub_hunt else "off", main=self)
            else:
                logger.warning("Setting up submarine_hunt but no icon appears")

    def handle_strategy(self, index: int) -> bool:
        if getattr(self, f"fleet_{index}_formation_fixed"):
            return False
        expected_formation = getattr(self.config, f"Fleet_Fleet{index}Formation")
        if self._strategy_get_from_map_buff() == expected_formation and not self.config.Submarine_Fleet:
            logger.info("Skip strategy bar check.")
            setattr(self, f"fleet_{index}_formation_fixed", True)
            return False

        self.strategy_open()
        self.strategy_set_execute(
            formation=expected_formation,
            sub_view=False,
            sub_hunt=bool(self.config.Submarine_Fleet) and self.config.Submarine_Mode in ["hunt_only", "hunt_and_boss"],
        )
        self.strategy_close()
        setattr(self, f"fleet_{index}_formation_fixed", True)
        return True

    def _strategy_get_from_map_buff(self) -> Literal["line_ahead", "double_line", "diamond", "unknown"]:
        image = self.image_crop(handler_assets.MAP_BUFF, copy=False)
        if TEMPLATE_FORMATION_2.match(image):
            buff = "double_line"
        elif TEMPLATE_FORMATION_1.match(image):
            buff = "line_ahead"
        elif TEMPLATE_FORMATION_3.match(image):
            buff = "diamond"
        else:
            buff = "unknown"

        logger.attr("Map_buff", buff)
        return buff

    def is_in_strategy_submarine_move(self) -> bool:
        return self.appear(handler_assets.SUBMARINE_MOVE_CONFIRM, offset=(20, 20))

    def strategy_submarine_move_enter(self, *, skip_first_screenshot: bool = True) -> None:
        """页面状态：STRATEGY_OPENED 或 SUBMARINE_MOVE_ENTER → SUBMARINE_MOVE_CONFIRM。"""
        logger.info("Submarine move enter")
        for _ in self.loop(skip_first=skip_first_screenshot, timeout=STRATEGY_TRANSITION_BUDGET):
            if self.appear(handler_assets.SUBMARINE_MOVE_ENTER, offset=200, interval=5):
                self.device.click(handler_assets.SUBMARINE_MOVE_ENTER)

            if self.appear(handler_assets.SUBMARINE_MOVE_CONFIRM, offset=(20, 20)):
                break
        else:
            self._raise_strategy_transition_exhausted("enter submarine move")

    def strategy_submarine_move_confirm(self, *, skip_first_screenshot: bool = True) -> None:
        """页面状态：SUBMARINE_MOVE_CONFIRM → STRATEGY_OPENED 或 SUBMARINE_MOVE_ENTER。"""
        logger.info("Submarine move confirm")
        for _ in self.loop(skip_first=skip_first_screenshot, timeout=STRATEGY_TRANSITION_BUDGET):
            self.appear_then_click(handler_assets.SUBMARINE_MOVE_CONFIRM, offset=(20, 20), interval=5)
            self.handle_popup_confirm("SUBMARINE_MOVE")

            if self.appear(handler_assets.SUBMARINE_MOVE_ENTER, offset=200):
                break
        else:
            self._raise_strategy_transition_exhausted("confirm submarine move")

    def strategy_submarine_move_cancel(self, *, skip_first_screenshot: bool = True) -> None:
        """页面状态：SUBMARINE_MOVE_CONFIRM → STRATEGY_OPENED 或 SUBMARINE_MOVE_ENTER。"""
        logger.info("Submarine move cancel")
        for _ in self.loop(skip_first=skip_first_screenshot, timeout=STRATEGY_TRANSITION_BUDGET):
            self.appear_then_click(handler_assets.SUBMARINE_MOVE_CANCEL, offset=(20, 20), interval=5)
            self.handle_popup_confirm("SUBMARINE_MOVE")

            if self.appear(handler_assets.SUBMARINE_MOVE_ENTER, offset=200):
                break
        else:
            self._raise_strategy_transition_exhausted("cancel submarine move")

    def is_in_strategy_mob_move(self) -> bool:
        return self.appear(handler_assets.MOB_MOVE_CANCEL, offset=(20, 20))

    def strategy_has_mob_move(self) -> bool:
        """在 STRATEGY_OPENED 中检测道中队移动入口，不改变页面。"""
        return self.match_template_color(handler_assets.MOB_MOVE_ENTER, offset=MOB_MOVE_OFFSET)

    def strategy_mob_move_enter(self, *, skip_first_screenshot: bool = True) -> None:
        """页面状态：STRATEGY_OPENED 或 MOB_MOVE_ENTER → MOB_MOVE_CANCEL。"""
        logger.info("Mob move enter")
        for _ in self.loop(skip_first=skip_first_screenshot, timeout=STRATEGY_TRANSITION_BUDGET):
            if self.appear(handler_assets.MOB_MOVE_CANCEL, offset=(20, 20)):
                break

            if self.appear_then_click(handler_assets.MOB_MOVE_ENTER, offset=MOB_MOVE_OFFSET, interval=5):
                continue
        else:
            self._raise_strategy_transition_exhausted("enter enemy move")

    def strategy_mob_move_cancel(self, *, skip_first_screenshot: bool = True) -> None:
        """页面状态：MOB_MOVE_CANCEL → STRATEGY_OPENED 或 MOB_MOVE_ENTER。"""
        logger.info("Mob move cancel")
        for _ in self.loop(skip_first=skip_first_screenshot, timeout=STRATEGY_TRANSITION_BUDGET):
            if self.appear(handler_assets.MOB_MOVE_ENTER, offset=MOB_MOVE_OFFSET):
                break

            if self.appear_then_click(handler_assets.MOB_MOVE_CANCEL, offset=(20, 20), interval=5):
                continue
        else:
            self._raise_strategy_transition_exhausted("cancel enemy move")

    def is_in_strategy_air_strike(self) -> bool:
        return self.appear(handler_assets.AIR_STRIKE_CONFIRM, offset=(20, 20))

    def strategy_has_air_strike(self) -> bool:
        """在 STRATEGY_OPENED 中检测空袭入口，不改变页面。"""
        return self.match_template_color(handler_assets.AIR_STRIKE_ENTER, offset=(150, 200))

    def strategy_air_strike_enter(self, *, skip_first_screenshot: bool = True) -> None:
        """页面状态：STRATEGY_OPENED 或 AIR_STRIKE_ENTER → AIR_STRIKE_CONFIRM。"""
        logger.info("Air strike enter")
        for _ in self.loop(skip_first=skip_first_screenshot, timeout=STRATEGY_TRANSITION_BUDGET):
            if self.appear(handler_assets.AIR_STRIKE_CONFIRM, offset=(20, 20)):
                break
            if self.appear_then_click(handler_assets.AIR_STRIKE_ENTER, offset=(150, 200), interval=5):
                continue
        else:
            self._raise_strategy_transition_exhausted("enter air strike")

    def strategy_air_strike_cancel(self, *, skip_first_screenshot: bool = True) -> None:
        """页面状态：AIR_STRIKE_CONFIRM → STRATEGY_OPENED 或 AIR_STRIKE_ENTER。"""
        logger.info("Air strike cancel")
        for _ in self.loop(skip_first=skip_first_screenshot, timeout=STRATEGY_TRANSITION_BUDGET):
            if self.appear(handler_assets.AIR_STRIKE_ENTER, offset=(150, 200)):
                break
            if self.appear_then_click(handler_assets.AIR_STRIKE_CANCEL, offset=(20, 20), interval=5):
                continue
        else:
            self._raise_strategy_transition_exhausted("cancel air strike")

    @staticmethod
    def _raise_strategy_transition_exhausted(operation: str) -> None:
        message = (
            f"strategy page failed to {operation}; "
            f"transition budget exhausted ({STRATEGY_TRANSITION_BUDGET:g}-second baseline)"
        )
        raise GameStuckError(message)
