from module.base.timer import Timer
from module.base.utils import get_color, red_overlay_transparency
from module.combat.combat import Combat
from module.handler import assets as handler_assets
from module.handler.info_handler import info_letter_preprocess
from module.logger import logger
from module.template.assets import (
    TEMPLATE_AMBUSH_EVADE_FAILED,
    TEMPLATE_AMBUSH_EVADE_SUCCESS,
    TEMPLATE_MAP_WALK_OUT_OF_STEP,
)

vars(TEMPLATE_AMBUSH_EVADE_SUCCESS)["pre_process"] = info_letter_preprocess
vars(TEMPLATE_AMBUSH_EVADE_FAILED)["pre_process"] = info_letter_preprocess
vars(TEMPLATE_MAP_WALK_OUT_OF_STEP)["pre_process"] = info_letter_preprocess


class AmbushHandler(Combat):
    MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD = 0.40
    MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD = 0.35  # 实测通常为 0.50～0.53。
    MAP_AIR_RAID_CONFIRM_SECOND = 0.5

    def ambush_color_initial(self):
        handler_assets.MAP_AMBUSH.load_color(self.device.image)
        handler_assets.MAP_AIR_RAID.load_color(self.device.image)

    def _ambush_appear(self):
        return (
            red_overlay_transparency(
                handler_assets.MAP_AMBUSH.color,
                get_color(self.device.image, handler_assets.MAP_AMBUSH.area),
            )
            > self.MAP_AMBUSH_OVERLAY_TRANSPARENCY_THRESHOLD
        )

    def _air_raid_appear(self):
        return (
            red_overlay_transparency(
                handler_assets.MAP_AIR_RAID.color,
                get_color(self.device.image, handler_assets.MAP_AIR_RAID.area),
            )
            > self.MAP_AIR_RAID_OVERLAY_TRANSPARENCY_THRESHOLD
        )

    def _handle_air_raid(self):
        logger.info("Map air raid")
        disappear = Timer(self.MAP_AIR_RAID_CONFIRM_SECOND).start()
        timeout = Timer(2.5, count=2).start()

        while 1:
            self.device.screenshot()
            if timeout.reached():
                logger.warning("_handle_air_raid timeout, assume air raid disappeared")
                break
            if self._air_raid_appear():
                disappear.reset()
            elif disappear.reached():
                break

    def _handle_ambush_evade(self):
        logger.info("Map ambushed")
        self.wait_until_appear(handler_assets.MAP_AMBUSH_EVADE, offset=(30, 30))
        self.handle_info_bar()

        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.info_bar_count():
                break

            if self.appear_then_click(handler_assets.MAP_AMBUSH_EVADE, offset=(30, 30), interval=3):
                continue

        image = info_letter_preprocess(self.image_crop(handler_assets.INFO_BAR_DETECT, copy=False))
        if TEMPLATE_AMBUSH_EVADE_SUCCESS.match(image):
            logger.attr("Ambush_evade", "success")
        elif TEMPLATE_AMBUSH_EVADE_FAILED.match(image):
            logger.attr("Ambush_evade", "failed")
            self.combat(expected_end="no_searching", fleet_index=self.fleet_show_index)
        else:
            logger.warning("Unrecognized info when ambush evade.")
            self.ensure_no_info_bar()
            if self.combat_appear():
                self.combat(fleet_index=self.fleet_show_index)

    def _handle_ambush_attack(self):
        logger.info("Map ambushed")
        self.wait_until_appear(handler_assets.MAP_AMBUSH_ATTACK, offset=(30, 30))

        skip_first_screenshot = True
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.combat_appear():
                break

            if self.appear_then_click(handler_assets.MAP_AMBUSH_ATTACK, offset=(30, 30), interval=3):
                continue
            if self.handle_combat_low_emotion():
                continue
            if self.handle_retirement():
                continue

        logger.attr("Ambush_evade", "attack")
        self.combat(expected_end="no_searching", fleet_index=self.fleet_show_index)

    def _handle_ambush(self):
        if self.config.Campaign_AmbushEvade:
            return self._handle_ambush_evade()
        return self._handle_ambush_attack()

    def handle_ambush(self):
        if not self.config.MAP_HAS_AMBUSH:
            return False

        if self._air_raid_appear():
            self._handle_air_raid()
            return True

        if self._ambush_appear():
            self._handle_ambush()
            return True

        if self.appear(handler_assets.MAP_AMBUSH_EVADE, offset=(30, 30)):
            self._handle_ambush()

        return False

    def handle_walk_out_of_step(self):
        if not self.config.MAP_HAS_FLEET_STEP:
            return False
        if not self.info_bar_count():
            return False

        image = info_letter_preprocess(self.image_crop(handler_assets.INFO_BAR_DETECT, copy=False))
        if TEMPLATE_MAP_WALK_OUT_OF_STEP.match(image):
            logger.warning("Map walk out of step.")
            self.handle_info_bar()
            return True

        return False
