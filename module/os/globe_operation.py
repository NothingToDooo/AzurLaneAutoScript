from typing import TYPE_CHECKING, Literal

from module.base.timer import Timer
from module.base.utils import area_pad
from module.device.control_options import SwipeVectorOptions
from module.logger import logger
from module.os import assets as os_assets
from module.os_handler.action_point import ActionPointHandler
from module.os_handler.assets import AUTO_SEARCH_REWARD
from module.os_handler.port import PORT_CHECK
from module.ui.assets import BACK_ARROW

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.base.button import Button
    from module.os.globe_zone import Zone
    from module.os_handler.action_point import ActionPointZoneType

type ZoneType = Literal["DANGEROUS", "SAFE", "OBSCURE", "ABYSSAL", "STRONGHOLD", "ARCHIVE"]

_ZONE_TYPE_BY_NAME: dict[str, ZoneType] = {
    "DANGEROUS": "DANGEROUS",
    "SAFE": "SAFE",
    "OBSCURE": "OBSCURE",
    "ABYSSAL": "ABYSSAL",
    "STRONGHOLD": "STRONGHOLD",
    "ARCHIVE": "ARCHIVE",
}

ZONE_TYPES = [
    os_assets.ZONE_DANGEROUS,
    os_assets.ZONE_SAFE,
    os_assets.ZONE_OBSCURE,
    os_assets.ZONE_ABYSSAL,
    os_assets.ZONE_STRONGHOLD,
    os_assets.ZONE_ARCHIVE,
]
ZONE_SELECT = [
    os_assets.SELECT_DANGEROUS,
    os_assets.SELECT_SAFE,
    os_assets.SELECT_OBSCURE,
    os_assets.SELECT_ABYSSAL,
    os_assets.SELECT_STRONGHOLD,
    os_assets.SELECT_ARCHIVE,
]
ASSETS_PINNED_ZONE = [*ZONE_TYPES, os_assets.ZONE_ENTRANCE, os_assets.ZONE_SWITCH, os_assets.ZONE_PINNED]


class OSExploreError(Exception):
    pass


class RewardUncollectedError(Exception):
    pass


