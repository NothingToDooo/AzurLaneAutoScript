from module.base.decorator import del_cached_property
from module.base.timer import Timer
from module.exception import CampaignEnd
from module.handler.assets import IN_MAP, MAP_ENEMY_SEARCHING
from module.handler.info_handler import InfoHandler
from module.handler.map_transition_ui import STANDARD_MAP_TRANSITION_UI, MapTransitionUi
from module.logger import logger
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION, MAP_PREPARATION_CANCEL
from module.ui.assets import CAMPAIGN_CHECK, EVENT_CHECK, SP_CHECK

IN_STAGE_MESSAGE = "In stage."


class EnemySearchingHandler(InfoHandler):
    _map_transition_ui: MapTransitionUi = STANDARD_MAP_TRANSITION_UI
    MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD = 0.5  # 实测通常为 0.70～0.80。
    MAP_ENEMY_SEARCHING_TIMEOUT_SECOND = 5
    in_stage_timer = Timer(0.5, count=2)
    stage_entrance = None

    map_is_100_percent_clear = False  # fast_forward.py 会覆盖此状态。

    def enemy_searching_color_initial(self) -> None:
        # 供需要颜色初始化的子类覆盖。
        pass

    def enemy_searching_appear(self) -> bool:
        if not self.is_in_map():
            return False

        return MAP_ENEMY_SEARCHING.match_luma(self.device.image, offset=(5, 5))

    def handle_enemy_flashing(self) -> None:
        self.device.sleep(1.2)

    def handle_in_stage(self) -> bool:
        if self.is_in_stage():
            if self.in_stage_timer.reached():
                logger.info(IN_STAGE_MESSAGE)
                self.ensure_no_info_bar(timeout=1.2)
                raise CampaignEnd(IN_STAGE_MESSAGE)
            return False
        if self.appear(MAP_PREPARATION, offset=(20, 20)) or self.appear(FLEET_PREPARATION, offset=(20, 50)):
            self.device.click(MAP_PREPARATION_CANCEL)
        self.in_stage_timer.reset()
        return False

    def is_in_stage_page(self) -> bool:
        return any(self.appear(check, offset=(20, 20)) for check in (CAMPAIGN_CHECK, EVENT_CHECK, SP_CHECK))

    def is_stage_page_has_entrance(self) -> bool:
        """以关卡入口是否可识别判断关卡页已完成加载。"""
        try:
            campaign_extract_name_image = getattr(self, "campaign_extract_name_image", None)
            if callable(campaign_extract_name_image):
                del_cached_property(self, "_stage_image")
                del_cached_property(self, "_stage_image_gray")
                if not len(campaign_extract_name_image(self.device.image)):
                    return False
        except IndexError:
            return False

        return True

    def is_in_stage(self) -> bool:
        if not self.is_in_stage_page():
            return False
        return self._map_transition_ui.stage_page_ready(self)

    def is_in_map(self) -> bool:
        return self.appear(IN_MAP)

    @staticmethod
    def is_event_animation() -> bool:
        """供活动子类覆盖，用于识别清敌后的活动动画。"""
        return False

    @staticmethod
    def handle_auto_search_exit() -> bool:
        """供 AutoSearchHandler 覆盖；寻敌等待流程会无条件调用此钩子。"""
        return False

    @staticmethod
    def _reset_enemy_searching_timeout(timeout: Timer, *, extend: bool = False) -> None:
        if extend:
            timeout.limit = 10
        timeout.reset()

    def _handle_enemy_searching_interrupts(self, timeout: Timer, *, extend_timeout: bool) -> bool:
        if self.handle_auto_search_exit():
            self._reset_enemy_searching_timeout(timeout, extend=extend_timeout)
            return True
        if self.handle_vote_popup():
            self._reset_enemy_searching_timeout(timeout, extend=extend_timeout)
            return True
        if self.handle_story_skip():
            self.ensure_no_story()
            self._reset_enemy_searching_timeout(timeout, extend=extend_timeout)
        if self.handle_guild_popup_cancel():
            self._reset_enemy_searching_timeout(timeout, extend=extend_timeout)
            return True
        if self.handle_urgent_commission():
            self._reset_enemy_searching_timeout(timeout, extend=extend_timeout)
            return True
        return False

    def _handle_enemy_searching_animation_end(self, *, appeared: bool) -> tuple[bool, bool]:
        if self.enemy_searching_appear():
            return True, False
        if appeared:
            self.handle_enemy_flashing()
            self.device.sleep(0.3)
            self.device.screenshot()
            logger.info("Enemy searching appeared.")
            return appeared, True
        self.enemy_searching_color_initial()
        return appeared, False

    def handle_in_map_with_enemy_searching(self) -> bool:
        if not self.is_in_map():
            return False

        timeout = Timer(self.MAP_ENEMY_SEARCHING_TIMEOUT_SECOND)
        appeared = False
        while 1:
            self.device.screenshot()
            if self._map_transition_ui.event_animation_visible(self):
                continue
            if self.is_in_map():
                timeout.start()
            else:
                timeout.reset()

            # 等待寻敌动画时，关卡也可能已经结束。
            if self._map_transition_ui.handle_stage_return(self):
                return True
            # 第 16 章可能直接进入潜艇战斗。
            is_combat_loading = getattr(self, "is_combat_loading", None)
            if callable(is_combat_loading) and is_combat_loading():
                logger.warning("Entered map with is_combat_loading appeared")
                break
            if self._handle_enemy_searching_interrupts(timeout, extend_timeout=True):
                continue

            appeared, finished = self._handle_enemy_searching_animation_end(appeared=appeared)
            if finished:
                break
            if timeout.reached():
                logger.info("Enemy searching timeout.")
                break

        return True

    def handle_in_map_no_enemy_searching(self) -> bool:
        if not self.is_in_map():
            return False

        timeout = Timer(1, count=2).start()
        while 1:
            self.device.screenshot()

            if not self.is_in_map():
                timeout.reset()

            # 即使不等待寻敌动画，关卡也可能已经结束。
            if self._map_transition_ui.handle_stage_return(self):
                return True
            if self._handle_enemy_searching_interrupts(timeout, extend_timeout=False):
                continue

            if timeout.reached():
                logger.info("No enemy searching in map.")
                break

        return True
