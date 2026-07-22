import copy
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Literal

import numpy as np
from scipy import signal

from module.base.timer import Timer
from module.base.utils import crop, image_size, rgb2gray
from module.combat import assets as combat_assets
from module.commission import assets as commission_assets
from module.commission.preset import DICT_FILTER_PRESET, SHORTEST_FILTER
from module.commission.project import COMMISSION_FILTER, Commission
from module.config.config_generated import GeneratedConfig
from module.config.utils import get_server_last_update, get_server_next_update
from module.dorm.dorm import RewardDorm
from module.exception import GameStuckError, HumanTakeoverRequiredError, OilMaxed
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.retire.assets import DOCK_CHECK
from module.ui.assets import BACK_ARROW, REWARD_GOTO_COMMISSION
from module.ui.page import page_commission, page_reward
from module.ui.scroll import Scroll
from module.ui.switch import Switch
from module.ui.ui import UI
from module.ui_white.assets import REWARD_1_WHITE, REWARD_GOTO_COMMISSION_WHITE

if TYPE_CHECKING:
    from module.base.button import Button
    from module.base.type_alias import Area, ImageArray

type CommissionChoice = Commission | str
type CommissionMode = Literal["daily", "urgent"]

COMMISSION_SWITCH = Switch("Commission_switch", is_selector=True)
COMMISSION_SWITCH.add_state("daily", commission_assets.COMMISSION_DAILY)
COMMISSION_SWITCH.add_state("urgent", commission_assets.COMMISSION_URGENT)
COMMISSION_SCROLL = Scroll(commission_assets.COMMISSION_SCROLL_AREA, color=(247, 211, 66), name="COMMISSION_SCROLL")
COMMISSION_ADVICE_FLASHING_BUG_MESSAGE = "Triggered commission list flashing bug"


def lines_detect(image: ImageArray) -> list[int]:
    """在 (597, 0, 619, 720) 白线区域返回各委托底边的 Y 坐标。"""
    color_height = np.mean(rgb2gray(crop(image, (597, 0, 619, 720), copy=False)), axis=1)
    parameters = {"height": 200, "distance": 100}
    peaks, _ = signal.find_peaks(color_height, **parameters)
    # 67 是委托列表头部高度。
    # 117 是单个委托卡片高度。
    return [int(y) for y in peaks if y > 67 + 117]


