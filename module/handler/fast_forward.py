import re
from pathlib import Path
from typing import ClassVar

from module.base.timer import Timer
from module.base.utils import color_bar_percentage
from module.handler import assets as handler_assets
from module.handler.auto_search import AutoSearchHandler
from module.logger import logger
from module.ui.switch import Switch

FAST_FORWARD = Switch("Fast_Forward", offset=(5, 5))
FAST_FORWARD.add_state("on", check_button=handler_assets.FAST_FORWARD_ON)
FAST_FORWARD.add_state("off", check_button=handler_assets.FAST_FORWARD_OFF)
FLEET_LOCK = Switch("Fleet_Lock", offset=(5, 20))
FLEET_LOCK.add_state("on", check_button=handler_assets.FLEET_LOCKED)
FLEET_LOCK.add_state("off", check_button=handler_assets.FLEET_UNLOCKED)
AUTO_SEARCH = Switch("Auto_Search", offset=(60, 20))
AUTO_SEARCH.add_state("on", check_button=handler_assets.AUTO_SEARCH_ON)
AUTO_SEARCH.add_state("on", check_button=handler_assets.AUTO_SEARCH_ON2)
AUTO_SEARCH.add_state("on", check_button=handler_assets.AUTO_SEARCH_ON3)
AUTO_SEARCH.add_state("on", check_button=handler_assets.AUTO_SEARCH_ON4)
AUTO_SEARCH.add_state("off", check_button=handler_assets.AUTO_SEARCH_OFF)
AUTO_SEARCH.add_state("off", check_button=handler_assets.AUTO_SEARCH_OFF2)
AUTO_SEARCH.add_state("off", check_button=handler_assets.AUTO_SEARCH_OFF3)
AUTO_SEARCH.add_state("off", check_button=handler_assets.AUTO_SEARCH_OFF4)


def map_files(event):
    """返回 ./campaign/<event> 下的地图文件名，例如 ['sp1', 'sp2', 'sp3']。"""
    folder = f"./campaign/{event}"

    if not Path(folder).exists():
        logger.warning(f"Map file folder: {folder} does not exist, can not get map files")
        return []

    files = []
    for path in Path(folder).iterdir():
        if path.suffix != ".py":
            continue
        name = path.stem
        if name == "campaign_base":
            continue
        files.append(name)
    return files


def to_map_input_name(name: str) -> str:
    """转成用户输入格式：campaign_7_2 → 7-2，d3 → D3。"""
    name = re.sub(r"[ \t\n]", "", name).lower()
    res = re.match(r"([a-zA-Z])+[- ]+(\d+)", name)
    if res:
        name = f"{res.group(1)}{res.group(2)}"
    # 先转回大写，便于移除战役前缀。
    name = str(name).upper()
    return name.replace("CAMPAIGN_", "").replace("_", "-")


def to_map_file_name(name: str) -> str:
    """转成地图文件名：7-2 → campaign_7_2，D3 → d3。"""
    name = str(name).lower()
    name = re.sub(r"[ \t\n]", "", name).lower()
    res = re.match(r"([a-zA-Z])+[- ]+(\d+)", name)
    if res:
        name = f"{res.group(1)}{res.group(2)}"
    if name and name[0].isdigit():
        name = "campaign_" + name.replace("-", "_")
    return name


