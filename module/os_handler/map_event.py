from typing import TYPE_CHECKING, override

from module.base.timer import Timer
from module.combat.assets import GET_ITEMS_1, GET_ITEMS_2, GET_ITEMS_3
from module.exception import CampaignEnd
from module.handler.assets import POPUP_CANCEL, POPUP_CONFIRM
from module.logger import logger
from module.os.assets import GLOBE_GOTO_MAP
from module.os_handler import assets as os_assets
from module.os_handler.enemy_searching import EnemySearchingHandler
from module.ui.assets import BACK_ARROW
from module.ui.switch import Switch

if TYPE_CHECKING:
    from module.base.base import ModuleBase


class FleetLockSwitch(Switch):
    @override
    def handle_additional(self, _main: ModuleBase) -> bool:
        # 上一个已清理海域的自动搜索奖励有时会延迟弹出。
        if not isinstance(_main, MapEventHandler):
            return False
        return _main.appear_then_click(os_assets.AUTO_SEARCH_REWARD, offset=(50, 50), interval=3)


fleet_lock = FleetLockSwitch("Fleet_Lock", offset=(10, 120))
fleet_lock.add_state("on", check_button=os_assets.OS_FLEET_LOCKED)
fleet_lock.add_state("off", check_button=os_assets.OS_FLEET_UNLOCKED)

_MAP_GET_ITEM_BUTTONS = (
    GET_ITEMS_1,
    GET_ITEMS_2,
    GET_ITEMS_3,
    os_assets.GET_ADAPTABILITY,
    os_assets.GET_MEOWFFICER_ITEMS_1,
    os_assets.GET_MEOWFFICER_ITEMS_2,
)
_MAP_EVENT_HANDLERS = (
    ("handle_map_get_items", "map_get_items"),
    ("handle_os_game_tips", "os_game_tips"),
    ("handle_map_archives", "map_archives"),
    ("handle_guild_popup_cancel", "guild_popup_cancel"),
    ("handle_ash_popup", "ash_popup"),
    ("handle_urgent_commission", "urgent_commission"),
    ("handle_story_skip", "story_skip"),
)


