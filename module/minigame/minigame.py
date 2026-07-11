from abc import ABC, abstractmethod
from dataclasses import dataclass
from importlib import import_module
from typing import Protocol, runtime_checkable

from module.combat.assets import GET_ITEMS_1
from module.logger import logger
from module.minigame import assets as minigame_assets
from module.ocr.ocr import Digit
from module.ui.assets import ACADEMY_GOTO_GAME_ROOM, GAME_ROOM_CHECK
from module.ui.page import page_academy, page_game_room
from module.ui.scroll import Scroll
from module.ui.ui import UI

OCR_COIN = Digit(minigame_assets.COIN_HOLDER, name="OCR_COIN", letter=(255, 235, 115), threshold=128)
MINIGAME_SCROLL = Scroll(minigame_assets.MINIGAME_SCROLL_AREA, color=(247, 247, 247), name="MINIGAME_SCROLL")


@dataclass(slots=True)
class _MinigameRunState:
    coin_collected: bool = False
    play_count: int = 0


@runtime_checkable
class MinigamePlayer(Protocol):
    def minigame_run(self) -> bool: ...


class MinigameRun(UI, ABC):
    def minigame_run(self, *, skip_first_screenshot: bool = True) -> bool:
        """从游戏室主页游玩一次并返回；无法或无需投币时返回 False。"""
        logger.hr("Minigame run", level=1)

        logger.info("Enter minigame")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            # 小游戏主页和小游戏列表都有 GOTO_CHOOSE_GAME。
            if (
                self.appear(GAME_ROOM_CHECK, offset=(5, 5))
                and not self.appear(minigame_assets.GOTO_CHOOSE_GAME, offset=(20, 20))
                and MINIGAME_SCROLL.appear(main=self)
            ):
                break
            # 无法获得更多游戏券的弹窗。
            if self.deal_popup():
                continue
            if self.appear_then_click(minigame_assets.GOTO_CHOOSE_GAME, offset=(5, 5), interval=3):
                # GOTO_CHOOSE_GAME 位于安全区域，在列表页点击不会进入具体小游戏。
                continue

        logger.info("Choose minigame")
        self.choose_game()
        add_coin_result = self.use_coin()
        if add_coin_result:
            logger.hr("Play minigame", level=2)
            self.play_game()
        logger.info("Exit minigame")
        self.exit_game()
        return add_coin_result

    def deal_popup(self) -> bool:
        """处理通用及小游戏弹窗；返回 True 时调用方需重新截图。"""
        # 具体小游戏自己的弹窗。
        if self.deal_specific_popup():
            return True
        if self.handle_popup_confirm("TICKETS_FULL"):
            self.interval_reset(minigame_assets.COIN_POPUP, interval=3)
            return True
        # 代币超过 31 时会出现弹窗。
        if self.appear_then_click(minigame_assets.COIN_POPUP, offset=(5, 5), interval=3):
            return True
        # 领取代币或游戏券。
        return bool(self.appear_then_click(GET_ITEMS_1, offset=(5, 5), interval=3))

    @abstractmethod
    def deal_specific_popup(self) -> bool:
        """处理具体小游戏弹窗，并返回调用方是否需要重新截图。"""

    @abstractmethod
    def choose_game(self, *, skip_first_screenshot: bool = True) -> None:
        """供子类实现从游戏列表进入具体小游戏。"""

    @abstractmethod
    def use_coin(self) -> bool:
        """投入本局所需代币，并返回是否可以开始。"""

    @abstractmethod
    def play_game(self, *, skip_first_screenshot: bool = True) -> None:
        """执行具体小游戏的一局流程。"""

    @abstractmethod
    def exit_game(self, *, skip_first_screenshot: bool = True) -> None:
        """供子类实现从小游戏退出到游戏列表。"""