class GlobeOperation(ActionPointHandler):
    _zone_unpin_interval = Timer(0.5)

    def is_in_globe(self) -> bool:
        return self.appear(os_assets.GLOBE_GOTO_MAP, offset=(20, 20))

    def get_zone_pinned(self) -> Button | None:
        for zone in ZONE_TYPES:
            if self.appear(zone, offset=(20, 20)):
                for button in ASSETS_PINNED_ZONE:
                    button.load_offset(zone)

                return zone

        return None

    def is_zone_pinned(self) -> bool:
        return self.get_zone_pinned() is not None

    @staticmethod
    def pinned_to_name(button: Button) -> str:
        return button.name.split("_")[1]

    def get_zone_pinned_name(self) -> ZoneType | Literal[""]:
        """返回钉选海域类型；未钉选时返回空字符串。"""
        pinned = self.get_zone_pinned()
        if pinned is not None:
            name = self.pinned_to_name(pinned)
            return _ZONE_TYPE_BY_NAME.get(name, "")
        return ""

    @staticmethod
    def _normalize_zone_types(types: ZoneType | Sequence[ZoneType]) -> Sequence[ZoneType]:
        if isinstance(types, str):
            zone_type = _ZONE_TYPE_BY_NAME.get(types)
            if zone_type is None:
                message = f"Unknown zone type: {types}"
                raise ValueError(message)
            return (zone_type,)
        return types

    def handle_zone_pinned(self) -> bool:
        if not self._zone_unpin_interval.reached():
            return False

        if self.is_zone_pinned():
            # 点击不会取消区域固定，滑动才会。
            self.device.swipe_vector(
                (50, -50),
                SwipeVectorOptions(
                    box=area_pad(os_assets.ZONE_PINNED.area, pad=-80),
                    random_range=(-10, -10, 10, 10),
                    padding=0,
                    name="PINNED_DISABLE",
                ),
            )
            self._zone_unpin_interval.reset()
            return True

        return False

    def ensure_no_zone_pinned(self) -> None:
        confirm_timer = Timer(1, count=2).start()
        for _ in self.loop():
            if self.handle_zone_pinned():
                confirm_timer.reset()
            elif confirm_timer.reached():
                break

    def zone_has_switch(self) -> bool:
        """海域切换图标会旋转，旧版白块检测不稳定。

        2021-07-15 图标缩小并新增 Change Zone 文本后，改为检测文字。
        """
        return self.appear(os_assets.ZONE_SWITCH, offset=(5, 5))

    _zone_select_offset = (20, 200)
    _zone_select_similarity = 0.75

    def get_zone_select(self) -> list[Button]:
        # 降低阈值到 0.75。
        # 原因不明，但字体有时会不同。
        return [
            select
            for select in ZONE_SELECT
            if self.appear(select, offset=self._zone_select_offset, similarity=self._zone_select_similarity)
        ]

    def is_in_zone_select(self) -> bool:
        return len(self.get_zone_select()) > 0

    def ensure_zone_select_expanded(self) -> list[Button]:
        record = 0
        for _ in range(5):
            selection = self.get_zone_select()
            if len(selection) == record and record > 0:
                return selection

            record = len(selection)
            self.device.screenshot()

        logger.warning("Failed to ensure zone selection expanded, assume expanded")
        return self.get_zone_select()

    def zone_select_enter(self) -> None:
        """从海域钉选信息进入海域类型选择页。"""
        self.ui_click(
            os_assets.ZONE_SWITCH,
            appear_button=self.is_zone_pinned,
            check_button=self.is_in_zone_select,
            skip_first_screenshot=True,
        )

    def zone_select_execute(self, button: Button) -> None:
        """在海域类型选择页选择 SELECT_*，完成后返回海域钉选信息。"""
        logger.info(f"Zone select: {button}")
        for _ in self.loop():
            # 结束。
            if self.is_zone_pinned():
                break
            if self.appear_then_click(
                button, offset=self._zone_select_offset, similarity=self._zone_select_similarity, interval=5
            ):
                continue

    def zone_type_select(self, types: ZoneType | Sequence[ZoneType] = ("SAFE", "DANGEROUS")) -> bool:
        """按调用方 types 的顺序选择海域类型；允许 DANGEROUS、SAFE、OBSCURE、ABYSSAL、STRONGHOLD、ARCHIVE。

        无匹配时回退到 SAFE、DANGEROUS；页面保持在海域钉选信息。
        """
        if not self.zone_has_switch():
            logger.info("Zone has no type to select, skip")
            return True

        selected_types = self._normalize_zone_types(types)

        pinned = self.get_zone_pinned_name()
        if pinned in selected_types:
            logger.info(f"Already selected at {pinned}")
            return True

        for _ in range(3):
            success, selected_types = self._zone_type_select_once(selected_types)
            if success:
                return True

        logger.warning("Failed to select zone type after 3 trial")
        return False

    @staticmethod
    def _zone_select_get_button(selection: Sequence[Button], types: Sequence[ZoneType]) -> Button | None:
        for raw_type in types:
            button_name = "SELECT_" + raw_type
            for button in selection:
                if button_name == button.name:
                    return button
        return None

    def _zone_select_get_button_with_fallback(
        self,
        selection: Sequence[Button],
        types: Sequence[ZoneType],
    ) -> tuple[Button, Sequence[ZoneType]]:
        button = self._zone_select_get_button(selection, types)
        if button is not None:
            return button, types

        logger.warning("No such zone type to select, fallback to default")
        fallback: tuple[ZoneType, ...] = ("SAFE", "DANGEROUS")
        button = self._zone_select_get_button(selection, fallback)
        if button is None:
            message = "Zone selection has neither SAFE nor DANGEROUS"
            raise RuntimeError(message)
        return button, fallback

    def _zone_type_select_once(self, types: Sequence[ZoneType]) -> tuple[bool, Sequence[ZoneType]]:
        self.zone_select_enter()
        selection = self.ensure_zone_select_expanded()
        logger.attr("Zone_selection", selection)

        button, types = self._zone_select_get_button_with_fallback(selection, types)
        self.zone_select_execute(button)
        return self.pinned_to_name(button) == self.get_zone_pinned_name(), types

    def zone_has_safe(self) -> bool:
        """优先选择 SAFE，否则选择必定存在的 DANGEROUS；页面保持在钉选信息。"""
        if self.get_zone_pinned_name() == "SAFE":
            return True
        if self.zone_has_switch():
            self.zone_select_enter()
            flag = os_assets.SELECT_SAFE in self.ensure_zone_select_expanded()
            button = os_assets.SELECT_SAFE if flag else os_assets.SELECT_DANGEROUS
            self.zone_select_execute(button)
            return flag
        # 没有 zone_switch，已在 DANGEROUS。
        return False

    def os_globe_goto_map(self, *, skip_first_screenshot: bool = True) -> None:
        """从全局地图返回区域地图。"""
        self.ui_click(
            os_assets.GLOBE_GOTO_MAP,
            check_button=self.is_in_map,
            offset=(20, 20),
            retry_wait=3,
            skip_first_screenshot=skip_first_screenshot,
        )

    def os_map_goto_globe(self, *, unpin: bool = True) -> None:
        """从区域地图进入全局地图；unpin 控制是否关闭已有钉选信息。"""
        click_count = 0
        for _ in self.loop():
            # 结束。
            if self.is_in_globe():
                break

            handled, click_count = self._os_map_goto_globe_handle_entry(click_count)
            if handled:
                continue

        self._os_map_goto_globe_handle_pinned(unpin=unpin)

    def _os_map_goto_globe_handle_entry(self, click_count: int) -> tuple[bool, int]:
        handled, click_count = self._os_map_goto_globe_click_button(click_count)
        if handled:
            return True, click_count
        if self._os_map_goto_globe_click_fog():
            return True, click_count
        if self._os_map_goto_globe_handle_popup():
            return True, click_count
        return False, click_count

    def _os_map_goto_globe_click_button(self, click_count: int) -> tuple[bool, int]:
        if not self.appear_then_click(os_assets.MAP_GOTO_GLOBE, offset=(200, 5), interval=5):
            return False, click_count

        # 只是为了初始化 MAP_GOTO_GLOBE_FOG 的间隔计时器。
        self.appear(os_assets.MAP_GOTO_GLOBE_FOG, interval=5)
        self.interval_reset(os_assets.MAP_GOTO_GLOBE_FOG)
        click_count += 1
        if click_count >= 5:
            # 存在未领取区域探索奖励时，AL 不允许离开。
            logger.warning("Unable to goto globe, there might be uncollected zone exploration rewards preventing exit")
            raise RewardUncollectedError
        return True, click_count

    def _os_map_goto_globe_click_fog(self) -> bool:
        if self.appear_then_click(os_assets.MAP_GOTO_GLOBE_FOG, interval=5):
            # 只会在据点遇到；即使地图内仍有探索奖励，AL 也不会阻止区域退出。
            self.interval_reset(os_assets.MAP_GOTO_GLOBE)
            return True
        return False

    def _os_map_goto_globe_handle_popup(self) -> bool:
        if self.handle_map_event():
            return True
        # 误入港口。
        if self.appear(PORT_CHECK, offset=(20, 20), interval=5):
            logger.info(f"Page switch: {PORT_CHECK} -> {BACK_ARROW}")
            self.device.click(BACK_ARROW)
            return True
        # 弹窗：AUTO_SEARCH_REWARD 出现较慢。
        if self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=5):
            return True
        # 离开当前区域时，猫指挥搜索和潜艇可能被终止；搜索奖励会在进入新区后出现。
        return self.handle_popup_confirm("GOTO_GLOBE")

    def _os_map_goto_globe_handle_pinned(self, *, unpin: bool) -> None:
        confirm_timer = Timer(1, count=2).start()
        unpinned = 0
        for _ in self.loop():
            if unpin:
                if self.handle_zone_pinned():
                    unpinned += 1
                    confirm_timer.reset()
                elif unpinned and confirm_timer.reached():
                    break
            elif self.is_zone_pinned():
                break

    def globe_enter(self, zone: Zone) -> None:
        """从钉选信息进入区域地图；海域未解锁时抛出 OSExploreError。"""
        click_timer = Timer(10)
        click_count = 0
        pinned = None
        for _ in self.loop():
            if pinned is None:
                pinned = self.get_zone_pinned_name()

            # 结束。
            if self.is_in_map():
                break

            clicked, click_count = self._globe_enter_click_zone(zone, click_timer, click_count)
            if clicked:
                continue
            if self._globe_enter_handle_blocker(zone, pinned, click_timer):
                continue

    def _globe_enter_click_zone(self, zone: Zone, click_timer: Timer, click_count: int) -> tuple[bool, int]:
        if not self.is_zone_pinned():
            return False, click_count
        if self.appear(os_assets.ZONE_LOCKED, offset=(20, 20)):
            logger.warning(f"Zone {zone} locked, neighbouring zones may not have been explored")
            raise OSExploreError
        if click_count > 5:
            logger.warning(f"Unable to enter zone {zone}, neighbouring zones may not have been explored")
            raise OSExploreError
        if not click_timer.reached():
            return False, click_count

        self.device.click(os_assets.ZONE_ENTRANCE)
        click_timer.reset()
        return True, click_count + 1

    def _globe_enter_handle_blocker(
        self,
        zone: Zone,
        pinned: ActionPointZoneType | Literal[""],
        click_timer: Timer,
    ) -> bool:
        if self.handle_action_point(zone=zone, pinned=pinned or None):
            click_timer.clear()
            return True
        if self.handle_map_event():
            return True
        if self.handle_popup_confirm("GLOBE_ENTER"):
            return True
        # 游戏 bug：上一个已清理区域的 AUTO_SEARCH_REWARD 会弹出。
        return self.appear_then_click(AUTO_SEARCH_REWARD, offset=(50, 50), interval=3)
