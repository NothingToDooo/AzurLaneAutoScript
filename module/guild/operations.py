from dataclasses import dataclass

from module.base.button import ButtonGrid
from module.base.timer import Timer
from module.base.utils import area_limit, area_pad, point_in_area, random_rectangle_vector
from module.config.utils import get_server_monthday
from module.exception import GameBugError
from module.guild import assets as guild_assets
from module.guild.base import GuildBase
from module.guild.guild_combat import GuildCombat
from module.logger import logger
from module.ocr.ocr import DigitCounter
from module.template.assets import TEMPLATE_OPERATIONS_RED_DOT

GUILD_OPERATIONS_PROGRESS = DigitCounter(
    guild_assets.OCR_GUILD_OPERATIONS_PROGRESS, letter=(255, 247, 247), threshold=64
)
GUILD_OPERATION_JOIN_STUCK_MESSAGE = "Unable to start/join guild operation"


@dataclass(slots=True)
class _GuildDispatchEntrances:
    expand: list
    enter: list


@dataclass(slots=True)
class _GuildOperationsEnsureState:
    confirm_timer: Timer
    join_confirm_count: int = 0


class GuildOperations(GuildBase):
    def _guild_operations_ensure(self, skip_first_screenshot=True):
        """等待作战背景和派遣/Boss 区加载；进入成功返回 True，资金不足返回 False。"""
        logger.attr("Guild master/official", self.config.GuildOperation_SelectNewOperation)
        state = _GuildOperationsEnsureState(confirm_timer=Timer(1.5, count=3).start())
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            self._raise_if_guild_operations_join_stuck(state)
            if self._guild_operation_fund_insufficient():
                return False
            if self._handle_guild_operations_start():
                state.confirm_timer.reset()
                continue
            if self._handle_guild_operations_join(state):
                continue
            if self._handle_guild_operations_join_popups(state):
                continue
            if self._guild_operations_loaded(state):
                return True
        return False

    def _raise_if_guild_operations_join_stuck(self, state):
        if state.join_confirm_count <= 5:
            return

        # 信息条显示 `none4302` 时，多半是其他公会管理已经开启了作战。
        # 重新进入公会页通常可以恢复。
        logger.warning(
            "Unable to start/join guild operation, "
            "probably because guild operation has been started by another guild officer already"
        )
        raise GameBugError(GUILD_OPERATION_JOIN_STUCK_MESSAGE)

    def _handle_guild_operations_join(self, state):
        if not self.appear(guild_assets.GUILD_OPERATIONS_JOIN, interval=3):
            return False

        if self._guild_operations_monthly_attempts_depleted():
            logger.info("Unable to join operation, no more monthly attempts left")
            self.device.click(guild_assets.GUILD_OPERATIONS_CLICK_SAFE_AREA)
        else:
            self._guild_operations_click_join_by_progress()
        state.confirm_timer.reset()
        return True

    def _guild_operations_monthly_attempts_depleted(self):
        return self.image_color_count(
            guild_assets.GUILD_OPERATIONS_MONTHLY_COUNT,
            color=(255, 93, 90),
            threshold=221,
            count=20,
        )

    def _guild_operations_click_join_by_progress(self):
        current, _remain, total = GUILD_OPERATIONS_PROGRESS.ocr(self.device.image)
        threshold = total * self.config.GuildOperation_JoinThreshold
        if current <= threshold:
            logger.info(f"Joining Operation, current progress less than threshold ({threshold:.2f})")
            self.device.click(guild_assets.GUILD_OPERATIONS_JOIN)
            return

        logger.info(f"Refrain from joining operation, current progress exceeds threshold ({threshold:.2f})")
        self.device.click(guild_assets.GUILD_OPERATIONS_CLICK_SAFE_AREA)

    def _handle_guild_operations_join_popups(self, state):
        if self.handle_popup_confirm("JOIN_OPERATION"):
            state.join_confirm_count += 1
            state.confirm_timer.reset()
            return True
        if not self.handle_popup_single("FLEET_UPDATED"):
            return False

        logger.info(
            "Fleet composition altered, may still be dispatch-able. However "
            "fellow guild members have updated their support line up. "
            "Suggestion: Enable Boss Recommend"
        )
        state.confirm_timer.reset()
        return True

    def _guild_operations_loaded(self, state):
        if not (
            self.appear(guild_assets.GUILD_BOSS_ENTER)
            or self.appear(guild_assets.GUILD_OPERATIONS_ACTIVE_CHECK, offset=(20, 20))
        ):
            return False
        if self.info_bar_count():
            return False
        return state.confirm_timer.reached()

    def _handle_guild_operations_start(self):
        """会长或军官开启所罗门海空战。

        普通成员每月只能参加两次，第三次通常无法派遣，会降低派遣评价和奖励。
        """
        if not self.config.GuildOperation_SelectNewOperation:
            return False

        today = get_server_monthday()
        limit = self.config.GuildOperation_NewOperationMaxDate
        if today >= limit:
            logger.info(f"No new guild operations because, today's date {today} >= limit {limit}")
            return False

        if self.appear_then_click(guild_assets.GUILD_OPERATIONS_SOLOMON, offset=(20, 20), interval=3):
            return True
        # 新作战会依次经过资金确认、加入和地图加载，由外层循环统一处理。
        return self.appear_then_click(guild_assets.GUILD_OPERATIONS_NEW, offset=(20, 20), interval=3)

    def _guild_operation_fund_insufficient(self):
        """仅在新作战页检测资金；不足返回 True，页面不匹配或资金充足返回 False。"""
        if not self.appear(guild_assets.GUILD_OPERATIONS_NEW, offset=(20, 20)):
            return False
        if self.image_color_count(
            guild_assets.GUILD_OPERATION_FUND_CHECK, color=(255, 93, 91), threshold=180, count=30
        ):
            logger.warning("Insufficient guild fund to start new operation")
            return True
        return False

    def _guild_operations_get_mode(self):
        """返回作战页状态：0 无作战、1 节点图、2 Raid Boss、None 无法确认。"""
        if self.appear(guild_assets.GUILD_OPERATIONS_INACTIVE_CHECK) and self.appear(
            guild_assets.GUILD_OPERATIONS_ACTIVE_CHECK
        ):
            logger.info(
                "Mode: Operations Inactive, please contact your Elite/Officer/Leader seniors to select "
                "an operation difficulty"
            )
            return 0
        if self.appear(guild_assets.GUILD_OPERATIONS_ACTIVE_CHECK):
            logger.info("Mode: Operations Active, may proceed to scan and dispatch fleets")
            return 1
        if self.appear(guild_assets.GUILD_BOSS_ENTER):
            logger.info("Mode: Guild Raid Boss (GUILD_BOSS_ENTER)")
            return 2
        if self.appear(guild_assets.GUILD_OPERATIONS_NEW, offset=(20, 20)):
            logger.info("Mode: Guild Raid Boss (GUILD_OPERATIONS_NEW)")
            return 2
        logger.warning("Operations interface is unrecognized")
        return None

    def _guild_operations_get_entrance(self):
        """实时返回展开和进入按钮列表；展开任务链后两类按钮会动态换位。"""
        # 整条作战任务链所在区域。
        detection_area = (152, 135, 1280, 630)
        # 向内收一点，避免点到边缘。
        pad = 5

        list_expand = []
        list_enter = []
        dots = TEMPLATE_OPERATIONS_RED_DOT.match_multi(self.image_crop(detection_area, copy=False), threshold=5)
        logger.info(f"Active operations found: {len(dots)}")
        for dot in dots:
            button = dot.move(vector=detection_area[:2])
            expand = button.crop(area=(-257, 14, 12, 51), name="DISPATCH_ENTRANCE_1")
            enter = button.crop(area=(-257, -109, 12, -1), name="DISPATCH_ENTRANCE_2")
            for b in [expand, enter]:
                b.area = area_limit(b.area, detection_area)
                b.set_button_area(area_pad(b.area, pad))
            list_expand.append(expand)
            list_enter.append(enter)

        return list_expand, list_enter

    def _guild_operations_dispatch_swipe(self, forward=True, skip_first_screenshot=True):
        """沿指定方向最多滑动五次，查找游戏自动聚焦遗漏的后续派遣任务。"""
        # 整条作战任务链所在区域。
        detection_area = (152, 135, 1280, 630)
        direction_vector = (-600, 0) if forward else (600, 0)

        for _ in range(5):
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            entrance_1, _entrance_2 = self._guild_operations_get_entrance()
            if len(entrance_1):
                return True

            p1, p2 = random_rectangle_vector(
                direction_vector, box=detection_area, random_range=(-50, -50, 50, 50), padding=20
            )
            self.device.drag(p1, p2, point_random=(0, 0, 0, 0))

        logger.warning("Failed to find active operation dispatch")
        return False

    def _guild_operations_dispatch_enter(self, skip_first_screenshot=True):
        """从节点图实时展开并进入派遣准备页；当前节点无入口时返回 False。"""
        timer_1 = Timer(2, count=5)
        timer_2 = Timer(2, count=5)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            active, entrances = self._guild_operations_active_dispatch_entrances()
            if active and entrances is None:
                return False
            if entrances is not None:
                if self._guild_operations_click_dispatch_expand(entrances, timer_1):
                    continue
                self._guild_operations_click_dispatch_enter(entrances, timer_1, timer_2)

            if self._guild_operations_handle_dispatch_quick(timer_1, timer_2):
                continue

            if self.appear(guild_assets.GUILD_DISPATCH_RECOMMEND, offset=(20, 20)):
                break

        return True

    def _guild_operations_active_dispatch_entrances(self):
        """返回 (是否在节点图, 动态派遣入口)；无入口时第二项为 None。"""
        if not self.appear(guild_assets.GUILD_OPERATIONS_ACTIVE_CHECK, offset=(20, 20)):
            return False, None

        entrance_1, entrance_2 = self._guild_operations_get_entrance()
        if not entrance_1:
            return True, None
        return True, _GuildDispatchEntrances(expand=entrance_1, enter=entrance_2)

    def _guild_operations_click_dispatch_expand(self, entrances, timer):
        if not timer.reached():
            return False

        self.device.click(entrances.expand[0])
        timer.reset()
        return True

    def _guild_operations_click_dispatch_enter(self, entrances, expand_timer, enter_timer):
        if not enter_timer.reached():
            return False

        for button in entrances.enter:
            # 进入按钮右上角的 Easy/Normal/Hard 周围有黑色区域。
            # 作战未展开时，这个位置只是高斯模糊背景。
            if self.image_color_count(button, color=(0, 0, 0), threshold=235, count=50):
                self.device.click(button)
                expand_timer.reset()
                enter_timer.reset()
                return True
        return False

    def _guild_operations_handle_dispatch_quick(self, expand_timer, enter_timer):
        if not self.appear_then_click(guild_assets.GUILD_DISPATCH_QUICK, offset=(20, 20), interval=2):
            return False

        expand_timer.reset()
        enter_timer.reset()
        return True

    def _guild_operations_get_dispatch(self):
        """直接检测动态舰队切换点；返回切往最右侧的按钮，已在最右侧时返回 None。"""
        # 红点偶尔不显示，因此不能用它判断可用派遣。
        # 舰队切换点，最多有 4 种布局。
        #          | 1 |
        #       | 1 | | 2 |
        #    | 1 | | 2 | | 3 |
        # | 1 | | 2 | | 3 | | 4 |
        #   0  1  2  3  4  5  6   switch_grid 中的按钮。
        switch_grid = ButtonGrid(origin=(573.5, 381), delta=(20.5, 0), button_shape=(11, 24), grid_shape=(7, 1))
        # 可点击舰队切换点颜色。
        color_active = (74, 117, 222)
        # 当前舰队颜色。
        color_inactive = (33, 48, 66)

        text = []
        index = 0
        button = None
        for switch in switch_grid.buttons:
            if self.image_color_count(switch, color=color_inactive, threshold=235, count=30):
                index += 1
                text.append(f"| {index} |")
                button = switch
            elif self.image_color_count(switch, color=color_active, threshold=235, count=30):
                index += 1
                text.append(f"[ {index} ]")
                button = switch

        # 日志示例：| 1 | | 2 | [ 3 ]
        text = " ".join(text)
        logger.attr("Dispatch_fleet", text)
        if text.endswith("]"):
            logger.info("Already at the most right fleet")
            return None
        return button

    def _guild_operations_dispatch_switch_fleet(self, skip_first_screenshot=True):
        """在派遣准备页切到最右侧可用舰队。"""
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            button = self._guild_operations_get_dispatch()
            if button is None:
                break
            if point_in_area((640, 393), button.area):
                logger.info("Dispatching the first fleet, skip switching")
            else:
                self.device.click(button)
                # 等点击动画结束，否则会干扰 _guild_operations_get_dispatch()。
                self.device.sleep((0.5, 0.6))
                continue

    def _guild_operations_dispatch_execute(self, skip_first_screenshot=True):
        """在派遣准备页补全推荐舰队并执行派遣。"""
        dispatched = False
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(guild_assets.GUILD_DISPATCH_FLEET_UNFILLED, offset=(20, 20), interval=3):
                # 这里不用 offset，因为未满员按钮和满员按钮只差颜色。
                # 选船需要几秒，所以保持较长 interval。
                self.device.click(guild_assets.GUILD_DISPATCH_RECOMMEND)
                continue
            if not dispatched and self.appear(guild_assets.GUILD_DISPATCH_FLEET, offset=(20, 20), interval=3):
                # 满员和未满员按钮特征相同，只能再用蓝色背景确认一次。
                if self.image_color_count(
                    guild_assets.GUILD_DISPATCH_FLEET,
                    color=(82, 93, 221),
                    threshold=235,
                    count=500,
                ):
                    self.device.click(guild_assets.GUILD_DISPATCH_FLEET)
                else:
                    self.interval_clear(guild_assets.GUILD_DISPATCH_FLEET)
                continue
            if self.handle_popup_confirm("GUILD_DISPATCH"):
                self.interval_clear(guild_assets.GUILD_DISPATCH_FLEET)
                dispatched = True
                continue

            if self.appear(guild_assets.GUILD_DISPATCH_IN_PROGRESS):
                # 首次派遣会显示派遣中按钮。
                logger.info("Fleet dispatched, dispatch in progress")
                break
            if (
                dispatched
                and self.appear(guild_assets.GUILD_DISPATCH_FLEET, offset=(20, 20), interval=3)
                and self.image_color_count(
                    guild_assets.GUILD_DISPATCH_FLEET,
                    color=(82, 93, 221),
                    threshold=235,
                    count=500,
                )
            ):
                # 后续派遣会继续显示满员按钮；如果实际没派出，外层会重试。
                logger.info("Fleet dispatched")
                break

    def _guild_operations_dispatch_exit(self, skip_first_screenshot=True):
        """从派遣准备页退出到作战节点图。"""
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(guild_assets.GUILD_DISPATCH_RECOMMEND, offset=(20, 20), interval=2):
                self.device.click(guild_assets.GUILD_DISPATCH_CLOSE)
                continue
            if self.appear(guild_assets.GUILD_DISPATCH_QUICK, offset=(20, 20), interval=2):
                self.device.click(guild_assets.GUILD_DISPATCH_CLOSE)
                continue
            if self.appear(guild_assets.GUILD_DISPATCH_IN_PROGRESS, interval=2):
                # 这里不用 offset，派遣中按钮本身靠颜色识别。
                self.device.click(guild_assets.GUILD_DISPATCH_CLOSE)
                continue

            if self.appear(guild_assets.GUILD_OPERATIONS_ACTIVE_CHECK):
                break

    def _guild_operations_dispatch(self):
        """在作战节点图完成全部可用派遣；未找到或重试耗尽返回 False。"""
        logger.hr("Guild dispatch")
        success = False
        for _ in reversed(range(2)):
            if self._guild_operations_dispatch_swipe(forward=_):
                success = True
                break
            if _:
                self.guild_side_navbar_ensure(bottom=2)
                self.guild_side_navbar_ensure(bottom=1)
                self._guild_operations_ensure()
        if not success:
            return False

        for _ in range(5):
            if self._guild_operations_dispatch_enter():
                self._guild_operations_dispatch_switch_fleet()
                self._guild_operations_dispatch_execute()
                self._guild_operations_dispatch_exit()
            else:
                return True

        logger.warning("Too many trials on guild operation dispatch")
        return False

    def _guild_operations_boss_preparation(self, az, skip_first_screenshot=True):
        """从 Boss 页进入战斗；独立 GuildCombat 实例用于隔离继承方法冲突。"""
        is_loading = False
        dispatch_count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear_then_click(guild_assets.GUILD_BOSS_ENTER, interval=3):
                continue

            if self.appear(guild_assets.GUILD_DISPATCH_FLEET, offset=(20, 20), interval=3):
                # 即使舰队为空，按钮也不会显示成灰色。
                if dispatch_count < 5:
                    self.device.click(guild_assets.GUILD_DISPATCH_FLEET)
                    dispatch_count += 1
                else:
                    logger.warning(
                        "Fleet composition error. Preloaded guild support selection may be "
                        "preventing dispatch. Suggestion: Enable Boss Recommend"
                    )
                    return False
                continue

            if (
                self.config.GuildOperation_BossFleetRecommend
                and self.info_bar_count()
                and self.appear_then_click(guild_assets.GUILD_DISPATCH_RECOMMEND_2, interval=3)
            ):
                continue

            # 只在首次检测到加载时打印。
            if not is_loading and az.is_combat_loading():
                self.device.screenshot_interval_set("combat")
                is_loading = True
                continue

            if az.handle_combat_automation_confirm():
                continue

            pause = az.is_combat_executing()
            if pause:
                logger.attr("BattleUI", pause)
                return True
        return False

    def _guild_operations_boss_combat(self):
        """从 Boss 页执行战斗并返回；准备失败时返回 False。"""
        az = GuildCombat(self.config, device=self.device)

        if not self._guild_operations_boss_preparation(az):
            return False
        az.combat_execute(auto="combat_auto", submarine="every_combat")
        az.combat_status(expected_end="in_ui")
        logger.info("Guild Raid Boss has been repelled")
        return True

    def _guild_operations_boss_available(self):
        appear = self.image_color_count(
            guild_assets.GUILD_BOSS_AVAILABLE, color=(140, 243, 99), threshold=221, count=10
        )
        if appear:
            logger.info("Guild boss available")
        else:
            logger.info("Guild boss not available")
        return appear

    def guild_operations(self):
        logger.hr("Guild operations", level=1)
        self.guild_side_navbar_ensure(bottom=1)
        entered = self._guild_operations_ensure()
        if not entered:
            logger.info(f"Guild operation run success: {entered}")
            return False
        operations_mode = self._guild_operations_get_mode()

        result = True
        if operations_mode == 0:
            # 没有进行中的作战时有意不执行后续动作。
            pass
        elif operations_mode == 1:
            self._guild_operations_dispatch()
        elif operations_mode == 2:
            if self._guild_operations_boss_available():
                if self.config.GuildOperation_AttackBoss:
                    result = self._guild_operations_boss_combat()
                else:
                    logger.info("Auto-battle disabled, play manually to complete this Guild Task")
        else:
            result = False

        logger.info(f"Guild operation run success: {result}")
        return result
