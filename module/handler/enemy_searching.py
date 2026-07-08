from module.base.decorator import del_cached_property
from module.base.timer import Timer
from module.exception import CampaignEnd
from module.handler.assets import IN_MAP, MAP_ENEMY_SEARCHING
from module.handler.info_handler import InfoHandler
from module.logger import logger
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION, MAP_PREPARATION_CANCEL
from module.ui.assets import CAMPAIGN_CHECK, EVENT_CHECK, SP_CHECK

IN_STAGE_MESSAGE = "In stage."


class EnemySearchingHandler(InfoHandler):
    MAP_ENEMY_SEARCHING_OVERLAY_TRANSPARENCY_THRESHOLD = 0.5  # Usually (0.70, 0.80).
    MAP_ENEMY_SEARCHING_TIMEOUT_SECOND = 5
    in_stage_timer = Timer(0.5, count=2)
    stage_entrance = None

    map_is_100_percent_clear = False  # Will be override in fast_forward.py

    def enemy_searching_color_initial(self):
        pass

    def enemy_searching_appear(self):
        if not self.is_in_map():
            return False

        return MAP_ENEMY_SEARCHING.match_luma(self.device.image, offset=(5, 5))

    def handle_enemy_flashing(self):
        self.device.sleep(1.2)

    def handle_in_stage(self):
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

    def is_in_stage_page(self):
        return any(self.appear(check, offset=(20, 20)) for check in (CAMPAIGN_CHECK, EVENT_CHECK, SP_CHECK))

    def is_stage_page_has_entrance(self):
        """
        Has any stage entrance, which means stage page is fully loaded
        """
        # campaign_extract_name_image in CampaignOcr.
        try:
            if hasattr(self, "campaign_extract_name_image"):
                del_cached_property(self, "_stage_image")
                del_cached_property(self, "_stage_image_gray")
                if not len(self.campaign_extract_name_image(self.device.image)):
                    return False
        except IndexError:
            return False

        return True

    def is_in_stage(self):
        if not self.is_in_stage_page():
            return False
        return self.is_stage_page_has_entrance()

    def is_in_map(self):
        return self.appear(IN_MAP)

    def is_event_animation(self):
        """
        Animation in events after cleared an enemy.

        Returns:
            bool: If animation appearing.
        """
        return False

    def handle_auto_search_exit(self):
        """
        A placeholder, will be override in AutoSearchHandler.
        AutoSearchHandler inherits EnemySearchingHandler,
        but handle_in_map_with_enemy_searching() requires handle_auto_search_exit() to handle unexpected situation.
        """
        return False

    @staticmethod
    def _reset_enemy_searching_timeout(timeout, *, extend=False):
        if extend:
            timeout.limit = 10
        timeout.reset()

    def _handle_enemy_searching_interrupts(self, timeout, *, extend_timeout):
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

    def _handle_enemy_searching_animation_end(self, appeared):
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

    def handle_in_map_with_enemy_searching(self):
        """
        Returns:
            bool: If handled.
        """
        if not self.is_in_map():
            return False

        timeout = Timer(self.MAP_ENEMY_SEARCHING_TIMEOUT_SECOND)
        appeared = False
        while 1:
            self.device.screenshot()
            if self.is_event_animation():
                continue
            if self.is_in_map():
                timeout.start()
            else:
                timeout.reset()

            # Stage might ends,
            # although here expects an enemy searching animation.
            if self.handle_in_stage():
                return True
            # immediately enter submarine combat in W16
            if hasattr(self, "is_combat_loading") and self.is_combat_loading():
                logger.warning("Entered map with is_combat_loading appeared")
                break
            if self._handle_enemy_searching_interrupts(timeout, extend_timeout=True):
                continue

            # End
            appeared, finished = self._handle_enemy_searching_animation_end(appeared)
            if finished:
                break
            if timeout.reached():
                logger.info("Enemy searching timeout.")
                break

        return True

    def handle_in_map_no_enemy_searching(self):
        """
        Returns:
            bool: If handled.
        """
        if not self.is_in_map():
            return False

        timeout = Timer(1, count=2).start()
        while 1:
            self.device.screenshot()

            if not self.is_in_map():
                timeout.reset()

            # Stage might ends,
            # although here expects an enemy searching animation.
            if self.handle_in_stage():
                return True
            if self._handle_enemy_searching_interrupts(timeout, extend_timeout=False):
                continue

            # End
            if timeout.reached():
                logger.info("No enemy searching in map.")
                break

        return True
