from dataclasses import dataclass

from module.base.button import Button, ButtonGrid
from module.base.timer import Timer
from module.logger import logger
from module.meowfficer import assets as meow_assets
from module.meowfficer.base import MeowfficerBase
from module.ui.switch import Switch

MEOWFFICER_TALENT_GRID_1 = ButtonGrid(
    origin=(875, 559), delta=(105, 0), button_shape=(16, 16), grid_shape=(3, 1), name="MEOWFFICER_TALENT_GRID_1"
)
MEOWFFICER_TALENT_GRID_2 = MEOWFFICER_TALENT_GRID_1.move(vector=(-40, -20), name="MEOWFFICER_TALENT_GRID_2")
MEOWFFICER_SHIFT_DETECT = Button(
    area=(1260, 669, 1280, 720), color=(117, 106, 84), button=(1260, 669, 1280, 720), name="MEOWFFICER_SHIFT_DETECT"
)

SWITCH_LOCK = Switch(name="Meowfficer_Lock", offset=(40, 40))
SWITCH_LOCK.add_state(
    "lock", check_button=meow_assets.MEOWFFICER_APPLY_UNLOCK, click_button=meow_assets.MEOWFFICER_APPLY_LOCK
)
SWITCH_LOCK.add_state(
    "unlock", check_button=meow_assets.MEOWFFICER_APPLY_LOCK, click_button=meow_assets.MEOWFFICER_APPLY_UNLOCK
)


@dataclass(slots=True)
class _MeowGetState:
    confirm_timer: Timer
    skip_first_screenshot: bool
    count: int = 0


