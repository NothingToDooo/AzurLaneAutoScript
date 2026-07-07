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


class GuildOperations(GuildBase):
    def _guild_operations_ensure(self, skip_first_screenshot=True):
        """
        Ensure guild operation is loaded
        After entering guild operation, background loaded first, then dispatch/boss

        Returns:
            bool: True if success to enter operation
                False if fund insufficient
        """
        logger.attr("Guild master/official", self.config.GuildOperation_SelectNewOperation)
        confirm_timer = Timer(1.5, count=3).start()
        click_count = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # 结束。
            if click_count > 5:
                # 信息条显示 `none4302` 时，多半是其他公会管理已经开启了作战。
                # 重新进入公会页通常可以恢复。
                logger.warning(
                    "Unable to start/join guild operation, "
                    "probably because guild operation has been started by another guild officer already"
                )
                raise GameBugError("Unable to start/join guild operation")

            if self._guild_operation_fund_insufficient():
                return False
            if self._handle_guild_operations_start():
                confirm_timer.reset()
                continue
            if self.appear(guild_assets.GUILD_OPERATIONS_JOIN, interval=3):
                if self.image_color_count(
                    guild_assets.GUILD_OPERATIONS_MONTHLY_COUNT,
                    color=(255, 93, 90),
                    threshold=221,
                    count=20,
                ):
                    logger.info("Unable to join operation, no more monthly attempts left")
                    self.device.click(guild_assets.GUILD_OPERATIONS_CLICK_SAFE_AREA)
                else:
                    current, _remain, total = GUILD_OPERATIONS_PROGRESS.ocr(self.device.image)
                    threshold = total * self.config.GuildOperation_JoinThreshold
                    if current <= threshold:
                        logger.info(f"Joining Operation, current progress less than threshold ({threshold:.2f})")
                        self.device.click(guild_assets.GUILD_OPERATIONS_JOIN)
                    else:
                        logger.info(
                            f"Refrain from joining operation, current progress exceeds threshold ({threshold:.2f})"
                        )
                        self.device.click(guild_assets.GUILD_OPERATIONS_CLICK_SAFE_AREA)
                confirm_timer.reset()
                continue
            if self.handle_popup_confirm("JOIN_OPERATION"):
                click_count += 1
                confirm_timer.reset()
                continue
            if self.handle_popup_single("FLEET_UPDATED"):
                logger.info(
                    "Fleet composition altered, may still be dispatch-able. However "
                    "fellow guild members have updated their support line up. "
                    "Suggestion: Enable Boss Recommend"
                )
                confirm_timer.reset()
                continue

            # 结束。
            if (
                self.appear(guild_assets.GUILD_BOSS_ENTER)
                or self.appear(guild_assets.GUILD_OPERATIONS_ACTIVE_CHECK, offset=(20, 20))
            ) and not self.info_bar_count() and confirm_timer.reached():
                return True
        return False

    def _handle_guild_operations_start(self):
        """
        开启新的公会作战。

        当前账号必须是公会会长或军官。每月第三次公会作战不建议开启，普通成员每月只能参加两次，
        第三次通常无法参与派遣，最终会降低派遣评价和奖励。

        Returns:
            bool: 是否发生点击。
        """
        if not self.config.GuildOperation_SelectNewOperation:
            return False

        today = get_server_monthday()
        limit = self.config.GuildOperation_NewOperationMaxDate
        if today >= limit:
            logger.info(f"No new guild operations because, today's date {today} >= limit {limit}")
            return False

        # 固定选择收益最高的所罗门海空战。
        if self.appear_then_click(guild_assets.GUILD_OPERATIONS_SOLOMON, offset=(20, 20), interval=3):
            return True
        # 进入刚开启的新作战。
        # 页面切换示例：
        # - GUILD_OPERATIONS_SOLOMON
        # - GUILD_OPERATIONS_NEW
        # - handle_popup_confirm()，确认消耗公会资金。
        # - GUILD_OPERATIONS_JOIN
        # - GUILD_OPERATIONS_ACTIVE_CHECK
        return self.appear_then_click(guild_assets.GUILD_OPERATIONS_NEW, offset=(20, 20), interval=3)

    def _guild_operation_fund_insufficient(self):
        """
        Returns:
            bool: True if insufficient

        Pages:
            in: GUILD_OPERATIONS_NEW
        """
        if not self.appear(guild_assets.GUILD_OPERATIONS_NEW, offset=(20, 20)):
            return False
        if self.image_color_count(
            guild_assets.GUILD_OPERATION_FUND_CHECK, color=(255, 93, 91), threshold=180, count=30
        ):
            logger.warning("Insufficient guild fund to start new operation")
            return True
        return False

    def _guild_operations_get_mode(self):
        """
        Returns:
            int: 当前公会作战菜单状态。
                0 - 没有进行中的作战，需要精英、军官或会长先选择一个。
                1 - 作战进行中，显示作战节点图。
                2 - 公会 Raid Boss 已开启。
                无法确认状态时返回 None。

        Pages:
            in: GUILD_OPERATIONS
            out: GUILD_OPERATIONS
        """
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
        """
        Get 2 entrance button of guild dispatch
        If operation is on the top, after clicking expand button, operation chain moves downward, and enter button
        appears on the top. So we need to detect two buttons in real time.

        Returns:
            list[Button], list[Button]: Expand button, enter button

        Pages:
            in: page_guild, guild operation, operation map (GUILD_OPERATIONS_ACTIVE_CHECK)
        """
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
                b._button = area_pad(b.area, pad)
            list_expand.append(expand)
            list_enter.append(enter)

        return list_expand, list_enter

    def _guild_operations_dispatch_swipe(self, forward=True, skip_first_screenshot=True):
        """
        Although AL will auto focus to active dispatch, but it's bugged.
        It can't reach the operations behind.
        So this method will swipe behind, and focus to active dispatch.
        Force to use minitouch, because uiautomator2 will need longer swipes.

        Args:
            forward (bool): direction of horizontal swipe
            skip_first_screenshot (bool):

        Returns:
            bool: If found active dispatch.
        """
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
            self.device.drag(p1, p2, segments=2, shake=(0, 25), point_random=(0, 0, 0, 0), shake_random=(0, -5, 0, 5))
            # self.device.sleep(0.3)

        logger.warning("Failed to find active operation dispatch")
        return False

    def _guild_operations_dispatch_enter(self, skip_first_screenshot=True):
        """
        Returns:
            bool: If entered

        Pages:
            in: page_guild, guild operation, operation map (GUILD_OPERATIONS_ACTIVE_CHECK)
                After entering guild operation, game will auto located to active operation.
                It is the main operation on chain that will be located to, side operations will be ignored.
            out: page_guild, guild operation, operation dispatch preparation (GUILD_DISPATCH_RECOMMEND)
        """
        timer_1 = Timer(2, count=5)
        timer_2 = Timer(2, count=5)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(guild_assets.GUILD_OPERATIONS_ACTIVE_CHECK, offset=(20, 20)):
                entrance_1, entrance_2 = self._guild_operations_get_entrance()
                if not len(entrance_1):
                    return False
                if timer_1.reached():
                    self.device.click(entrance_1[0])
                    timer_1.reset()
                    continue
                if timer_2.reached():
                    for button in entrance_2:
                        # 进入按钮右上角的 Easy/Normal/Hard 周围有黑色区域。
                        # 作战未展开时，这个位置只是高斯模糊背景。
                        if self.image_color_count(button, color=(0, 0, 0), threshold=235, count=50):
                            self.device.click(button)
                            timer_1.reset()
                            timer_2.reset()
                            break

            if self.appear_then_click(guild_assets.GUILD_DISPATCH_QUICK, offset=(20, 20), interval=2):
                timer_1.reset()
                timer_2.reset()
                continue

            # 结束。
            if self.appear(guild_assets.GUILD_DISPATCH_RECOMMEND, offset=(20, 20)):
                break

        return True

    def _guild_operations_get_dispatch(self):
        """
        获取用于切换到可用派遣舰队的按钮。

        旧版本会检测切换点上的红点；红点偶尔会原因不明地不显示，所以这里直接检测切换点本身。

        Returns:
            Button: 切换到可用派遣的按钮；已经在最右侧舰队时返回 None。

        Pages:
            in: page_guild, guild operation, operation dispatch preparation (GUILD_DISPATCH_RECOMMEND)
        """
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
        """
        Switch to the fleet on most right

        Pages:
            in: page_guild, guild operation, operation dispatch preparation (GUILD_DISPATCH_RECOMMEND)
            out: page_guild, guild operation, operation dispatch preparation (GUILD_DISPATCH_RECOMMEND)
        """
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
        """
        Executes the dispatch sequence

        Pages:
            in: page_guild, guild operation, operation dispatch preparation (GUILD_DISPATCH_RECOMMEND)
            out: page_guild, guild operation, operation dispatch preparation (GUILD_DISPATCH_RECOMMEND)
        """
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

            # 结束。
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
        """
        Exit to operation map

        Pages:
            in: page_guild, guild operation, operation dispatch preparation (GUILD_DISPATCH_RECOMMEND)
            out: page_guild, guild operation, operation map (GUILD_OPERATIONS_ACTIVE_CHECK)
        """
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

            # 结束。
            if self.appear(guild_assets.GUILD_OPERATIONS_ACTIVE_CHECK):
                break

    def _guild_operations_dispatch(self):
        """
        Run guild dispatch

        Pages:
            in: page_guild, guild operation, operation map (GUILD_OPERATIONS_ACTIVE_CHECK)
            out: page_guild, guild operation, operation map (GUILD_OPERATIONS_ACTIVE_CHECK)
        """
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
        """
        Execute preparation sequence for guild raid boss

        az is a GuildCombat instance to handle combat various
        interfaces. Independently created to avoid conflicts
        or override methods of parent/child objects

        Pages:
            in: GUILD_OPERATIONS_BOSS
            out: IN_BATTLE
        """
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

            if self.config.GuildOperation_BossFleetRecommend and self.info_bar_count() and self.appear_then_click(
                guild_assets.GUILD_DISPATCH_RECOMMEND_2, interval=3
            ):
                continue

            # 只在首次检测到加载时打印。
            if not is_loading and az.is_combat_loading():
                self.device.screenshot_interval_set("combat")
                is_loading = True
                continue

            if az.handle_combat_automation_confirm():
                continue

            # End
            pause = az.is_combat_executing()
            if pause:
                logger.attr("BattleUI", pause)
                return True
        return False

    def _guild_operations_boss_combat(self):
        """
        Execute combat sequence
        If battle could not be prepared, exit

        Pages:
            in: GUILD_OPERATIONS_BOSS
            out: GUILD_OPERATIONS_BOSS
        """
        az = GuildCombat(self.config, device=self.device)

        if not self._guild_operations_boss_preparation(az):
            return False
        az.combat_execute(auto="combat_auto", submarine="every_combat")
        az.combat_status(expected_end="in_ui")
        logger.info("Guild Raid Boss has been repelled")
        return True

    def _guild_operations_boss_available(self):
        """
        Returns:
            bool:
        """
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
        # 判断作战模式，目前有 3 种。
        operations_mode = self._guild_operations_get_mode()

        # 按检测到的模式执行动作。
        result = True
        if operations_mode == 0:
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
