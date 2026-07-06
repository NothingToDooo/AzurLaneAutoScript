from module.base.timer import Timer
from module.logger import logger
from module.minigame import assets as minigame_assets
from module.minigame.minigame import MINIGAME_SCROLL, MinigameRun
from module.ocr.ocr import Digit
from module.ui.page import page_game_room

OCR_GAME_NEW_YEAR_COIN_COST = Digit(
    minigame_assets.NEW_YEAR_CHALLENGE_COIN_COST_HOLDER,
    name="OCR_GAME_NEW_YEAR_COIN_COST",
    letter=(33, 28, 49),
    threshold=128,
)
OCR_NEW_YEAR_BATTLE_SCORE = Digit(
    minigame_assets.NEW_YEAR_CHALLENGE_SCORE_HOLDER,
    name="OCR_NEW_YEAR_BATTLE_SCORE",
    letter=(231, 215, 82),
    threshold=128,
)


class NewYearChallenge(MinigameRun):
    NEW_YEAR_BATTLE_RED = (255, 150, 123)
    NEW_YEAR_BATTLE_YELLOW = (247, 223, 115)
    NEW_YEAR_BATTLE_BLUE = (82, 134, 239)
    NEW_YEAR_BATTLE_TMP_BUTTON = [
        minigame_assets.NEW_YEAR_CHALLENGE_TMP_1,
        minigame_assets.NEW_YEAR_CHALLENGE_TMP_2,
        minigame_assets.NEW_YEAR_CHALLENGE_TMP_3,
        minigame_assets.NEW_YEAR_CHALLENGE_TMP_4,
        minigame_assets.NEW_YEAR_CHALLENGE_TMP_5,
    ]
    NEW_YEAR_BATTLE_COLOR_BUTTON_DICT = {
        NEW_YEAR_BATTLE_RED: minigame_assets.NEW_YEAR_CHALLENGE_RED_BUTTON,
        NEW_YEAR_BATTLE_YELLOW: minigame_assets.NEW_YEAR_CHALLENGE_YELLOW_BUTTON,
        NEW_YEAR_BATTLE_BLUE: minigame_assets.NEW_YEAR_CHALLENGE_BLUE_BUTTON,
    }

    def deal_specific_popup(self):
        # 第一次进入新年挑战战斗。
        if self.appear(minigame_assets.NEW_YEAR_CHALLENGE_FIRST_TIME, offset=(5, 5), interval=3):
            self.device.click(minigame_assets.NEW_YEAR_CHALLENGE_SAFE_AREA)
            return True
        return False

    def choose_game(self, skip_first_screenshot=True):
        self.interval_clear(page_game_room.check_button)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.deal_popup():
                continue
            # 已进入入口。
            if self.appear(minigame_assets.NEW_YEAR_CHALLENGE_START, offset=(5, 5)):
                break
            # 游戏室主页 -> 选择游戏。
            if self.appear_then_click(minigame_assets.GOTO_CHOOSE_GAME, offset=(5, 5), interval=3):
                continue
            # 选择新年挑战。
            if self.appear(minigame_assets.NEW_YEAR_CHALLENGE_ENTRANCE, offset=(5, 500), interval=3):
                self.device.click(minigame_assets.NEW_YEAR_CHALLENGE_ENTRANCE)
                self.interval_reset(page_game_room.check_button, interval=3)
                continue
            # 下滑寻找入口。
            if (
                self.ui_page_appear(page_game_room, interval=3)
                and MINIGAME_SCROLL.appear(main=self)
                and not MINIGAME_SCROLL.set(main=self, position=0.25, distance_check=False)
            ):
                MINIGAME_SCROLL.set_bottom(main=self)
                continue

    def use_coin(self, skip_first_screenshot=True):
        return self.use_coin_new_year_challenge(count=5)

    def play_game(self, skip_first_screenshot=True):
        """
        Pages:
            in: page_game_room new_year_challenge_prepare
            out: page_game_room new_year_challenge_end/new_year_challenge_prepare
        """
        score_ocr_interval = Timer(0.6, count=5).start()
        started = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.deal_popup():
                continue
            # 一轮选择。
            if self.appear(minigame_assets.NEW_YEAR_CHALLENGE_CHOOSING, offset=(5, 5), interval=3):
                # 点时钟会被误判为两个按钮之间点击过多，所以这里只执行颜色选择。
                # self.device.click(minigame_assets.NEW_YEAR_CHALLENGE_CHOOSING)
                self.new_year_challenge_turn(skip_first_screenshot=False)
                self.device.click_record_clear()
                continue
            # 等待选择。
            if score_ocr_interval.reached() and self.appear(
                minigame_assets.NEW_YEAR_CHALLENGE_STOP_PLAY, offset=(5, 5)
            ):
                # 分数足够时停止游玩。
                score = OCR_NEW_YEAR_BATTLE_SCORE.ocr(self.device.image)
                score_ocr_interval.reset()
                if score > 1000 and self.appear_then_click(
                    minigame_assets.NEW_YEAR_CHALLENGE_STOP_PLAY, offset=(5, 5), interval=3
                ):
                    continue
            # 游戏结束。
            if self.appear(minigame_assets.NEW_YEAR_CHALLENGE_END, offset=(5, 5), interval=3):
                break
            # 游戏规则介绍。
            if self.appear(minigame_assets.NEW_YEAR_CHALLENGE_START, offset=(5, 5), interval=3):
                if started:
                    self.interval_clear(minigame_assets.NEW_YEAR_CHALLENGE_START)
                    break
                else:
                    started = True
                    self.device.click(minigame_assets.NEW_YEAR_CHALLENGE_START)
                    continue

    def exit_game(self, skip_first_screenshot=True):
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.deal_popup():
                continue
            if self.appear(minigame_assets.BACK, offset=(5, 5)):
                if self.appear(minigame_assets.GOTO_CHOOSE_GAME, offset=(5, 5)):
                    break
                else:
                    self.appear_then_click(minigame_assets.BACK, offset=(5, 5), interval=3)
                    continue
            if self.appear_then_click(minigame_assets.NEW_YEAR_CHALLENGE_END, offset=(5, 5), interval=3):
                continue
            if self.appear_then_click(minigame_assets.NEW_YEAR_CHALLENGE_EXIT, offset=(5, 5), interval=3):
                continue

    def use_coin_new_year_challenge(self, skip_first_screenshot=True, count=1):
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()
            if self.deal_popup():
                continue
            if self.appear(minigame_assets.NEW_YEAR_CHALLENGE_ADD_COIN, offset=(5, 5)):
                # 添加代币。
                if count > 1:
                    for _i in range(count - 1):
                        self.device.click(minigame_assets.NEW_YEAR_CHALLENGE_ADD_COIN)
                    self.device.screenshot()
                # 测试时可不消耗代币。
                if count < 1:
                    self.appear_then_click(minigame_assets.NEW_YEAR_CHALLENGE_DEC_COIN, offset=(5, 5), interval=3)
                    self.device.screenshot()
                coin_cost_after_add = OCR_GAME_NEW_YEAR_COIN_COST.ocr(self.device.image)
                logger.info(f"coin cost after add : {coin_cost_after_add}")
                if count >= 1 and coin_cost_after_add <= 0:
                    # 月度奖励已领取完或剩余代币为 0 时无法添加代币。
                    return False
                return True

    def new_year_challenge_turn(self, skip_first_screenshot=True):
        if not skip_first_screenshot:
            self.device.screenshot()
        to_clicks = []
        # 判断需要点击的颜色按钮。
        for to_judge in self.NEW_YEAR_BATTLE_TMP_BUTTON:
            for color, button in self.NEW_YEAR_BATTLE_COLOR_BUTTON_DICT.items():
                if self.image_color_count(to_judge, color, threshold=221, count=10):
                    to_clicks.append(button)
                    break
        logger.info(f"to clicks: {to_clicks}")
        to_clicks.reverse()
        # 按顺序点击。
        click_interval = Timer(0.2, count=5).start()
        while 1:
            if to_clicks and click_interval.reached():
                self.device.click(to_clicks.pop())
                click_interval.reset()
            if not to_clicks:
                break
