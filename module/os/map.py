import time
from typing import TYPE_CHECKING, Literal, override

from module.base.timer import Timer
from module.config.utils import get_os_reset_remain
from module.exception import CampaignEnd, GameTooManyClickError, HumanTakeoverRequiredError, MapWalkError
from module.handler.login import LoginHandler
from module.logger import logger
from module.map.map import Map
from module.os.assets import FLEET_EMP_DEBUFF, MAP_GOTO_GLOBE_FOG
from module.os.fleet import OSFleet
from module.os.globe_camera import GlobeCamera
from module.os.globe_operation import RewardUncollectedError, ZoneType
from module.os_handler.action_point import ActionPointLimit
from module.os_handler.assets import (
    AUTO_SEARCH_OS_MAP_OPTION_OFF,
    AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
    AUTO_SEARCH_OS_MAP_OPTION_ON,
)
from module.os_handler.strategic import StrategicSearchHandler
from module.ui.page import page_os

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.config.config import AzurLaneConfig
    from module.device.device import Device
    from module.map_detection.grid import Grid
    from module.os.globe_zone import Zone, ZoneName

type RescanMode = Literal["current", "full"]
type OSMapEvent = Literal[
    "is_exploration_reward",
    "is_akashi",
    "is_scanning_device",
    "is_logging_tower",
    "is_fleet_mechanism",
]