class MeowfficerCollect(MeowfficerBase):
    def _meow_detect_shift(self, *, skip_first_screenshot: bool = True) -> bool:
        """等待领取完成页稳定，并返回页面是否随机左移。"""
        flag = False
        confirm_timer = Timer(3, count=6).start()
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.image_color_count(
                MEOWFFICER_SHIFT_DETECT, color=MEOWFFICER_SHIFT_DETECT.color, threshold=221, count=650
            ):
                if not flag:
                    confirm_timer.reset()
                    flag = True
                if confirm_timer.reached():
                    break
                continue

            if self.appear(meow_assets.MEOWFFICER_GET_CHECK, offset=(40, 40)):
                if flag:
                    confirm_timer.reset()
                    flag = False
                if confirm_timer.reached():
                    break
        return flag

    def _meow_check_popup_exit(self) -> bool:
        """返回退出锁定弹窗或天赋详情后是否位于可继续页面。"""
        return self.match_template_color(meow_assets.MEOWFFICER_GET_CHECK, offset=(40, 40)) or self.appear(
            meow_assets.MEOWFFICER_TRAIN_START, offset=(20, 20)
        )

    def _meow_is_special_talented(self) -> bool:
        """检查指挥喵是否至少有一个特殊天赋。"""
        logger.info("Wait complete load and examine base talents")

        special_talent = False
        grid = MEOWFFICER_TALENT_GRID_2 if self._meow_detect_shift() else MEOWFFICER_TALENT_GRID_1

        for btn in grid.buttons:
            # 空槽有大量白色像素，普通天赋的罗马数字只有少量白色像素。
            if self.image_color_count(btn, color=(255, 255, 247), threshold=221, count=200):
                continue

            if self.image_color_count(btn, color=(255, 255, 255), threshold=221, count=25):
                continue

            special_talent = True

        log_insert = "Found" if special_talent else "No"
        logger.info(f"{log_insert} special talent abilities in meowfficer")
        return special_talent

    def _meow_skip_lock(self) -> None:
        """仅用于金色指挥喵，缓慢跳过锁定流程以避免误操作。"""

        def additional() -> bool:
            if self.appear(meow_assets.MEOWFFICER_TRAIN_EVALUATE, offset=(20, 20), interval=3):
                self.device.click(meow_assets.MEOWFFICER_TRAIN_EVALUATE)
                return True
            return False

        self.ui_click(
            meow_assets.MEOWFFICER_TRAIN_CLICK_SAFE_AREA,
            appear_button=meow_assets.MEOWFFICER_GET_CHECK,
            check_button=meow_assets.MEOWFFICER_CONFIRM,
            additional=additional,
            offset=(40, 40),
            retry_wait=3,
            skip_first_screenshot=True,
        )

        self.ui_click(
            meow_assets.MEOWFFICER_CANCEL,
            check_button=self._meow_check_popup_exit,
            additional=additional,
            offset=(40, 20),
            retry_wait=3,
            skip_first_screenshot=True,
        )
        self.device.click_record.pop()
        self.device.click_record.pop()

    def _meow_apply_lock(self, *, lock: bool = True) -> None:
        """设置新指挥喵锁定状态，避免被用作强化材料。"""
        SWITCH_LOCK.set("lock" if lock else "unlock", main=self)

        self.ensure_no_info_bar(timeout=1)

    def _meow_skip_popup_after_locking(self, *, skip_first_screenshot: bool = True) -> None:
        """兼容 2023-11-16 后已锁定金色指挥喵仍出现确认弹窗的流程。"""
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 下一个指挥喵的 MEOWFFICER_APPLY_LOCK 比 MEOWFFICER_GET_CHECK 加载更快，
            # 退出前需要确保已有完整截图。
            if self.appear(meow_assets.MEOWFFICER_GET_CHECK, offset=(40, 40)) and self.appear(
                meow_assets.MEOWFFICER_APPLY_LOCK, offset=(40, 40)
            ):
                break
            # 意外退出领取队列。
            if self.appear(meow_assets.MEOWFFICER_TRAIN_START, offset=(20, 20)):
                logger.info("_meow_skip_popup_after_locking exits at MEOWFFICER_TRAIN_START")
                break

            if self.appear(meow_assets.MEOWFFICER_APPLY_UNLOCK, offset=(40, 40), interval=3):
                self.device.click(meow_assets.MEOWFFICER_TRAIN_CLICK_SAFE_AREA)
                continue
            if self.appear(meow_assets.MEOWFFICER_CONFIRM, offset=(40, 20), interval=3) or self.appear(
                meow_assets.MEOWFFICER_CANCEL, offset=(40, 20), interval=3
            ):
                self.device.click(meow_assets.MEOWFFICER_CONFIRM)
                continue
            if self.appear(meow_assets.MEOWFFICER_TRAIN_EVALUATE, offset=(20, 20), interval=3):
                self.device.click(meow_assets.MEOWFFICER_TRAIN_EVALUATE)
                continue

        self.device.click_record.pop()
        self.device.click_record.pop()
        self.interval_reset(
            (
                meow_assets.MEOWFFICER_GET_CHECK,
                meow_assets.MEOWFFICER_APPLY_LOCK,
                meow_assets.MEOWFFICER_CONFIRM,
                meow_assets.MEOWFFICER_CANCEL,
            )
        )

    def meow_get(self, *, skip_first_screenshot: bool = True) -> None:
        """从领取页等待数量不定的动画并逐只领取；仅金色会确认，最终回到训练页。"""
        state = _MeowGetState(confirm_timer=Timer(1.5, count=3).start(), skip_first_screenshot=skip_first_screenshot)
        while 1:
            if state.skip_first_screenshot:
                state.skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._meow_get_finished(state):
                break
            if self._meow_get_handle_popup(state):
                continue
            if self._meow_get_handle_acquired(state):
                continue
            if self._meow_get_handle_evaluate():
                continue

    def _meow_get_finished(self, state: _MeowGetState) -> bool:
        if self.appear(meow_assets.MEOWFFICER_TRAIN_START, offset=(20, 20)):
            return state.confirm_timer.reached()

        state.confirm_timer.reset()
        return False

    def _meow_get_handle_popup(self, state: _MeowGetState) -> bool:
        if not self.handle_meow_popup_dismiss():
            return False

        state.confirm_timer.reset()
        return True

    def _meow_get_handle_acquired(self, state: _MeowGetState) -> bool:
        if not self.appear(meow_assets.MEOWFFICER_GET_CHECK, offset=(40, 40), interval=3):
            return False

        if self._meow_get_skip_popup_after_locking(state):
            return True

        state.count += 1
        logger.attr("Meow_get", state.count)
        special_talent = self._meow_is_special_talented()
        if self._meow_get_handle_gold(state, special_talent=special_talent):
            return True
        self._meow_get_handle_purple(special_talent=special_talent)
        self._meow_get_continue_next(state)
        return True

    def _meow_get_skip_popup_after_locking(self, state: _MeowGetState) -> bool:
        if not self.appear(meow_assets.MEOWFFICER_APPLY_UNLOCK, offset=(40, 40)):
            return False

        self._meow_skip_popup_after_locking(skip_first_screenshot=True)
        state.confirm_timer.reset()
        # 意外退出领取队列。
        return self.appear(meow_assets.MEOWFFICER_TRAIN_START, offset=(20, 20))

    def _meow_get_handle_gold(self, state: _MeowGetState, *, special_talent: bool) -> bool:
        if not self.appear(meow_assets.MEOWFFICER_GOLD_CHECK, offset=(40, 40)):
            return False
        if self.config.MeowfficerTrain_RetainTalentedGold and special_talent:
            self._meow_apply_lock()
            return False

        self._meow_skip_lock()
        state.skip_first_screenshot = True
        state.confirm_timer.reset()
        return True

    def _meow_get_handle_purple(self, *, special_talent: bool) -> None:
        if not self.appear(meow_assets.MEOWFFICER_PURPLE_CHECK, offset=(40, 40)):
            return
        if self.config.MeowfficerTrain_RetainTalentedPurple and special_talent:
            self._meow_apply_lock()

    def _meow_get_continue_next(self, state: _MeowGetState) -> None:
        # 多次领取时容易触发异常，通过弹出 click_record 缓解。
        self.device.click(meow_assets.MEOWFFICER_TRAIN_CLICK_SAFE_AREA)
        self.device.click_record.pop()
        state.confirm_timer.reset()
        self.interval_reset(meow_assets.MEOWFFICER_GET_CHECK)

    def _meow_get_handle_evaluate(self) -> bool:
        # 点击 MEOWFFICER_TRAIN_FINISH_ALL 后会进入评价页面。
        if not self.appear(meow_assets.MEOWFFICER_TRAIN_EVALUATE, offset=(20, 20), interval=3):
            return False

        self.device.click(meow_assets.MEOWFFICER_TRAIN_EVALUATE)
        return True

    def meow_collect(self, *, collect_all: bool = True) -> bool:
        """在训练页领取一只或全部并返回是否领取；完成槽会自动移到队首，只检查左上槽。"""
        logger.hr("Meowfficer collect", level=2)

        if self.appear(meow_assets.MEOWFFICER_TRAIN_COMPLETE, offset=(20, 20)):
            # 周日领取全部，否则只领取一个。
            if collect_all:
                logger.info("Collect all trained meowfficers")
                button = meow_assets.MEOWFFICER_TRAIN_FINISH_ALL
            else:
                logger.info("Collect single trained meowfficer")
                button = meow_assets.MEOWFFICER_TRAIN_COMPLETE
            self.ui_click(
                button,
                check_button=meow_assets.MEOWFFICER_GET_CHECK,
                additional=self.handle_meow_popup_dismiss,
                offset=(40, 40),
                skip_first_screenshot=True,
            )

            self.meow_get()
            return True
        return False