class Minigame(UI):
    def get_coin_amount(self, *, skip_first_screenshot: bool = True) -> int:
        """在游戏室主页识别代币数，并把结果限制在 0～40。"""
        if not skip_first_screenshot:
            self.device.screenshot()
        amount = OCR_COIN.ocr_single(self.device.image)
        return min(40, amount)

    def go_to_main_page(self, *, skip_first_screenshot: bool = True) -> None:
        """从游戏室主页或列表页回到游戏室主页。"""
        logger.info("minigame go_to_main_page")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.ui_additional():
                continue
            if self.appear_then_click(minigame_assets.COIN_POPUP, offset=(5, 5), interval=2):
                continue
            if self.appear(GAME_ROOM_CHECK, offset=(5, 5)) and not self.appear(
                minigame_assets.GOTO_CHOOSE_GAME, offset=(5, 5)
            ):
                self.appear_then_click(minigame_assets.BACK, offset=(5, 5), interval=2)
                continue
            if self.appear(minigame_assets.GOTO_CHOOSE_GAME, offset=(5, 5)):
                break

    def collect_coin(self, *, skip_first_screenshot: bool = True) -> bool:
        """回到游戏室主页收取代币，返回是否发生领取。"""
        coin_collected = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.ui_additional():
                continue
            if self.appear_then_click(minigame_assets.COIN_POPUP, offset=(5, 5), interval=3):
                continue
            # 游戏室和选择游戏页共用同一个页头，先回到游戏室主页。
            if self.appear(GAME_ROOM_CHECK, offset=(5, 5)) and not self.appear(
                minigame_assets.GOTO_CHOOSE_GAME, offset=(5, 5)
            ):
                self.appear_then_click(minigame_assets.BACK, offset=(5, 5), interval=3)
                continue
            # 收取代币。
            if not coin_collected and self.appear(minigame_assets.COIN, offset=(5, 5)):
                self.appear_then_click(minigame_assets.COIN, offset=(5, 5), interval=3)
                coin_collected = True
                continue
            if self.appear(minigame_assets.GOTO_CHOOSE_GAME, offset=(5, 5)):
                break
        return coin_collected

    def run(self) -> None:
        """从任意页面进入游戏室并消耗可用代币。"""
        self._minigame_enter_game_room()
        self.go_to_main_page()

        specific_game_name = "new_year_challenge"
        minigame_instance = self._create_minigame_instance(specific_game_name)
        self._spend_minigame_coins(minigame_instance, specific_game_name)
        self.config.task_delay(server_update=True)

    def _minigame_enter_game_room(self) -> None:
        self.ui_ensure(page_academy)
        # 学院页 -> 游戏室。
        for _ in self.loop():
            if self.ui_page_appear(page_game_room):
                break
            if self.ui_page_appear(page_academy, interval=5):
                self.device.click(ACADEMY_GOTO_GAME_ROOM)
                continue
            # 达到每月游戏券上限时，确认仍继续游玩。
            if self.handle_popup_confirm("MINIGAME_ENTER"):
                continue

    def _create_minigame_instance(self, specific_game_name: str) -> MinigamePlayer | None:
        if specific_game_name == "new_year_challenge":
            module = import_module("module.minigame.new_year_challenge")
            game_class = getattr(module, "NewYearChallenge", None)
            if not isinstance(game_class, type):
                message = "new_year_challenge does not export a game class"
                raise TypeError(message)
            instance = game_class(config=self.config, device=self.device)
            if not isinstance(instance, MinigamePlayer):
                message = "new_year_challenge does not implement MinigamePlayer"
                raise TypeError(message)
            return instance
        return None

    def _spend_minigame_coins(
        self,
        minigame_instance: MinigamePlayer | None,
        specific_game_name: str,
    ) -> None:
        state = _MinigameRunState()
        while state.play_count < 10:
            coin_count = self.get_coin_amount()
            logger.info(f"coin count : {coin_count}")

            if self._collect_minigame_coin_if_needed(state, coin_count):
                continue
            if self._minigame_coin_empty(coin_count):
                break
            if self._play_minigame_once(minigame_instance, specific_game_name, state):
                continue
            break

    def _collect_minigame_coin_if_needed(self, state: _MinigameRunState, coin_count: int) -> bool:
        if coin_count > 30 or state.coin_collected:
            return False

        state.coin_collected = True
        return self.collect_coin()

    @staticmethod
    def _minigame_coin_empty(coin_count: int) -> bool:
        if coin_count == 0:
            logger.info(f"coin count : {coin_count}, finished")
            return True
        return False

    @staticmethod
    def _play_minigame_once(
        minigame_instance: MinigamePlayer | None,
        specific_game_name: str,
        state: _MinigameRunState,
    ) -> bool:
        logger.info("coin count > 0, spend")
        if minigame_instance is None:
            logger.error(f"unknown game name {specific_game_name}")
            return False
        if not minigame_instance.minigame_run():
            return False

        state.play_count += 1
        return True