class FastForwardHandler(AutoSearchHandler):
    map_clear_percentage = 0.0
    map_achieved_star_1 = False
    map_achieved_star_2 = False
    map_achieved_star_3 = False
    map_is_100_percent_clear = False
    map_is_3_stars = False
    map_is_threat_safe = False
    map_has_clear_mode = False
    map_is_clear_mode = False  # Clear mode 即旧称 fast forward。
    map_is_auto_search = False
    map_is_2x_book = False

    STAGE_INCREASE: ClassVar[tuple[str, ...]] = (
        """
        1-1 > 1-2 > 1-3 > 1-4
        > 2-1 > 2-2 > 2-3 > 2-4
        > 3-1 > 3-2 > 3-3 > 3-4
        > 4-1 > 4-2 > 4-3 > 4-4
        > 5-1 > 5-2 > 5-3 > 5-4
        > 6-1 > 6-2 > 6-3 > 6-4
        > 7-1 > 7-2 > 7-3 > 7-4
        > 8-1 > 8-2 > 8-3 > 8-4
        > 9-1 > 9-2 > 9-3 > 9-4
        > 10-1 > 10-2 > 10-3 > 10-4
        > 11-1 > 11-2 > 11-3 > 11-4
        > 12-1 > 12-2 > 12-3 > 12-4
        > 13-1 > 13-2 > 13-3 > 13-4
        > 14-1 > 14-2 > 14-3 > 14-4
        > 15-1 > 15-2 > 15-3 > 15-4
        > 16-1 > 16-2 > 16-3 > 16-4
        """,
        "A1 > A2 > A3",
        "B1 > B2 > B3",
        "C1 > C2 > C3",
        "D1 > D2 > D3",
        "SP1 > SP2 > SP3 > SP4 > SP5",
        "T1 > T2 > T3 > T4 > T5 > T6",
        "HT1 > HT2 > HT3 > HT4 > HT5 > HT6",
    )
    map_fleet_checked = False

    def map_get_info(self):
        self.map_clear_percentage = self.get_map_clear_percentage()
        self.map_achieved_star_1 = self._is_map_star_active(handler_assets.MAP_STAR_1)
        self.map_achieved_star_2 = self._is_map_star_active(handler_assets.MAP_STAR_2)
        self.map_achieved_star_3 = self._is_map_star_active(handler_assets.MAP_STAR_3)
        self.map_is_100_percent_clear = self.map_clear_percentage > 0.95
        self.map_is_3_stars = self.map_achieved_star_1 and self.map_achieved_star_2 and self.map_achieved_star_3
        self.map_is_threat_safe = self.appear(handler_assets.MAP_GREEN, offset=(20, 20))
        if self.config.Campaign_Name.lower() == "sp":
            # SP 无法检测清理模式，只能以自律寻敌按钮代替；玩家手动关闭后 Alas 无法重新启用。
            self.map_has_clear_mode = AUTO_SEARCH.appear(main=self)
        else:
            self.map_has_clear_mode = self.map_is_100_percent_clear and FAST_FORWARD.appear(main=self)

        if self.map_achieved_star_1:
            # Boss 刷新前剧情，对应 chapter_template.lua 中的 "story_refresh_boss"。
            self.config.MAP_HAS_MAP_STORY = False
        self.config.MAP_CLEAR_ALL_THIS_TIME = bool(
            self.config.STAR_REQUIRE_3
            and not getattr(self, f"map_achieved_star_{self.config.STAR_REQUIRE_3}")
            and (self.config.StopCondition_MapAchievement in ["map_3_stars", "threat_safe"])
        )

        self.map_show_info()

    def map_show_info(self):
        logger.attr("MAP_CLEAR_ALL_THIS_TIME", self.config.MAP_CLEAR_ALL_THIS_TIME)
        names = [
            "map_achieved_star_1",
            "map_achieved_star_2",
            "map_achieved_star_3",
            "map_is_100_percent_clear",
            "map_is_3_stars",
            "map_is_threat_safe",
            "map_has_clear_mode",
        ]
        strip = ["map", "achieved", "is", "has"]
        log_names = ["_".join([x for x in name.split("_") if x not in strip]) for name in names]
        enabled_log_names = [
            log_name for log_name, attr_name in zip(log_names, names, strict=True) if getattr(self, attr_name)
        ]
        text = ", ".join(enabled_log_names)
        text = f"{int(self.map_clear_percentage * 100)}%, " + text
        logger.attr("Map_info", text)
        logger.attr("StopCondition_MapAchievement", self.config.StopCondition_MapAchievement)

    def handle_fast_forward(self):
        if not self.map_has_clear_mode:
            self.map_is_clear_mode = False
            self.map_is_auto_search = False
            self.map_is_2x_book = False
            return False

        if self.config.Campaign_UseClearMode:
            self.config.MAP_HAS_AMBUSH = False
            self.config.MAP_HAS_FLEET_STEP = False
            self.config.MAP_HAS_MOVABLE_ENEMY = False
            self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY = False
            self.config.MAP_HAS_PORTAL = False
            self.config.MAP_HAS_LAND_BASED = False
            self.config.MAP_HAS_MAZE = False
            self.config.MAP_HAS_FORTRESS = False
            self.config.MAP_HAS_BOUNCING_ENEMY = False
            self.config.MAP_HAS_DECOY_ENEMY = False
            self.map_is_clear_mode = True
            if self.config.MAP_CLEAR_ALL_THIS_TIME:
                logger.info("MAP_CLEAR_ALL_THIS_TIME does not work with auto search, disable auto search temporarily")
                self.map_is_auto_search = False
            else:
                self.map_is_auto_search = self.config.Campaign_UseAutoSearch
            self.map_is_2x_book = self.config.Campaign_Use2xBook
        else:
            # 禁用快速前进时，是否存在伏击由地图配置决定。
            self.map_is_clear_mode = False
            self.map_is_auto_search = False
            self.map_is_2x_book = False

        state = "on" if self.config.Campaign_UseClearMode else "off"
        changed = FAST_FORWARD.set(state, main=self)
        if changed:
            self.map_wait_auto_search()
        return changed

    def _is_map_star_active(self, button):
        return self.image_color_count(button, color=(250, 232, 140), threshold=180, count=35)

    def handle_map_fleet_lock(self, enable=None):
        """enable 为 None 时使用 Campaign_UseFleetLock。"""
        # 舰队锁定依赖按钮是否出现在地图上，而不是地图状态。
        # 已经在地图内时不会再显示地图状态。
        if not FLEET_LOCK.appear(main=self):
            logger.info("No fleet lock option.")
            return False

        if enable is None:
            enable = self.config.Campaign_UseFleetLock
        state = "on" if enable else "off"
        return FLEET_LOCK.set(state, main=self)

    def map_wait_auto_search(self):
        """启用清理模式后等待自律寻敌按钮完成出现动画。"""
        timeout = Timer(1, count=3).start()
        for _ in self.loop():
            state = AUTO_SEARCH.get(main=self)
            logger.attr("AUTO_SEARCH", state)
            if state != "unknown":
                return True
            if timeout.reached():
                # 有些地图有清理模式，但没有自律寻敌。
                logger.info("map wait auto search timeout")
                return False
        return False

    def handle_auto_search(self):
        """页面进入：MAP_PREPARATION。"""
        if not AUTO_SEARCH.appear(main=self):
            logger.info("No auto search option.")
            self.map_is_auto_search = False
            return False

        state = "on" if self.map_is_auto_search else "off"
        return AUTO_SEARCH.set(state, main=self)

    def handle_auto_search_setting(self):
        """页面进入：FLEET_PREPARATION。"""
        if not self.map_is_auto_search:
            return False

        logger.info("Auto search setting")
        self.fleet_preparation_sidebar_ensure(3)
        self.auto_search_setting_ensure(self.config.Fleet_FleetOrder)
        if self.config.submarine:
            self.auto_search_setting_ensure(self.config.Submarine_AutoSearchMode)
        return True

    @property
    def is_call_submarine_at_boss(self):
        return self.config.submarine and self.config.Submarine_Mode in ["boss_only", "hunt_and_boss"]

    def handle_auto_submarine_call_disable(self):
        """页面进入：FLEET_PREPARATION。"""
        if self.map_fleet_checked:
            return False
        if not self.is_call_submarine_at_boss:
            return False
        # 2025-09-22 起，舰队职责设置需解锁清理模式后才可用。
        if not self.map_is_clear_mode:
            logger.warning("Can not set submarine call because auto search not available, assuming disabled")
            logger.warning(
                "Please do the followings: goto any stage -> auto search role -> set submarine role to standby"
            )
            logger.warning("If you already did, ignore this warning")
            return False

        logger.info("Disable auto submarine call")
        self.fleet_preparation_sidebar_ensure(3)
        self.auto_search_setting_ensure("sub_standby")
        return True

    def handle_auto_search_continue(self):
        """覆盖通用继续处理，以便同步双倍书设置。"""
        if self.appear(handler_assets.AUTO_SEARCH_MENU_CONTINUE, offset=self._auto_search_menu_offset, interval=2):
            self.map_is_2x_book = self.config.Campaign_Use2xBook
            self.handle_2x_book_setting(mode="auto")
            if self.appear_then_click(handler_assets.AUTO_SEARCH_MENU_CONTINUE, offset=self._auto_search_menu_offset):
                self.interval_reset(handler_assets.AUTO_SEARCH_MENU_CONTINUE)
            else:
                # 设置双倍书后继续按钮可能已经消失。
                pass
            return True
        return False

    def get_map_clear_percentage(self):
        """在 MAP_PREPARATION 返回 0～1 的地图清理比例。"""
        percent = color_bar_percentage(
            self.device.image, area=handler_assets.MAP_CLEAR_PERCENTAGE.area, prev_color=(231, 170, 82)
        )
        if self.config.MAP_CLEAR_PERCENTAGE_SHORT:
            percent *= 1.4
        return percent

    def campaign_name_increase(self, name):
        """把 6-1、a1 或 campaign_6_1 推进到大写的下一关；无法推进时返回原名。"""
        stage_increase = list(self.STAGE_INCREASE)
        if self.config.STAGE_INCREASE_AB:
            stage_increase = ["A1 > A2 > A3 > B1 > B2 > B3", *stage_increase]
        custom = self.config.STAGE_INCREASE_CUSTOM
        if custom:
            if isinstance(custom, str):
                custom = [custom]
            stage_increase = custom + stage_increase

        name = to_map_input_name(name)
        for raw_increase in stage_increase:
            increase = [i.strip(" \t\r\n") for i in raw_increase.split(">")]
            if name in increase:
                index = increase.index(name) + 1
                if index < len(increase):
                    new = increase[index]
                    # 主线文件名与用户输入格式不同，且默认所有主线关卡都存在。
                    if self.config.Campaign_Event == "campaign_main":
                        return new
                    existing = map_files(self.config.Campaign_Event)
                    logger.info(f"Existing files: {existing}")
                    if new.lower() in existing:
                        return new
                    logger.info(f"Stage increase reach end, new map {new} does not exist")
                    return name
                logger.info("Stage increase reach end")
                return name

        return name

    def triggered_map_stop(self):
        match self.config.StopCondition_MapAchievement:
            case "100_percent_clear":
                return self.map_is_100_percent_clear
            case "map_3_stars":
                return self.map_is_100_percent_clear and self.map_is_3_stars
            case "threat_safe_without_3_stars":
                return self.map_is_100_percent_clear and self.map_is_threat_safe
            case "threat_safe":
                return self.map_is_100_percent_clear and self.map_is_3_stars and self.map_is_threat_safe
            case _:
                return False

    def handle_map_stop(self):
        """达到停止条件后禁用当前任务或推进关卡配置。"""
        if self.config.StopCondition_StageIncrease:
            prev_stage = to_map_input_name(self.config.Campaign_Name)
            next_stage = self.campaign_name_increase(prev_stage)
            if next_stage != prev_stage:
                logger.info(f"Stage {prev_stage} increases to {next_stage}")
                self.config.Campaign_Name = next_stage
            else:
                logger.info(f"Stage {prev_stage} cannot increase, stop at current stage")
                self.config.Scheduler_Enable = False
        else:
            self.config.Scheduler_Enable = False

    def _set_2x_book_status(self, status, check_button, box_button, skip_first_screenshot=True):
        """把双倍书设为 on 或 off；每 3 秒重试，超过 3 次或页面无此设置时返回 False。"""
        confirm_timer = Timer(0.3, count=1).start()
        clicked_threshold = 0
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if clicked_threshold > 3:
                break

            if self.appear(check_button, offset=self._auto_search_menu_offset, interval=3):
                box_button.load_offset(check_button)
                enabled = self.image_color_count(box_button.button, color=(156, 255, 82), threshold=221, count=20)
                if (status == "on" and enabled) or (status == "off" and not enabled):
                    return True
                if (status == "on" and not enabled) or (status == "off" and enabled):
                    self.device.click(box_button)

                clicked_threshold += 1

            if not clicked_threshold and confirm_timer.reached():
                logger.info("Map do not have 2x book setting")
                return False

        logger.warning("Wait time has expired; Cannot set 2x book setting")
        return False

    def handle_2x_book_setting(self, mode="prep"):
        """mode 为 prep 时处理准备页，其他值处理自律寻敌页。"""
        if not self.map_is_clear_mode:
            return False
        if not hasattr(self, "emotion"):
            logger.info("Emotion instance not loaded, cannot handle 2x book setting")
            return False

        logger.info(f"Handling 2x book setting, mode={mode}.")
        if mode == "prep":
            book_check = handler_assets.BOOK_CHECK_PREP
            book_box = handler_assets.BOOK_BOX_PREP
        else:
            book_check = handler_assets.BOOK_CHECK_AUTO
            book_box = handler_assets.BOOK_BOX_AUTO

        state = "on" if self.map_is_2x_book else "off"
        if self._set_2x_book_status(state, book_check, book_box):
            self.emotion.map_is_2x_book = self.map_is_2x_book
        else:
            self.map_is_2x_book = False
            self.emotion.map_is_2x_book = self.map_is_2x_book

        self.handle_info_bar()
        return True

    def handle_2x_book_popup(self):
        return self.appear(handler_assets.BOOK_POPUP_CHECK, offset=(20, 20)) and self.handle_popup_confirm("2X_BOOK")

    def handle_submarine_support_popup(self):
        """供第 16 章潜艇基类覆盖；默认有意不处理。"""
        return False

    def handle_map_walk_speedup(self, skip_first_screenshot=True):
        """只负责开启地图步速，已开启即返回，不会主动关闭。"""
        if not self.config.MAP_HAS_WALK_SPEEDUP:
            return False

        timeout = Timer(2, count=4).start()
        interval = Timer(1, count=2)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.image_color_count(handler_assets.MAP_WALK_SPEEDUP, color=(132, 255, 148), threshold=180, count=50):
                logger.attr("Walk_Speedup", "on")
                return True
            if timeout.reached():
                logger.warning("Wait time has expired; Cannot set map walk speedup")
                return False

            if interval.reached():
                self.device.click(handler_assets.MAP_WALK_SPEEDUP)
                interval.reset()
                continue
        return False