class MapEventHandler(EnemySearchingHandler):
    ash_popup_canceled = False

    def handle_map_get_items(self, interval: int = 2) -> bool:
        if self.is_in_map():
            return False

        for button in _MAP_GET_ITEM_BUTTONS:
            if self.appear(button, interval=interval):
                logger.info(f"{button} -> {os_assets.CLICK_SAFE_AREA}")
                self.device.click(os_assets.CLICK_SAFE_AREA)
                return True

        return False

    def handle_map_archives(self) -> bool:
        if self.appear(os_assets.MAP_ARCHIVES, interval=5):
            logger.info(f"{os_assets.MAP_ARCHIVES} -> {os_assets.CLICK_SAFE_AREA}")
            self.device.click(os_assets.CLICK_SAFE_AREA)
            return True
        return self.appear_then_click(os_assets.MAP_WORLD, offset=(20, 20), interval=5)

    def handle_os_game_tips(self) -> bool:
        # 首次开启自动搜索时关闭游戏提示。
        return self.appear_then_click(os_assets.OS_GAME_TIPS, offset=(20, 20), interval=3)

    def handle_ash_popup(self) -> bool:
        name = "ASH"
        # 2021-12-09 起 Ash 弹窗不再显示红字，改用 `Ashes Coordinates` 文字识别。
        if (
            self.appear(POPUP_CONFIRM, offset=self._popup_offset)
            and self.appear(POPUP_CANCEL, offset=self._popup_offset, interval=2)
            and self.appear(os_assets.ASH_POPUP_CHECK, offset=(20, 20))
        ):
            POPUP_CANCEL.name = POPUP_CANCEL.name + "_" + name
            self.device.click(POPUP_CANCEL)
            POPUP_CANCEL.name = POPUP_CANCEL.name[: -len(name) - 1]
            self.ash_popup_canceled = True
            return True
        return False

    def handle_map_event(self) -> str:
        """返回已处理的事件名；没有事件时返回空字符串。"""
        for handler, event in _MAP_EVENT_HANDLERS:
            if getattr(self, handler)():
                return event

        return ""

    _os_in_map_confirm_timer = Timer(1.5, count=3)

    def handle_os_in_map(self) -> bool:
        """返回当前是否在大世界地图内且已稳定确认。"""
        if self.is_in_map():
            return bool(self._os_in_map_confirm_timer.reached())
        self._os_in_map_confirm_timer.reset()
        return False

    def ensure_no_map_event(self) -> None:
        self._os_in_map_confirm_timer.reset()

        for _ in self.loop():
            if self.handle_map_event():
                continue
            if self.handle_os_in_map():
                break

    def os_auto_search_quit(self) -> bool:
        """退出自动搜索，并返回当前地图是否已清空。"""
        confirm_timer = Timer(1.2, count=3).start()
        cleared = False
        for _ in self.loop():
            if self.appear(os_assets.AUTO_SEARCH_REWARD, offset=(50, 50), interval=2):
                if self.ensure_no_info_bar():
                    cleared = True
                self.device.click(os_assets.AUTO_SEARCH_REWARD)
                self.interval_reset(
                    [
                        os_assets.AUTO_SEARCH_REWARD,
                        os_assets.AUTO_SEARCH_OS_MAP_OPTION_ON,
                        os_assets.AUTO_SEARCH_OS_MAP_OPTION_OFF,
                        os_assets.AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED,
                    ]
                )
                confirm_timer.reset()
                continue
            if self.handle_map_event():
                confirm_timer.reset()
                continue
            if self.appear_then_click(GLOBE_GOTO_MAP, offset=(20, 20), interval=2):
                # 点击自动搜索奖励后，有时会因为重复点击或点到地图外而误入全球地图。
                confirm_timer.reset()
                continue
            # 偶发误入仓库时直接退出；这里不能继承 StorageHandler。
            # STORAGE_CHECK 有重名，这里明确使用 os_handler/STORAGE_CHECK。
            if self.appear(os_assets.STORAGE_CHECK, offset=(20, 20), interval=5):
                logger.info(f"{os_assets.STORAGE_CHECK} -> {BACK_ARROW}")
                self.device.click(BACK_ARROW)
                confirm_timer.reset()
                continue

            if self.is_in_map():
                if confirm_timer.reached():
                    break
            else:
                confirm_timer.reset()

        return cleared

    def handle_os_auto_search_map_option(self, *, enable: bool | None = True) -> bool:
        """enable 为 None 时不切换；搜索结束时退出并抛出 CampaignEnd。"""
        if (
            self.match_template_color(os_assets.AUTO_SEARCH_OS_MAP_OPTION_OFF, offset=(5, 120))
            and self.info_bar_count() >= 2
        ):
            self.device.screenshot_interval_set()
            self.os_auto_search_quit()
            raise CampaignEnd
        if (
            self.match_template_color(os_assets.AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED, offset=(5, 120))
            and self.info_bar_count() >= 2
        ):
            self.device.screenshot_interval_set()
            self.os_auto_search_quit()
            raise CampaignEnd
        if self.appear(os_assets.AUTO_SEARCH_REWARD, offset=(50, 50)):
            self.device.screenshot_interval_set()
            if self.os_auto_search_quit():
                # 当前地图没有更多道具。
                raise CampaignEnd
            # 自动搜索已停止，但地图尚未清空。
            return True

        if enable is None:
            pass
        elif enable:
            if self.match_template_color(os_assets.AUTO_SEARCH_OS_MAP_OPTION_OFF, offset=(5, 120), interval=3):
                self.device.click(os_assets.AUTO_SEARCH_OS_MAP_OPTION_OFF)
                self.interval_reset(os_assets.AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED)
                return True
            # 游戏客户端偶尔会让 AUTO_SEARCH_OS_MAP_OPTION_OFF 灰显，但按钮仍然可用。
            if self.match_template_color(os_assets.AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED, offset=(5, 120), interval=3):
                self.device.click(os_assets.AUTO_SEARCH_OS_MAP_OPTION_OFF_DISABLED)
                self.interval_reset(os_assets.AUTO_SEARCH_OS_MAP_OPTION_OFF)
                return True
        elif self.match_template_color(os_assets.AUTO_SEARCH_OS_MAP_OPTION_ON, offset=(5, 120), interval=3):
            self.device.click(os_assets.AUTO_SEARCH_OS_MAP_OPTION_ON)
            return True

        return False

    def handle_os_map_fleet_lock(self, *, enable: bool | None = None) -> bool:
        # 舰队锁定依赖按钮是否出现在地图上，而不是地图状态。
        # 已经在地图内时不会再显示地图状态。
        if not fleet_lock.appear(main=self):
            logger.info("No fleet lock option.")
            return False

        if enable is None:
            enable = self.config.Campaign_UseFleetLock
        state = "on" if enable else "off"
        return fleet_lock.set(state, main=self)