class RewardCommission(UI, InfoHandler):
    daily: SelectedGrids[Commission]
    urgent: SelectedGrids[Commission]
    daily_choose: SelectedGrids[Commission]
    urgent_choose: SelectedGrids[Commission]
    comm_choose: SelectedGrids[Commission]
    max_commission = 4

    def _commission_detect(self, image: ImageArray) -> SelectedGrids[Commission]:
        logger.hr("Commission detect")
        commission: list[Commission] = []
        for y in lines_detect(image):
            comm = Commission(image, y=y, config=self.config)
            logger.attr("Commission", comm)
            repeat = len([c for c in commission if c == comm])
            comm.repeat_count += repeat
            commission.append(comm)

        return SelectedGrids(commission)

    def commission_detect(
        self,
        trial: int = 1,
        area: Area | None = None,
        *,
        skip_first_screenshot: bool = True,
    ) -> SelectedGrids[Commission]:
        """检测委托；仅一个条目无效时按 trial 重试，通常是 info_bar 残影所致。"""
        commissions = SelectedGrids([])
        for _ in range(trial):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            image = self.device.image
            if area is not None:
                image = crop(image, area, copy=False)
            commissions = self._commission_detect(image)

            if commissions.count >= 2 and commissions.select(valid=False).count == 1:
                logger.warning("Found 1 invalid commission, retry commission detect")
                continue
            return commissions

        logger.info("trials of commission detect exhausted, stop")
        return commissions

    def _commission_choose(
        self,
        daily: SelectedGrids[Commission],
        urgent: SelectedGrids[Commission],
    ) -> tuple[SelectedGrids[Commission], SelectedGrids[Commission]]:
        """返回本轮选择的日常委托和紧急委托。"""
        self.comm_choose = SelectedGrids([])
        total = self._commission_merge_candidates(daily, urgent)
        running_count = self._commission_running_count(total)
        logger.attr("Running", f"{running_count}/{self.max_commission}")

        preset, string = self._commission_filter_string()
        run = self._commission_apply_filter(total, preset=preset, string=string)
        run = self._commission_fill_shortest(run, daily=daily, running_count=running_count)
        self.comm_choose = SelectedGrids(choice for choice in run if not isinstance(choice, str))

        if running_count >= self.max_commission:
            return SelectedGrids([]), SelectedGrids([])

        return self._commission_split_choices(run, daily=daily, urgent=urgent, running_count=running_count)

    def _commission_merge_candidates(
        self,
        daily: SelectedGrids[Commission],
        urgent: SelectedGrids[Commission],
    ) -> SelectedGrids[Commission]:
        total = daily.add_by_eq(urgent)
        # 后缀更大的委托总是在后缀更小的委托下方，反转后优先选择高后缀委托。
        total = total[::-1]
        self.max_commission = 5 if any(comm.genre == "daily_event" for comm in total) else 4
        return total

    @staticmethod
    def _commission_running_count(total: SelectedGrids[Commission]) -> int:
        return sum(1 for comm in total if comm.status == "running")

    def _commission_filter_string(self) -> tuple[str, str]:
        preset = self.config.Commission_PresetFilter
        if preset == "custom":
            return preset, self.config.Commission_CustomFilter

        preset = self._commission_resolve_filter_preset(preset)
        return preset, DICT_FILTER_PRESET[preset]

    @staticmethod
    def _commission_resolve_filter_preset(preset: str) -> str:
        if f"{preset}_night" in DICT_FILTER_PRESET:
            start_time = get_server_last_update("02:00")
            end_time = get_server_last_update("21:00")
            if start_time < end_time:
                preset = f"{preset}_night"
        if preset in DICT_FILTER_PRESET:
            return preset

        logger.warning(f"Preset not found: {preset}, use default preset")
        return GeneratedConfig.Commission_PresetFilter

    def _commission_apply_filter(
        self,
        total: SelectedGrids[Commission],
        *,
        preset: str,
        string: str,
    ) -> SelectedGrids[CommissionChoice]:
        logger.attr("Commission Filter", preset)
        COMMISSION_FILTER.load(string)
        run = COMMISSION_FILTER.apply(total.grids, func=self._commission_check)
        logger.attr("Filter_sort", " > ".join([str(c) for c in run]))
        return SelectedGrids(run)

    def _commission_fill_shortest(
        self,
        run: SelectedGrids[CommissionChoice],
        *,
        daily: SelectedGrids[Commission],
        running_count: int,
    ) -> SelectedGrids[CommissionChoice]:
        no_shortest = run.delete(SelectedGrids[CommissionChoice](["shortest"]))
        if no_shortest.count + running_count >= self.max_commission:
            return run
        if not daily.count:
            logger.info("Not enough commissions to run")
            return run

        logger.info("Not enough commissions to run, add shortest daily commissions")
        COMMISSION_FILTER.load(SHORTEST_FILTER)
        shortest = COMMISSION_FILTER.apply(daily[::-1], func=self._commission_check)
        # 反转日常委托列表，优先选择更好的委托。
        run = no_shortest.add_by_eq(SelectedGrids(shortest))
        logger.attr("Filter_sort", " > ".join([str(c) for c in run]))
        return run

    def _commission_split_choices(
        self,
        run: SelectedGrids[CommissionChoice],
        *,
        daily: SelectedGrids[Commission],
        urgent: SelectedGrids[Commission],
        running_count: int,
    ) -> tuple[SelectedGrids[Commission], SelectedGrids[Commission]]:
        run = run[: self.max_commission - running_count]
        commissions = SelectedGrids(choice for choice in run if not isinstance(choice, str))
        daily_choose = commissions.intersect_by_eq(daily)
        urgent_choose = commissions.intersect_by_eq(urgent)
        self._log_commission_choices("daily", daily_choose)
        self._log_commission_choices("urgent", urgent_choose)
        return daily_choose, urgent_choose

    @staticmethod
    def _log_commission_choices(name: CommissionMode, choices: SelectedGrids[Commission]) -> None:
        if not choices:
            return

        logger.info(f"Choose {name} commission")
        for comm in choices:
            logger.info(comm)

    def _commission_check(self, commission: Commission) -> bool:
        return (
            commission.valid
            and commission.status == "pending"
            and (self.config.Commission_DoMajorCommission or commission.category_str != "major")
        )

    def _commission_ensure_mode(self, mode: CommissionMode) -> bool:
        if COMMISSION_SWITCH.set(mode, main=self):
            # 日常委托超过 4 个时通常会有 5 个，紧急委托则是 1 到 4 个。
            # 委托列表的滚动动画会导致最上方条目漏检。
            if (
                not COMMISSION_SCROLL.appear(main=self)
                or COMMISSION_SCROLL.cal_position(main=self) < 0.05
                or COMMISSION_SCROLL.length / COMMISSION_SCROLL.total > 0.98
            ):
                pre_peaks = lines_detect(self.device.image)
                if not len(pre_peaks):
                    return True
                self.device.screenshot()
                while 1:
                    peaks = lines_detect(self.device.image)
                    if (not len(peaks) or peaks[0] > 67 + 117) and (
                        not len(pre_peaks) or not len(peaks) or abs(peaks[0] - pre_peaks[0]) < 3
                    ):
                        break
                    pre_peaks = peaks
                    self.device.screenshot()

            return True
        return False

    def _commission_mode_reset(self) -> bool:
        logger.hr("Commission mode reset")
        if self.appear(commission_assets.COMMISSION_DAILY):
            current, another = "daily", "urgent"
        elif self.appear(commission_assets.COMMISSION_URGENT):
            current, another = "urgent", "daily"
        else:
            logger.warning("Unknown Commission mode")
            return False

        self._commission_ensure_mode(another)
        self._commission_ensure_mode(current)

        return True

    def _commission_swipe(self) -> bool:
        if COMMISSION_SCROLL.appear(main=self):
            if COMMISSION_SCROLL.at_bottom(main=self):
                return False
            COMMISSION_SCROLL.next_page(main=self)
            return True
        return False

    def _commission_swipe_to_top(self) -> bool:
        if not COMMISSION_SCROLL.appear(main=self):
            return False
        COMMISSION_SCROLL.set_top(main=self, skip_first_screenshot=True)
        return True

    def _commission_scan_list(self) -> SelectedGrids[Commission]:
        self.device.click_record_clear()
        commission = SelectedGrids([])
        for _ in range(15):
            new = self.commission_detect(trial=2)
            commission = commission.add_by_eq(new)

            if not self._commission_swipe():
                break

        self.device.click_record_clear()
        return commission

    def _commission_scan_all(self) -> tuple[SelectedGrids[Commission], SelectedGrids[Commission]]:
        """在委托页扫描日常与紧急列表，并计算本轮选择。"""
        logger.hr("Commission scan", level=1)
        # 紧急委托列表是懒加载的，先切过去强制刷新。
        self._commission_ensure_mode("urgent")

        logger.hr("Scan daily", level=2)
        self._commission_ensure_mode("daily")
        self._commission_swipe_to_top()
        daily = self._commission_scan_list()

        urgent = SelectedGrids([])
        for _ in range(2):
            logger.hr("Scan urgent", level=2)
            self._commission_ensure_mode("urgent")
            self._commission_swipe_to_top()
            urgent = self._commission_scan_list()
            # 将额外委托转换为夜间委托。
            urgent.call("convert_to_night")

            # 不在 21:00~03:00，却扫到了夜间委托，多半是过期数据，刷新一次即可。
            if datetime.now() - get_server_next_update("21:00") > timedelta(hours=6):
                night = urgent.select(category_str="night")
                if night:
                    logger.warning("Not in 21:00~03:00, but scanned night commissions")
                    for comm in night:
                        logger.attr("Commission", comm)
                    logger.info("Re-scan urgent commission list")
                    # 这里虽然是硬等待，但只在罕见刷新异常时触发，可以接受。
                    self.device.sleep(2)
                    self._commission_ensure_mode("daily")
                    continue

            break

        logger.hr("Showing commission", level=2)
        logger.info("Daily commission")
        for comm in daily.sort("status", "genre"):
            logger.attr("Commission", comm)
        if urgent.count:
            logger.info("Urgent commission")
            for comm in urgent.sort("status", "genre"):
                logger.attr("Commission", comm)

        self.daily = daily
        self.urgent = urgent
        self.daily_choose, self.urgent_choose = self._commission_choose(self.daily, self.urgent)
        return daily, urgent

    def _commission_start_click(
        self,
        comm: Commission,
        *,
        is_urgent: bool = False,
        skip_first_screenshot: bool = True,
    ) -> bool:
        """在委托页启动项目，成功后详情展开并出现 info_bar。"""
        logger.hr("Commission start")
        self.interval_clear(commission_assets.COMMISSION_ADVICE)
        self.interval_clear(commission_assets.COMMISSION_START)
        comm_timer = Timer(7)
        count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._commission_start_finished():
                break

            self._raise_if_commission_advice_flashing(count)

            if self._handle_commission_start_button(comm_timer):
                continue
            if self._handle_commission_dock_back(comm_timer):
                continue

            advice_result = self._handle_commission_advice(comm, is_urgent=is_urgent, comm_timer=comm_timer)
            if advice_result is False:
                return False
            if advice_result is True:
                count += 1
                continue

            self._handle_commission_entry(comm, comm_timer)

        return True

    def _commission_start_finished(self) -> bool:
        return bool(self.info_bar_count())

    @staticmethod
    def _raise_if_commission_advice_flashing(count: int) -> None:
        if count < 3:
            return
        # 重启游戏以处理委托推荐 bug：点击“推荐”后舰船短暂出现又消失，同时委托图标闪烁。
        logger.warning(COMMISSION_ADVICE_FLASHING_BUG_MESSAGE)
        raise GameStuckError(COMMISSION_ADVICE_FLASHING_BUG_MESSAGE)

    def _handle_commission_start_button(self, comm_timer: Timer) -> bool:
        if self.match_template_color(commission_assets.COMMISSION_START, offset=(5, 20), interval=7):
            self.device.click(commission_assets.COMMISSION_START)
            self.interval_reset(commission_assets.COMMISSION_ADVICE)
            comm_timer.reset()
            return True
        if self.handle_popup_confirm("COMMISSION_START"):
            self.interval_reset(commission_assets.COMMISSION_ADVICE)
            comm_timer.reset()
            return True
        return False

    def _handle_commission_dock_back(self, comm_timer: Timer) -> bool:
        if not self.appear(DOCK_CHECK, offset=(20, 20), interval=3):
            return False

        logger.info(f"equip_enter {DOCK_CHECK} -> {BACK_ARROW}")
        self.device.click(BACK_ARROW)
        comm_timer.reset()
        return True

    def _handle_commission_advice(
        self,
        comm: Commission,
        *,
        is_urgent: bool,
        comm_timer: Timer,
    ) -> bool | None:
        if not self.appear(commission_assets.COMMISSION_ADVICE, offset=(5, 20), interval=7):
            return None

        if not self._commission_advice_matches(comm, is_urgent=is_urgent):
            return False

        self.device.click(commission_assets.COMMISSION_ADVICE)
        self.interval_reset(commission_assets.COMMISSION_ADVICE)
        self.interval_clear(commission_assets.COMMISSION_START)
        comm_timer.reset()
        return True

    def _commission_advice_matches(self, comm: Commission, *, is_urgent: bool) -> bool:
        area = (0, 0, image_size(self.device.image)[0], commission_assets.COMMISSION_ADVICE.button[1])
        current = self.commission_detect(area=area)
        if is_urgent:
            current.call("convert_to_night")
        if current.count < 1:
            logger.warning("No selected commission detected, assuming correct")
            return True

        current = current[0]
        if current == comm:
            logger.info("Selected to the correct commission")
            return True

        logger.warning("Selected to the wrong commission")
        return False

    def _handle_commission_entry(self, comm: Commission, comm_timer: Timer) -> bool:
        if not comm_timer.reached():
            return False

        self.device.click(comm.button)
        self.device.sleep(0.3)
        comm_timer.reset()
        return True

    def _commission_find_and_start(self, comm: Commission, *, is_urgent: bool = False) -> bool:
        self.device.click_record_clear()
        comm = copy.deepcopy(comm)
        comm.repeat_count = 1
        for _ in range(3):
            logger.hr("Commission find and start", level=2)
            logger.info(f"Finding commission {comm}")

            failed = True

            for _ in range(15):
                new = self.commission_detect(trial=2)
                if is_urgent:
                    new.call("convert_to_night")

                # 更新委托位置；不同扫描里的信息相同，但坐标可能不同。
                current = None
                for new_comm in new:
                    if new_comm == comm:
                        current = new_comm
                if current is not None:
                    if self._commission_start_click(current, is_urgent=is_urgent):
                        self.device.click_record_clear()
                        return True
                    self._commission_mode_reset()
                    self._commission_swipe_to_top()
                    failed = False
                    break

                if not self._commission_swipe():
                    break

            if failed:
                logger.warning(f"Failed to select commission: {comm}")
                self._commission_mode_reset()
                self._commission_swipe_to_top()
                self.device.click_record_clear()
                continue
            logger.warning(f"Commission not found: {comm}")
            self.device.click_record_clear()
            return False

        logger.warning("Failed to select commission after 3 trial")
        self.device.click_record_clear()
        return False

    def commission_start(self) -> None:
        """在委托页扫描并启动全部选中委托。"""
        self._commission_scan_all()

        logger.hr("Commission run", level=1)
        if self.daily_choose:
            for comm in self.daily_choose:
                self._commission_ensure_mode("daily")
                self._commission_swipe_to_top()
                self.handle_info_bar()
                if self._commission_find_and_start(comm, is_urgent=False):
                    comm.convert_to_running()
                self._commission_mode_reset()
        if self.urgent_choose:
            for comm in self.urgent_choose:
                self._commission_ensure_mode("urgent")
                self._commission_swipe_to_top()
                self.handle_info_bar()
                if self._commission_find_and_start(comm, is_urgent=True):
                    comm.convert_to_running()
                self._commission_mode_reset()
        if not self.daily_choose and not self.urgent_choose:
            logger.info("No commission chose")

    def _commission_receive(self, *, skip_first_screenshot: bool = True) -> bool:
        """从奖励页领取委托奖励并进入委托页，返回是否领到奖励。"""
        logger.hr("Reward receive")

        reward = False
        click_timer = Timer(1)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self._commission_reward_finished():
                break

            if self._handle_commission_reward_save(click_timer):
                reward = True
                continue

            reward_click = self._handle_commission_reward_buttons(click_timer)
            if reward_click is not None:
                reward = reward or reward_click
                continue

            if self.ui_main_appear_then_click(page_reward, interval=3):
                self.interval_reset(combat_assets.GET_SHIP)
                # 不需要重置 click_timer，直接立即点击 REWARD_1。
                continue

            self._raise_if_commission_oil_maxed()

            if self._handle_commission_get_ship(click_timer):
                reward = True
                continue

            if self._handle_commission_additional(click_timer):
                click_timer.reset()
                continue

        return reward

    def _commission_reward_finished(self) -> bool:
        # 留在委托页时，委托奖励可能弹出过慢，导致 UI 切换卡住。
        return self.ui_page_appear(page_commission, offset=(20, 20))

    def _handle_commission_reward_save(self, click_timer: Timer) -> bool:
        for button in (
            commission_assets.EXP_INFO_S_REWARD,
            combat_assets.GET_ITEMS_1,
            combat_assets.GET_ITEMS_2,
            combat_assets.GET_ITEMS_3,
        ):
            if self._click_commission_reward_save(button, click_timer):
                return True
        return False

    def _click_commission_reward_save(self, button: Button, click_timer: Timer) -> bool:
        if not self.appear(button, interval=1):
            return False

        commission_assets.REWARD_SAVE_CLICK.name = button.name
        self.device.click(commission_assets.REWARD_SAVE_CLICK)
        click_timer.reset()
        return True

    def _handle_commission_reward_buttons(self, click_timer: Timer) -> bool | None:
        if not click_timer.reached():
            return None

        for button, is_reward in (
            (commission_assets.REWARD_1, True),
            (REWARD_1_WHITE, True),
        ):
            if self.appear_then_click(button, offset=(20, 20), interval=1):
                self.interval_reset(combat_assets.GET_SHIP)
                click_timer.reset()
                return is_reward
        for button in (REWARD_GOTO_COMMISSION, REWARD_GOTO_COMMISSION_WHITE):
            if self.appear_then_click(button, offset=(20, 20)):
                self.interval_reset(combat_assets.GET_SHIP)
                click_timer.reset()
                return False
        return None

    def _raise_if_commission_oil_maxed(self) -> None:
        if self.config.SERVER == "cn" and self.appear(commission_assets.OIL_MAXED, offset=(20, 20), interval=3):
            raise OilMaxed

    def _handle_commission_get_ship(self, click_timer: Timer) -> bool:
        if not click_timer.reached():
            return False
        # 最后检查 GET_SHIP，以处理主界面随机白底。
        return self._click_commission_reward_save(combat_assets.GET_SHIP, click_timer)

    def _handle_commission_additional(self, click_timer: Timer) -> bool:
        return click_timer.reached() and self.ui_additional()

    def commission_receive(self) -> bool:
        """领取委托奖励并返回是否领到；石油满时最多三次前往宿舍消耗后重试。"""
        for _ in range(3):
            try:
                return self._commission_receive()
            except OilMaxed:
                logger.info("Oil maxed, buy food to consume oil")
                RewardDorm(self.config, self.device).dorm_food_run(amount=10)
                self.ui_ensure(page_reward)

        logger.critical("Failed to handle oil maxed after 3 trial")
        raise HumanTakeoverRequiredError
