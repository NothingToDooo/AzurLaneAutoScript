from module.base.timer import Timer
from module.campaign.campaign_status import OCR_COIN
from module.combat.assets import GET_SHIP
from module.exception import ScriptError
from module.gacha import assets as gacha_assets
from module.gacha.ui import GachaUI
from module.handler.assets import POPUP_CONFIRM, STORY_SKIP
from module.logger import logger
from module.ocr.ocr import Digit
from module.retire.retirement import Retirement

RECORD_GACHA_OPTION = ("RewardRecord", "gacha")
RECORD_GACHA_SINCE = (0,)
OCR_BUILD_CUBE_COUNT = Digit(gacha_assets.BUILD_CUBE_COUNT, letter=(255, 247, 247), threshold=64)
OCR_BUILD_TICKET_COUNT = Digit(gacha_assets.BUILD_TICKET_COUNT, letter=(255, 247, 247), threshold=64)
OCR_BUILD_SUBMIT_COUNT = Digit(gacha_assets.BUILD_SUBMIT_COUNT, letter=(255, 247, 247), threshold=64)
OCR_BUILD_SUBMIT_WW_COUNT = Digit(gacha_assets.BUILD_SUBMIT_WW_COUNT, letter=(255, 247, 247), threshold=64)


class RewardGacha(GachaUI, Retirement):
    build_coin_count = 0
    build_cube_count = 0
    build_ticket_count = 0

    def gacha_prep(self, target, skip_first_screenshot=True):
        """
        Initiate preparation to submit build orders.

        Args:
            target (int): Number of build orders to submit
            skip_first_screenshot (bool):

        Returns:
            bool: True if prep complete otherwise False.

        Pages:
            in: page_build (any)
            out: submit pop up

        Except:
            May exit if unable to process prep
        """
        # target 为 0 时不需要准备。
        if not target:
            return False

        # 必须在可提交建造订单的页面。
        if not self.appear(gacha_assets.BUILD_SUBMIT_ORDERS) and not self.appear(gacha_assets.BUILD_SUBMIT_WW_ORDERS):
            return False

        # 用 appear 更新资产实际位置，供 ui_ensure_index 使用。
        confirm_timer = Timer(1, count=2).start()
        ocr_submit = None
        index_offset = (60, 20)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(gacha_assets.BUILD_SUBMIT_ORDERS, interval=3):
                ocr_submit = OCR_BUILD_SUBMIT_COUNT
                confirm_timer.reset()
                continue

            if self.appear_then_click(gacha_assets.BUILD_SUBMIT_WW_ORDERS, interval=3):
                ocr_submit = OCR_BUILD_SUBMIT_WW_COUNT
                confirm_timer.reset()
                continue
            # 即使 UR 兑换点已满，也继续建造。
            if self.handle_popup_confirm("GACHA_PREP"):
                confirm_timer.reset()
                continue

            # 结束。
            if (
                self.appear(gacha_assets.BUILD_PLUS, offset=index_offset)
                and self.appear(gacha_assets.BUILD_MINUS, offset=index_offset)
                and confirm_timer.reached()
            ):
                break

        # 检查是否提前退出，并套用正确的提交数量 OCR。
        if ocr_submit is None:
            raise ScriptError("Failed to identify ocr asset required, cannot continue prep work")
        area = ocr_submit.buttons[0]
        ocr_submit.buttons = [
            (gacha_assets.BUILD_MINUS.button[2] + 3, area[1], gacha_assets.BUILD_PLUS.button[0] - 3, area[3])
        ]
        self.ui_ensure_index(
            target,
            letter=ocr_submit,
            prev_button=gacha_assets.BUILD_MINUS,
            next_button=gacha_assets.BUILD_PLUS,
            skip_first_screenshot=True,
        )

        return True

    def gacha_calculate(self, target_count, gold_cost, cube_cost):
        """
        Calculate number able to actually submit.

        Args:
            target_count (int): Number of build orders like to submit
            gold_cost (int): Gold coin cost
            cube_cost (int): Cube cost

        Returns:
            int: Actual number able to submit based on current resources
        """
        while 1:
            # 按 target_count 计算资源消耗。
            gold_total = gold_cost * target_count
            cube_total = cube_cost * target_count

            # 已经降到 0，无法继续建造。
            if not target_count:
                logger.warning("Insufficient gold and/or cubes to gacha roll")
                break

            # 资源不足，减少 1 次后重新计算。
            if gold_total > self.build_coin_count or cube_total > self.build_cube_count:
                target_count -= 1
                continue

            break

        # 扣除资源，并返回当前 target_count。
        logger.info(f"Able to submit up to {target_count} build orders")
        self.build_coin_count -= gold_total
        self.build_cube_count -= cube_total
        return target_count

    def gacha_goto_pool(self, target_pool):
        """
        Transition to appropriate build pool page.

        Args:
            target_pool (str): Name of pool, default to
            'light' path if outside of acceptable range

        Returns:
            str: Current pool location based on availability

        Pages:
            in: page_build (gacha pool selection)
            out: page_build (gacha pool allowed)

        Except:
            May exit if 'wishing_well' but not
            complete configuration
        """
        # 先切到 light 池。
        self.gacha_bottom_navbar_ensure(right=3, is_build=True)

        # 按需切到 target_pool，并在不可用时回退。
        if target_pool == "wishing_well":
            if self._gacha_side_navbar.get_total(main=self) != 5:
                logger.warning("'wishing_well' is not available, default to 'light' pool")
                target_pool = "light"
            else:
                self.gacha_side_navbar_ensure(upper=2)
                if self.appear(gacha_assets.BUILD_WW_CHECK):
                    raise ScriptError(
                        "'wishing_well' must be configured manually by user, cannot continue gacha_goto_pool"
                    )
        elif target_pool == "event":
            gacha_bottom_navbar = self._gacha_bottom_navbar(is_build=True)
            if gacha_bottom_navbar.get_total(main=self) == 3:
                logger.warning("'event' is not available, default to 'light' pool")
                target_pool = "light"
            else:
                self.gacha_bottom_navbar_ensure(left=1, is_build=True)
        elif target_pool in ["heavy", "special"]:
            if target_pool == "heavy":
                self.gacha_bottom_navbar_ensure(right=2, is_build=True)
            else:
                self.gacha_bottom_navbar_ensure(right=1, is_build=True)

        return target_pool

    def gacha_flush_queue(self, skip_first_screenshot=True):
        """
        Flush build order queue to ensure empty before submission.

        Args:
            skip_first_screenshot (bool):

        Pages:
            in: page_build (any)
            out: page_build (gacha pool selection)

        Except:
            May exit if unable to flush queue entirely,
            dock likely full
        """
        # 进入建造订单页。
        self.gacha_side_navbar_ensure(bottom=3)

        # 处理各类过渡页面，最终回到建造页。
        confirm_timer = Timer(1, count=2).start()
        confirm_mode = True  # 快速完成、锁定舰船。
        # 清除按钮偏移，否则可能点到钻石加号或 HOME。
        STORY_SKIP.clear_offset()
        queue_clean = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(gacha_assets.BUILD_QUEUE_EMPTY, offset=(20, 20)) and queue_clean:
                self.gacha_side_navbar_ensure(upper=1)
                break
            queue_clean = False

            if self.appear_then_click(gacha_assets.BUILD_FINISH_ORDERS, interval=3):
                confirm_timer.reset()
                continue

            if self.handle_retirement():
                confirm_timer.reset()
                continue

            if self.handle_popup_confirm("FINISH_ORDERS"):
                if confirm_mode:
                    self.device.sleep((0.5, 0.8))
                    self.device.click(gacha_assets.BUILD_FINISH_ORDERS)  # 跳过动画的安全区域。
                    confirm_mode = False
                confirm_timer.reset()
                continue

            if self.appear(GET_SHIP, interval=1):
                self.device.click(STORY_SKIP)  # 多订单时快进。
                confirm_timer.reset()
                continue
            if self.handle_get_items_ship():
                continue

            if self.appear(gacha_assets.BUILD_FINISH_RESULTS, offset=(20, 150), interval=3):
                self.device.click(gacha_assets.BUILD_FINISH_ORDERS)  # 安全区域。
                confirm_timer.reset()
                continue

            # 结束：队列清空后点击会回到池子页面。
            if (
                self.appear(gacha_assets.BUILD_SUBMIT_ORDERS)
                or self.appear(gacha_assets.BUILD_SUBMIT_WW_ORDERS)
            ) and confirm_timer.reached():
                break

        # 许愿池不再显示金币，回到普通池。
        if self.appear(gacha_assets.BUILD_SUBMIT_WW_ORDERS):
            logger.info("In wishing pool, go back to normal pools")
            self.gacha_side_navbar_ensure(upper=1)

    def gacha_submit(self, skip_first_screenshot=True):
        """
        Pages:
            in: POPUP_CONFIRM
            out: BUILD_FINISH_ORDERS
        """
        logger.info("Submit gacha")
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(POPUP_CONFIRM, offset=(20, 80), interval=3):
                # 临时修改资产名，区分这次点击。
                POPUP_CONFIRM.name = POPUP_CONFIRM.name + "_" + "GACHA_ORDER"
                self.device.click(POPUP_CONFIRM)
                POPUP_CONFIRM.name = POPUP_CONFIRM.name[: -len("GACHA_ORDER") - 1]
                continue

            # 结束。
            if self.appear(gacha_assets.BUILD_FINISH_ORDERS):
                break

    def gacha_run(self):
        """
        Run gacha operations to submit build orders.

        Returns:
            bool: True if run successful otherwise False

        Pages:
            in: any
            out: page_build
        """
        # 进入建造。
        self.ui_goto_gacha()

        # 先清空现有建造队列，确保从主建造页开始。
        self.gacha_flush_queue()

        # OCR 当前金币和魔方数量。
        self.build_coin_count = OCR_COIN.ocr(self.device.image)
        self.build_cube_count = OCR_BUILD_CUBE_COUNT.ocr(self.device.image)

        # 切到目标建造池，同时确定建造成本。
        actual_pool = self.gacha_goto_pool(self.config.Gacha_Pool)

        # 根据实际建造池确定成本。
        gold_cost = 600
        cube_cost = 1
        if actual_pool in ["heavy", "special", "event", "wishing_well"]:
            gold_cost = 1500
            cube_cost = 2

        # OCR 建造券数量，决定使用建造券还是魔方/金币。
        # buy = [使用建造券的次数, 使用魔方的次数]
        buy = [self.config.Gacha_Amount, 0]
        if actual_pool == "event" and self.config.Gacha_UseTicket:
            if self.appear(gacha_assets.BUILD_TICKET_CHECK, offset=(30, 30)):
                self.build_ticket_count = OCR_BUILD_TICKET_COUNT.ocr(self.device.image)
            else:
                logger.info("Build ticket not detected, use cubes and coins")
        if self.config.Gacha_Amount > self.build_ticket_count:
            buy[0] = self.build_ticket_count
            # 按配置和资源计算还能建造几次。
            buy[1] = self.gacha_calculate(self.config.Gacha_Amount - self.build_ticket_count, gold_cost, cube_cost)

        # 逐组提交 buy_count。这里不能用 handle_popup_confirm，因为这个窗口没有 POPUP_CANCEL。
        result = False
        for buy_count in buy:
            if self.gacha_prep(buy_count):
                self.gacha_submit()

                # 如果配置为建造后使用快速完成。
                if self.config.Gacha_UseDrill:
                    self.gacha_flush_queue()
                # 任意一次提交成功就返回 True。
                result = True

        return result

    def run(self):
        """
        Handle gacha operations if configured to do so.

        Pages:
            in: Any page
            out: page_build
        """
        self.gacha_run()
        self.config.task_delay(server_update=True)