class OSMap(OSFleet, Map, GlobeCamera, StrategicSearchHandler):
    def os_init(self) -> None:
        """调用大世界功能前完成页面定位、区域状态刷新和当前区域清理，结束于区域地图。"""
        logger.hr("OS init", level=1)
        self.config.apply_runtime_overlay(Submarine_Fleet=1, Submarine_Mode="every_combat", STORY_ALLOW_SKIP=False)
        self._os_init_ensure_page()
        self._os_init_prepare_current_zone()
        self._os_init_clear_current_zone()

    def _os_init_ensure_page(self) -> None:
        if self.is_in_map():
            logger.info("Already in os map")
        elif self.is_in_globe():
            self.os_globe_goto_map()
        else:
            if self.ui_page_appear(page_os):
                self.ui_goto_main()
            self.ui_ensure(page_os)

    def _os_init_prepare_current_zone(self) -> None:
        self.zone_init()
        self.hp_reset()
        self.handle_after_auto_search()
        self.handle_current_fleet_resolve(revert=False)

        if self.is_in_special_zone():
            logger.warning("OS is in a special zone type, while SAFE and DANGEROUS are acceptable")
            self.map_exit()

    def _os_init_clear_current_zone(self) -> None:
        if self.zone.zone_id in (22, 44, 154):
            logger.info("In zone 22, 44, 154, skip running first auto search")
            self.handle_ash_beacon_attack()
        else:
            self.run_auto_search(rescan=False)
            self.handle_after_auto_search()

    def get_current_zone_from_globe(self) -> Zone:
        self.os_map_goto_globe(unpin=False)
        self.globe_update()
        self.zone = self.get_globe_pinned_zone()
        self.zone_config_set()
        self.os_globe_goto_map()
        self.zone_init(fallback_init=False)
        return self.zone

    def globe_goto(
        self,
        zone: ZoneName,
        types: ZoneType | Sequence[ZoneType] = ("SAFE", "DANGEROUS"),
        *,
        refresh: bool = False,
        stop_if_safe: bool = False,
    ) -> bool:
        """从区域地图或全球地图前往指定海域，结束于区域地图。

        zone 接受多语言名称、编号或 Zone；types 按调用方顺序尝试 DANGEROUS、SAFE、OBSCURE、
        ABYSSAL、STRONGHOLD。已在目标海域时，refresh 控制是否重新进入；stop_if_safe 会在安全海域返回 False。
        返回是否发生海域切换。
        """
        zone = self.name_to_zone(zone)
        logger.hr(f"Globe goto: {zone}")
        if self.zone == zone:
            if refresh:
                logger.info("Goto another zone to refresh current zone")
                self.globe_goto(self.zone_nearest_azur_port(self.zone), types=("SAFE", "DANGEROUS"), refresh=False)
            else:
                if self.is_in_globe():
                    self.os_globe_goto_map()
                logger.info("Already at target zone")
                return False
        if self.is_in_special_zone():
            self.map_exit()
        if self.is_in_map():
            self.os_map_goto_globe()
        self.globe_update()
        self.globe_focus_to(zone)
        if stop_if_safe and self.zone_has_safe():
            logger.info("Zone is safe, stopped")
            self.ensure_no_zone_pinned()
            return False
        self.zone_type_select(types=types)
        self.globe_enter(zone)
        if hasattr(self, "zone"):
            del self.zone
        self.zone_init()
        return True

    @override
    def os_map_goto_globe(self, *, unpin: bool = True) -> None:
        """
        包装 os_map_goto_globe，处理未领取探索奖励导致的退出失败。

        区域内存在未领取探索奖励时，先执行自动搜索，再重新进入大地图。
        """
        for _ in range(3):
            try:
                super().os_map_goto_globe(unpin=unpin)
            except RewardUncollectedError:
                # 搜索后处理会退出当前海域，递归调用还会触发 RecursionError，因此必须禁用。
                self.run_auto_search(rescan=True, after_auto_search=False)
                continue
            else:
                return

        logger.error("Failed to solve uncollected rewards")
        raise GameTooManyClickError

    def port_goto(self, *, allow_port_arrive: bool = True) -> bool:
        """前往港口并处理步数不同步，返回是否成功。"""
        for _ in range(3):
            try:
                super().port_goto(allow_port_arrive=allow_port_arrive)
            except MapWalkError:
                pass
            else:
                return True

            logger.info("Goto another port then re-enter")
            prev = self.zone
            other = self.name_to_zone(1) if prev.zone_id == 0 else self.zone_nearest_azur_port(prev)
            self.globe_goto(other)
            self.globe_goto(prev)

        logger.warning("Failed to solve MapWalkError when going to port")
        return False

    def fleet_repair(self, *, revert: bool = True) -> None:
        """在最近港口维修舰队；revert 控制是否返回原海域。"""
        logger.hr("OS fleet repair")
        prev = self.zone
        if self.zone.is_azur_port:
            logger.info("Already in azur port")
        else:
            self.globe_goto(self.zone_nearest_azur_port(self.zone))

        self.port_goto()
        self.port_enter()
        self.port_dock_repair()
        self.port_quit()

        if revert and prev != self.zone:
            self.globe_goto(prev)

    def handle_fleet_repair(self, *, revert: bool = True) -> bool:
        """需要时维修舰队；revert 控制是否返回原海域，并返回是否执行维修。"""
        if self.config.OpsiGeneral_RepairThreshold < 0:
            return False
        if self.is_in_special_zone():
            logger.info("OS is in a special zone type, skip fleet repair")
            return False

        self.hp_get()
        check = [
            round(data, 2) <= self.config.OpsiGeneral_RepairThreshold if use else False
            for data, use in zip(self.hp, self.hp_has_ship, strict=True)
        ]
        if any(check):
            logger.info(
                "At least one ship is below threshold "
                f"{int(self.config.OpsiGeneral_RepairThreshold * 100)!s}%, "
                "retreating to nearest azur port for repairs"
            )
            self.fleet_repair(revert=revert)
            self.hp_reset()
            return True
        logger.info(
            "No ship found to be below threshold "
            f"{int(self.config.OpsiGeneral_RepairThreshold * 100)!s}%, "
            "continue OS exploration"
        )
        self.hp_reset()
        return False

    def fleet_resolve(self, *, revert: bool = True) -> None:
        """前往低侵蚀海域战斗以解除低士气；revert 控制是否返回原海域。"""
        logger.hr("OS fleet cure low resolve debuff")

        prev = self.zone
        self.globe_goto(22)
        self.zone_init()
        self.run_auto_search()

        if revert and prev != self.zone:
            self.globe_goto(prev)

    def handle_fleet_resolve(self, *, revert: bool = False) -> bool:
        """检查并解除各舰队的低士气；revert 控制是否返回原海域。"""
        if self.is_in_special_zone():
            logger.info("OS is in a special zone type, skip fleet resolve")
            return False

        for index in [1, 2, 3, 4]:
            if not self.fleet_set(index):
                self.device.screenshot()

            if self.fleet_low_resolve_appear():
                logger.info("At least one fleet is afflicted with the low resolve debuff")
                self.fleet_resolve(revert=revert)
                return True

        logger.info("None of the fleets are afflicted with the low resolve debuff")
        return False

    def handle_current_fleet_resolve(self, *, revert: bool = False) -> bool:
        """初始化时只检查当前舰队的低士气；revert 控制是否返回原海域。"""
        if self.fleet_low_resolve_appear():
            logger.info("Current fleet is afflicted with the low resolve debuff")
            self.fleet_resolve(revert=revert)
            return True

        logger.info("Current fleet is not afflicted with the low resolve debuff")
        return False

    def handle_fleet_emp_debuff(self) -> bool:
        """通过移动舰队解除会限制步数并干扰自动搜索的 EMP，返回是否处理。"""
        if self.is_in_special_zone():
            logger.info("OS is in a special zone type, skip handle_fleet_emp_debuff")
            return False

        def has_emp_debuff() -> bool:
            return self.appear(FLEET_EMP_DEBUFF, offset=(50, 20))

        for trial in range(5):
            if not has_emp_debuff():
                logger.info("No EMP debuff on current fleet")
                return trial > 0

            current = self.get_fleet_current_index()
            logger.hr(f"Solve EMP debuff on fleet {current}")
            self.globe_goto(self.zone_nearest_azur_port(self.zone))

            logger.info("Find a fleet without EMP debuff")
            for fleet in [1, 2, 3, 4]:
                self.fleet_set(fleet)
                if has_emp_debuff():
                    logger.info(f"Fleet {fleet} is under EMP debuff")
                    continue
                logger.info(f"Fleet {fleet} is not under EMP debuff")
                break

            logger.info("Solve EMP debuff by going somewhere else")
            self.port_goto(allow_port_arrive=False)
            self.fleet_set(current)

        logger.warning("Failed to solve EMP debuff after 5 trial, assume solved")
        return True

    def handle_fog_block(self, *, repair: bool = True) -> bool:
        """游戏 bug 可能使迷雾跨海域或页面残留；重启后恢复任务，repair 控制是否顺带维修。"""
        if not self.appear(MAP_GOTO_GLOBE_FOG):
            return False

        logger.warning(
            f"Triggered stuck fog status, restarting game to resolve and continue {self.config.task.command}"
        )

        # 直接重启而不调用新任务，确保当前任务不中断。
        self.device.app_stop()
        self.device.app_start()
        LoginHandler(self.config, self.device).handle_app_login()

        self.ui_ensure(page_os)
        if repair:
            self.handle_fleet_repair(revert=False)

        return True

    def get_action_point_limit(self) -> int:
        """月末覆盖行动力保留配置，以便自动消耗全部行动力。"""
        remain = get_os_reset_remain()
        if remain <= 0:
            if self.config.is_task_enabled("OpsiCrossMonth"):
                logger.info(
                    "Just less than 1 day to OpSi reset, OpsiCrossMonth is enabled"
                    "set OpsiMeowfficerFarming.ActionPointPreserve to 300 temporarily"
                )
                return 300
            logger.info("Just less than 1 day to OpSi reset, set ActionPointPreserve to 0 temporarily")
            return 0
        if self.is_cl1_enabled and remain <= 2:
            logger.info(
                "Just less than 3 days to OpSi reset, set ActionPointPreserve to 1000 temporarily for hazard 1 leveling"
            )
            return 1000
        if remain <= 2:
            logger.info("Just less than 3 days to OpSi reset, set ActionPointPreserve to 300 temporarily")
            return 300
        logger.info("Not close to OpSi reset")
        return 2000

    def handle_after_auto_search(self) -> bool:
        logger.hr("After auto search", level=2)
        solved = False
        solved |= self.handle_fleet_emp_debuff()
        solved |= self.handle_fleet_repair(revert=False)
        logger.info(f"Handle after auto search finished, solved={solved}")
        return solved

    def cl1_ap_preserve(self) -> None:
        """保留足够启动 CL1 的行动力。"""
        if (
            self.is_cl1_enabled
            and get_os_reset_remain() > 2
            and self.get_yellow_coins() > self.config.OS_CL1_YELLOW_COINS_PRESERVE
        ):
            logger.info("Keep 1000 AP when CL1 available")
            if not self.action_point_check(1000):
                raise ActionPointLimit

    _auto_search_battle_count = 0
    _auto_search_round_timer: float = 0.0

    def on_auto_search_battle_count_reset(self) -> None:
        self._auto_search_battle_count = 0
        self._auto_search_round_timer = 0.0

    def on_auto_search_battle_count_add(self) -> None:
        self._auto_search_battle_count += 1
        logger.attr("battle_count", self._auto_search_battle_count)
        if self.is_in_task_cl1_leveling and self._auto_search_battle_count % 2 == 1:
            if self._auto_search_round_timer:
                cost = round(time.time() - self._auto_search_round_timer, 2)
                logger.attr("CL1 time cost", f"{cost}s/round")
            self._auto_search_round_timer = time.time()

    def os_auto_search_daemon(self) -> int:
        """从关闭的自动搜索选项开始推进搜索，并返回完成战斗数。

        搜索结束抛出 CampaignEnd；没有自动搜索选项时抛出 HumanTakeoverRequiredError。
        地图清空后仍在关闭选项页并等待信息栏，获得奖励时结束于 AUTO_SEARCH_REWARD。
        """
        logger.hr("OS auto search", level=2)
        self.on_auto_search_battle_count_reset()
        unlock_checked = False
        unlock_check_timer = Timer(5, count=10).start()
        self.ash_popup_canceled = False

        success = True
        finished_combat = 0
        died_timer = Timer(1.5, count=3)
        self.hp_reset()
        for _ in self.loop():
            unlock_checked = self._os_auto_search_check_unlock_timeout(
                unlock_checked=unlock_checked,
                unlock_check_timer=unlock_check_timer,
            )
            if self._os_auto_search_fleet_died_confirmed(success=success, died_timer=died_timer):
                break
            if not unlock_checked:
                unlock_checked = self._os_auto_search_option_appeared()

            if self.handle_os_auto_search_map_option(enable=success):
                unlock_checked = True
                continue
            if self.handle_retirement():
                # 退役流程会打断自动搜索，需要重新进入本轮循环。
                self.ash_popup_canceled = True
                continue
            if self.combat_appear():
                combat_count, fleet_died = self._os_auto_search_handle_combat()
                finished_combat += combat_count
                if fleet_died:
                    success = False
                    continue
            if self.handle_map_event():
                # 自动搜索不能处理塞壬搜索装置，交给地图事件处理。
                continue

        return finished_combat

    @staticmethod
    def _os_auto_search_check_unlock_timeout(*, unlock_checked: bool, unlock_check_timer: Timer) -> bool:
        if unlock_checked or not unlock_check_timer.reached():
            return unlock_checked

        logger.critical("Unable to use auto search in current zone")
        logger.critical("Please finish the story mode of OpSi to unlock auto search before using any OpSi functions")
        raise HumanTakeoverRequiredError

    def _os_auto_search_fleet_died_confirmed(self, *, success: bool, died_timer: Timer) -> bool:
        if not self.is_in_map():
            died_timer.reset()
            return False

        self.device.stuck_record_clear()
        if success:
            died_timer.reset()
            return False
        if died_timer.reached():
            logger.warning("Fleet died confirm")
            return True
        return False

    def _os_auto_search_option_appeared(self) -> bool:
        return (
            self.appear(AUTO_SEARCH_OS_MAP_OPTION_OFF, offset=(5, 120))
            or self.appear(AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED, offset=(5, 120))
            or self.appear(AUTO_SEARCH_OS_MAP_OPTION_ON, offset=(5, 120))
        )

    def _os_auto_search_handle_combat(self) -> tuple[int, bool]:
        self.on_auto_search_battle_count_add()
        if self.auto_search_combat():
            return 1, False

        self.hp_get()
        if any(self.need_repair):
            logger.warning("Fleet died, stop auto search")
            return 0, True
        return 0, False

    def os_auto_search_run(self, *, strategic: bool = False) -> int:
        """运行普通或战略自动搜索，并返回完成战斗数。"""
        finished_combat = 0
        for _ in range(5):
            backup = self.config.temporary(Campaign_UseAutoSearch=True)
            try:
                if strategic:
                    self.strategic_search_start()
                combat = self.os_auto_search_daemon()
                finished_combat += combat
            except CampaignEnd:
                finished_combat += self._auto_search_battle_count
                logger.info("OS auto search finished")
            finally:
                backup.recover()

            # 信标弹窗中断搜索时继续；海域已清空时结束。
            if self.config.is_task_enabled("OpsiAshBeacon"):
                if self.handle_ash_beacon_attack() or self.ash_popup_canceled:
                    strategic = False
                    continue
                break
            if self.info_bar_count() >= 2:
                break
            if self.ash_popup_canceled:
                continue
            break

        return finished_combat

    def clear_question(self) -> bool:
        """最多尝试三次清理雷达附近及上方三格内的问号，避免双舰队机关导致循环。"""
        logger.hr("Clear question", level=2)
        for _ in range(3):
            grid = self.radar.predict_question(self.device.image, in_port=self.zone.is_port)
            if grid is None:
                logger.info("No question mark above current fleet on this radar")
                return False

            logger.info(f"Found question mark on {grid}")
            self.handle_info_bar()

            self.update_os()
            self.view.predict()
            self.view.show()

            grid = self.convert_radar_to_local(grid)
            self.device.click(grid)
            with self.config.temporary(STORY_ALLOW_SKIP=False):
                result = self.wait_until_walk_stable(walk_out_of_step=False, confirm_timer=Timer(1.5, count=4))
            if "akashi" in result:
                self._solved_map_event.add("is_akashi")
                return True
            if "event" in result and grid.is_logging_tower:
                self._solved_map_event.add("is_logging_tower")
                return True
            if "event" in result and grid.is_scanning_device:
                self._solved_map_event.add("is_scanning_device")
                self.os_auto_search_run()
                return True
            logger.warning(f"Arrive question with unexpected result: {result}, expected: {grid.str}")
            continue

        logger.warning("Failed to goto question mark after 5 trail, this might be 2 adjacent fleet mechanism, stopped")
        return False

    def run_auto_search(
        self,
        *,
        question: bool = True,
        rescan: RescanMode | bool | None = None,
        after_auto_search: bool = True,
    ) -> int:
        """用自动搜索清理当前海域，并返回完成战斗数；剧情模式需先通关才能解锁。

        question 控制搜索后是否清理附近问号；rescan 接受 current 或 full，分别复扫当前视野或全图，
        用于处理搜索遗漏的装置、明石商店和双舰队机关。特殊海域任务应禁用复扫。
        after_auto_search 控制是否执行搜索后处理。
        """
        if rescan is None:
            rescan = self.config.OpsiGeneral_DoRandomMapEvent
        if rescan is True:
            rescan = "full"
        self.handle_ash_beacon_attack()

        logger.info(f"Run auto search, question={question}, rescan={rescan}")
        finished_combat = 0
        while 1:
            combat = self.os_auto_search_run()
            finished_combat += combat

            self.hp_reset()
            self.hp_get()
            if after_auto_search and self.is_in_task_explore and not self.zone.is_port:
                prev = self.zone
                if self.handle_after_auto_search():
                    self.globe_goto(prev, types=("DANGEROUS",))
                    continue
            break

        self._solved_map_event = set()
        self._solved_fleet_mechanism = False
        if question:
            self.clear_question()
        if rescan:
            self.map_rescan(rescan_mode=rescan)

        return finished_combat

    def __init__(
        self,
        config: AzurLaneConfig,
        device: Device,
    ) -> None:
        self._solved_map_event: set[OSMapEvent] = set()
        self._solved_fleet_mechanism: bool = False
        super().__init__(config, device=device)

    def run_strategic_search(self) -> None:
        self.handle_ash_beacon_attack()

        logger.hr("Run strategy search", level=2)
        self.os_auto_search_run(strategic=True)

        self.hp_reset()
        self.hp_get()
        self._solved_map_event = set()
        self._solved_fleet_mechanism = False
        self.clear_question()
        self.map_rescan()

    def map_rescan_current(self) -> bool:
        """检查当前视野内可处理的随机地图事件，并返回是否处理。"""
        handlers = (
            self._map_rescan_exploration_reward,
            self._map_rescan_akashi,
            self._map_rescan_scanning_device,
            self._map_rescan_logging_tower,
            self._map_rescan_fleet_mechanism,
        )
        for handler in handlers:
            result = handler()
            if result is not None:
                return result

        logger.info("No map event")
        return False

    def _map_rescan_first_grid(self, event: OSMapEvent) -> Grid | None:
        if event in self._solved_map_event:
            return None

        grids = self.view.select(**{event: True})
        if not grids:
            return None

        grid = grids[0]
        if not getattr(grid, event):
            return None
        return grid

    def _map_rescan_exploration_reward(self) -> bool | None:
        grid = self._map_rescan_first_grid("is_exploration_reward")
        if grid is None:
            return None

        logger.info(f"Found exploration reward on {grid}")
        result = self.wait_until_walk_stable(walk_out_of_step=False, confirm_timer=Timer(1.5, count=4))
        if "event" in result:
            self._solved_map_event.add("is_exploration_reward")
            return True
        return False

    def _map_rescan_akashi(self) -> bool | None:
        grid = self._map_rescan_first_grid("is_akashi")
        if grid is None:
            return None

        logger.info(f"Found Akashi on {grid}")
        fleet = self.convert_radar_to_local((0, 0))
        if fleet.distance_to(grid) > 1:
            self.device.click(grid)
            with self.config.temporary(STORY_ALLOW_SKIP=False):
                result = self.wait_until_walk_stable(walk_out_of_step=False)
            if "akashi" in result:
                self._solved_map_event.add("is_akashi")
                return True
            return False

        logger.info(f"Akashi ({grid}) is near current fleet ({fleet})")
        self.handle_akashi_supply_buy(grid)
        self._solved_map_event.add("is_akashi")
        return True

    def _map_rescan_scanning_device(self) -> bool | None:
        grid = self._map_rescan_first_grid("is_scanning_device")
        if grid is None:
            return None

        logger.info(f"Found scanning device on {grid}")
        if self.is_in_task_cl1_leveling:
            logger.info("In CL1 leveling, mark scanning device as solved")
            self._solved_map_event.add("is_scanning_device")
            return True

        self.device.click(grid)
        with self.config.temporary(STORY_ALLOW_SKIP=False):
            result = self.wait_until_walk_stable(walk_out_of_step=False, confirm_timer=Timer(1.5, count=4))
        self.os_auto_search_run()
        if "event" in result:
            self._solved_map_event.add("is_scanning_device")
            return True
        return False

    def _map_rescan_logging_tower(self) -> bool | None:
        grid = self._map_rescan_first_grid("is_logging_tower")
        if grid is None:
            return None

        logger.info(f"Found logging tower on {grid}")
        self.device.click(grid)
        with self.config.temporary(STORY_ALLOW_SKIP=False):
            result = self.wait_until_walk_stable(walk_out_of_step=False, confirm_timer=Timer(1.5, count=4))
        if "event" in result:
            self._solved_map_event.add("is_logging_tower")
            return True
        return False

    def _map_rescan_fleet_mechanism(self) -> bool | None:
        if not self.is_in_task_explore:
            return None

        grid = self._map_rescan_first_grid("is_fleet_mechanism")
        if grid is None:
            return None

        logger.info(f"Found fleet mechanism on {grid}")
        self.device.click(grid)
        self.wait_until_walk_stable(walk_out_of_step=False, confirm_timer=Timer(1.5, count=4))

        if self._solved_fleet_mechanism:
            logger.info("All fleet mechanism are solved")
            self.os_auto_search_run()
            self._solved_map_event.add("is_fleet_mechanism")
            return True

        logger.info("One of the fleet mechanism is solved")
        self._solved_fleet_mechanism = True
        return True

    def map_rescan_once(self, rescan_mode: RescanMode = "full") -> bool:
        """按 current 或 full 复扫当前视野或全图，并返回是否处理随机事件。"""
        result = False

        logger.hr("Map rescan current", level=2)
        self.map_data_init(map_=None)
        self.handle_info_bar()
        self.update()
        if self.map_rescan_current():
            logger.info(f"Map rescan once end, result={True}")
            return True

        if rescan_mode == "full":
            logger.hr("Map rescan full", level=2)
            self.map_init(map_=None)
            queue = self.map.layout.camera_data
            while len(queue) > 0:
                logger.hr(f"Map rescan {queue[0]}")
                queue = queue.sort_by_camera_distance(self.camera)
                self.focus_to(queue[0], swipe_limit=(6, 5))
                self.focus_to_grid_center(0.3)

                if self.map_rescan_current():
                    result = True
                    break
                queue = queue[1:]

        logger.info(f"Map rescan once end, result={result}")
        return result

    def map_rescan(self, rescan_mode: RescanMode = "full") -> bool:
        if self.zone.is_port:
            logger.info("Current zone is a port, do not need rescan")
            return False
        if self.is_cl1_enabled and not self.config.is_task_enabled("OpsiMeowfficerFarming"):
            return False

        for _ in range(5):
            if not self._solved_fleet_mechanism:
                self.fleet_set(self.config.OpsiFleet_Fleet)
            else:
                self.fleet_set(self.get_second_fleet())
            if not self.is_in_task_explore and len(self._solved_map_event):
                logger.info("Solved a map event and not in OpsiExplore, stop rescan")
                logger.attr("Solved_map_event", self._solved_map_event)
                self.fleet_set(self.config.OpsiFleet_Fleet)
                return False
            result = self.map_rescan_once(rescan_mode=rescan_mode)
            if not result:
                logger.attr("Solved_map_event", self._solved_map_event)
                self.fleet_set(self.config.OpsiFleet_Fleet)
                return True

        logger.attr("Solved_map_event", self._solved_map_event)
        logger.warning("Too many trial on map rescan, stop")
        self.fleet_set(self.config.OpsiFleet_Fleet)
        return False
