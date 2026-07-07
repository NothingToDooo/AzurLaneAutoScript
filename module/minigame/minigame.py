import module.config.server as server
from module.combat.assets import GET_ITEMS_1
from module.logger import logger
from module.minigame import assets as minigame_assets
from module.ocr.ocr import Digit
from module.ui.assets import ACADEMY_GOTO_GAME_ROOM, GAME_ROOM_CHECK
from module.ui.page import page_academy, page_game_room
from module.ui.scroll import Scroll
from module.ui.ui import UI

if server.server != "jp":
    OCR_COIN = Digit(minigame_assets.COIN_HOLDER, name="OCR_COIN", letter=(255, 235, 115), threshold=128)
else:
    OCR_COIN = Digit(minigame_assets.COIN_HOLDER, name="OCR_COIN", letter=(211, 196, 95), threshold=128)
MINIGAME_SCROLL = Scroll(minigame_assets.MINIGAME_SCROLL_AREA, color=(247, 247, 247), name="MINIGAME_SCROLL")


class MinigameRun(UI):
    def minigame_run(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_game_room main_page
            out: page_game_room main_page
        Return:
            False if unable or unnecessary to play
        """
        logger.hr("Minigame run", level=1)

        # page_game_room main_page -> MINIGAME_SCROLL
        logger.info("Enter minigame")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            # 小游戏主页和小游戏列表都有 GOTO_CHOOSE_GAME。
            if self.appear(GAME_ROOM_CHECK, offset=(5, 5)) and not self.appear(
                minigame_assets.GOTO_CHOOSE_GAME, offset=(20, 20)
            ):
                if MINIGAME_SCROLL.appear(main=self):
                    break
            # 无法获得更多游戏券的弹窗。
            if self.deal_popup():
                continue
            if self.appear_then_click(minigame_assets.GOTO_CHOOSE_GAME, offset=(5, 5), interval=3):
                # GOTO_CHOOSE_GAME 位于安全区域，在列表页点击不会进入具体小游戏。
                continue

        logger.info("Choose minigame")
        self.choose_game()
        # try to add coins, if failed, skip play
        add_coin_result = self.use_coin()
        if add_coin_result:
            logger.hr("Play minigame", level=2)
            self.play_game()
        logger.info("Exit minigame")
        self.exit_game()
        return add_coin_result

    def deal_popup(self):
        """
        处理可能出现的弹窗。

        返回 True 时需要重新截图。
        """
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

    def deal_specific_popup(self):
        return False

    def choose_game(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_game_room choosing_game
            out: page_game_room game_entrance
        """

    def use_coin(self, skip_first_screenshot=True):
        return False

    def play_game(self, skip_first_screenshot=True):
        pass

    def exit_game(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_game_room new_year_challenge_end
            out: page_game_room choose_game
        """


class Minigame(UI):
    def get_coin_amount(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_game_room main_page
            out: page_game_room main_page
        Returns:
            int: Coin amount
        """
        if not skip_first_screenshot:
            self.device.screenshot()
        amount = OCR_COIN.ocr(self.device.image)
        if amount >= 40:
            amount = 40
        return amount

    def go_to_main_page(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_game_room main_page/choose_game_page
            out: page_game_room main_page
        """
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

    def collect_coin(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_game_room main_page/choose_game_page
            out: page_game_room main_page
        """
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

    def run(self):
        """
        Pages:
            in: Any page
            out: page_game_room
        """
        # 临时处理：2026.02.18 将 self.ui_ensure(page_game_room) 拆成两步。
        # EN 服的学院页识别不同；若直接 ui_ensure(page_game_room)，ui_goto 必须改用 ui_page_appear。
        # 这会导致 page_main/page_main_white 点击静态切换按钮，所以这里先保持局部处理。
        self.ui_ensure(page_academy)
        # 学院页 -> 游戏室。
        for _ in self.loop():
            if self.ui_page_appear(page_game_room):
                break
            if self.ui_page_appear(page_academy, interval=5):
                self.device.click(ACADEMY_GOTO_GAME_ROOM)
                continue
            # You've reached your monthly limit of Game Tickets, and will not be able to earn any more.
            # Continue playing the minigame?
            if self.handle_popup_confirm("MINIGAME_ENTER"):
                continue

        # 游戏室和选择游戏页共用同一个页头，先回到游戏室主页。
        self.go_to_main_page()
        coin_collected = False
        play_count = 0

        # 选择具体小游戏。
        specific_game_name = "new_year_challenge"
        minigame_instance = None
        if specific_game_name == "new_year_challenge":
            from module.minigame.new_year_challenge import NewYearChallenge

            minigame_instance = NewYearChallenge(config=self.config, device=self.device)

        while 1:
            # 游玩次数上限。
            if play_count >= 10:
                break
            # OCR 获取代币数量。
            coin_count = self.get_coin_amount()
            logger.info(f"coin count : {coin_count}")
            # 收取代币。
            if coin_count <= 30 and not coin_collected:
                coin_collected = True
                if self.collect_coin():
                    continue
            # 没有代币时结束。
            if coin_count == 0:
                logger.info(f"coin count : {coin_count}, finished")
                break
            logger.info("coin count > 0, spend")
            # 执行具体小游戏逻辑。
            if minigame_instance is not None and minigame_instance.minigame_run():
                play_count += 1
                continue
            if minigame_instance is None:
                logger.error(f"unknown game name {specific_game_name}")
                break
            break

        self.config.task_delay(server_update=True)
