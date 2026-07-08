import cv2
import numpy as np

from module.base.timer import Timer
from module.campaign.campaign_event import CampaignEvent
from module.combat.assets import BATTLE_PREPARATION
from module.device.control_options import SwipeVectorOptions
from module.exception import ScriptError
from module.logger import logger
from module.map.map_operation import MapOperation
from module.ocr.ocr import Digit, DigitCounter
from module.raid import assets as raid_assets
from module.raid.combat import RaidCombat
from module.ui.assets import RAID_CHECK
from module.ui.page import page_rpg_stage


class RaidCounterPostMixin(DigitCounter):
    def after_process(self, result):
        # fix result like "915/", "1515"
        result = result.strip("/")
        if result.isdigit() and len(result) > 2 and result.endswith("15"):
            result = f"{result[:-2]}/15"
        return result


class RaidCounter(DigitCounter):
    def pre_process(self, image):
        image = super().pre_process(image)
        return np.pad(image, ((2, 2), (0, 0)), mode="constant", constant_values=255)


class HuanChangCounter(Digit):
    """
    The limit on number of raid event "Spring Festive Fiasco" is vertical,
    Ocr numbers on the top half.
    """

    def ocr(self, image, direct_ocr=False):
        result = super().ocr(image, direct_ocr)
        return (result, 0, 15)


class HuanChangPtOcr(Digit):
    def pre_process(self, image):
        """
        Args:
            image (np.ndarray): Shape (height, width, channel)

        Returns:
            np.ndarray: Shape (height, width)
        """
        image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
        image = cv2.threshold(image, 128, 255, cv2.THRESH_BINARY_INV)[1]
        count, cc = cv2.connectedComponents(image)
        # Calculate connected area, greater than 60 is considered a number,
        # CN, JP background rightmost is connected but EN is not,
        # EN need judge both [0, -1] and [-1, -1]
        num_idx = [
            i for i in range(1, count + 1) if i != cc[0, -1] and i != cc[-1, -1] and np.count_nonzero(cc == i) > 60
        ]
        image = ~(np.isin(cc, num_idx) * 255)  # Numbers are white, need invert
        return image.astype(np.uint8)


RAID_NAME_PREFIX = {
    "raid_20200624": "ESSEX",
    "raid_20210708": "SURUGA",
    "raid_20220127": "BRISTOL",
    "raid_20220630": "IRIS",
    "raid_20221027": "ALBION",
    "raid_20230118": "KUYBYSHEY",
    "raid_20230629": "GORIZIA",
    "raid_20240130": "HUANCHANG",
    "raid_20240328": "RPG",
    "raid_20250116": "CHIENWU",
    "raid_20260212": "CHANGWU",
}

RAID_OCR_CONFIG = {
    "ESSEX": {"default": (RaidCounter, {"letter": (57, 52, 255), "threshold": 128})},
    "SURUGA": {"default": (RaidCounter, {"letter": (49, 48, 49), "threshold": 128})},
    "BRISTOL": {"default": (RaidCounter, {"letter": (214, 231, 219), "threshold": 128})},
    "IRIS": {"default": (DigitCounter, {"letter": (148, 138, 123), "threshold": 128, "lang": "cnocr"})},
    "ALBION": {"default": (DigitCounter, {"letter": (99, 73, 57), "threshold": 128})},
    "KUYBYSHEY": {
        "default": (DigitCounter, {"letter": (231, 239, 247), "threshold": 128}),
        "ex": (Digit, {"letter": (189, 203, 214), "threshold": 128}),
    },
    "GORIZIA": {
        "default": (DigitCounter, {"letter": (82, 89, 66), "threshold": 128}),
        "ex": (Digit, {"letter": (198, 223, 140), "threshold": 128}),
    },
    "HUANCHANG": {
        "default": (HuanChangCounter, {"letter": (255, 255, 255), "threshold": 80}),
        "ex": (Digit, {"letter": (255, 255, 255), "threshold": 180}),
    },
    "CHIENWU": {
        "default": (DigitCounter, {"letter": (0, 0, 0), "threshold": 128}),
        "ex": (Digit, {"letter": (247, 223, 222), "threshold": 128}),
    },
    "CHANGWU": {
        "default": (RaidCounterPostMixin, {"lang": "cnocr", "letter": (154, 148, 133), "threshold": 128}),
        "ex": (Digit, {"letter": (255, 239, 215), "threshold": 128}),
    },
}

RAID_PT_OCR_CONFIG = {
    "IRIS": (Digit, {"letter": (181, 178, 165), "threshold": 128}),
    "ALBION": (Digit, {"letter": (23, 20, 9), "threshold": 128}),
    "KUYBYSHEY": (Digit, {"letter": (16, 24, 33), "threshold": 64}),
    "GORIZIA": (Digit, {"letter": (255, 255, 255), "threshold": 64}),
    "HUANCHANG": (HuanChangPtOcr, {"letter": (23, 20, 6), "threshold": 128}),
    "CHIENWU": (Digit, {"letter": (255, 231, 231), "threshold": 128}),
    "CHANGWU": (Digit, {"letter": (255, 239, 215), "threshold": 128}),
}


def raid_name_shorten(name):
    """
    Args:
        name (str): 共斗活动名，例如 raid_20200624、raid_20210708。

    Returns:
        str: 按钮名前缀，例如 ESSEX、SURUGA。
    """
    if prefix := RAID_NAME_PREFIX.get(name):
        return prefix
    raise ScriptError(f"Unknown raid name: {name}")


def raid_entrance(raid, mode):
    """
    Args:
        raid (str): Raid name, such as raid_20200624, raid_20210708.
        mode (str): easy, normal, hard

    Returns:
        Button:
    """
    key = f"{raid_name_shorten(raid)}_RAID_{mode.upper()}"
    return _raid_asset(key)


def _raid_asset(key):
    try:
        return getattr(raid_assets, key)
    except AttributeError as e:
        raise ScriptError(f"Raid asset not exists: {key}") from e


def raid_ocr(raid, mode):
    """
    Args:
        raid (str): Raid name, such as raid_20200624, raid_20210708.
        mode (str): easy, normal, hard, ex

    Returns:
        DigitCounter:
    """
    raid = raid_name_shorten(raid)
    key = f"{raid}_OCR_REMAIN_{mode.upper()}"
    button = _raid_asset(key)
    config = RAID_OCR_CONFIG.get(raid, {})
    counter_config = config.get(mode, config.get("default"))
    if counter_config is not None:
        counter, kwargs = counter_config
        return counter(button, **kwargs)
    raise ScriptError(f"Raid OCR is not configured: {raid}, mode={mode}")


def pt_ocr(raid):
    """
    Args:
        raid (str): Raid name, such as raid_20200624, raid_20210708.

    Returns:
        Digit:
    """
    raid = raid_name_shorten(raid)
    key = f"{raid}_OCR_PT"
    button = getattr(raid_assets, key, None)
    if button is None:
        return None
    ocr_config = RAID_PT_OCR_CONFIG.get(raid)
    if ocr_config is not None:
        counter, kwargs = ocr_config
        return counter(button, **kwargs)
    raise ScriptError(f"Raid PT OCR is not configured: {raid}")


class Raid(MapOperation, RaidCombat, CampaignEvent):
    @property
    def _raid_has_oil_icon(self):
        """
        Game devs are too asshole to drop oil display for UI design
        https://github.com/LmeSzinc/AzurLaneAutoScript/issues/5214
        """
        return False

    def triggered_stop_condition(self, oil_check=False, pt_check=False, coin_check=False):
        """
        Returns:
            bool: If triggered a stop condition.
        """
        # Oil limit
        if oil_check and self.get_oil() < max(500, self.config.StopCondition_OilLimit):
            logger.hr("Triggered stop condition: Oil limit")
            self.config.task_delay(minute=(120, 240))
            return True
        # Event limit
        if pt_check and self.event_pt_limit_triggered():
            logger.hr("Triggered stop condition: Event PT limit")
            return True
        # TaskBalancer
        if coin_check and self.config.TaskBalancer_Enable and self.triggered_task_balancer():
            logger.hr("Triggered stop condition: Coin limit")
            self.handle_task_balancer()
            return True

        return False

    def _handle_raid_preparation_page(self, *, auto, checked):
        if not self.appear(BATTLE_PREPARATION, offset=(30, 20)):
            return checked, False
        if self.handle_combat_automation_set(auto=auto == "combat_auto"):
            return checked, True
        if not checked and self._raid_has_oil_icon:
            checked = True
            if self.triggered_stop_condition(oil_check=True, coin_check=True):
                self.config.task_stop()
        return checked, False

    def _handle_raid_preparation_actions(self):
        return (
            self.handle_raid_ticket_use()
            or self.handle_retirement()
            or self.handle_combat_low_emotion()
            or self.appear_then_click(BATTLE_PREPARATION, offset=(30, 20), interval=2)
            or self.handle_combat_automation_confirm()
            or self.handle_story_skip()
        )

    def _finish_raid_preparation_if_combat_started(self, *, emotion_reduce, fleet_index):
        pause = self.is_combat_executing()
        if not pause:
            return False
        logger.attr("BattleUI", pause)
        if emotion_reduce:
            self.emotion.reduce(fleet_index)
        return True

    def combat_preparation(self, balance_hp=False, emotion_reduce=False, auto="combat_auto", fleet_index=1):
        """
        Args:
            balance_hp (bool):
            emotion_reduce (bool):
            auto (bool):
            fleet_index (int):
        """
        logger.info("Combat preparation.")

        # Raid 战斗复用普通战斗入口，但不执行普通战斗的血量平衡。
        del balance_hp
        # 不需要等待，raid_execute_once() 已经处理过。
        # if emotion_reduce:
        #     self.emotion.wait(fleet_index)

        checked = False
        for _ in self.loop():
            checked, handled = self._handle_raid_preparation_page(auto=auto, checked=checked)
            if handled:
                continue
            if self._handle_raid_preparation_actions():
                continue

            # End
            if self._finish_raid_preparation_if_combat_started(emotion_reduce=emotion_reduce, fleet_index=fleet_index):
                break

    def handle_raid_ticket_use(self):
        """
        Returns:
            bool: If clicked.
        """
        if self.appear(raid_assets.TICKET_USE_CONFIRM, offset=(30, 30), interval=1):
            if self.config.Raid_UseTicket:
                self.device.click(raid_assets.TICKET_USE_CONFIRM)
            else:
                self.device.click(raid_assets.TICKET_USE_CANCEL)
            return True

        return False

    def raid_enter(self, mode, raid, skip_first_screenshot=True):
        """
        Args:
            mode:
            raid:
            skip_first_screenshot:

        Pages:
            in: page_raid
            out: BATTLE_PREPARATION
        """
        entrance = raid_entrance(raid=raid, mode=mode)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(entrance, offset=(10, 10), interval=5):
                # Items appear from right
                # Check PT when entrance appear
                if self.triggered_stop_condition(pt_check=True):
                    self.config.task_stop()
                self.device.click(entrance)
                continue
            if self.appear_then_click(raid_assets.RAID_FLEET_PREPARATION, offset=(20, 20), interval=5):
                continue

            # End
            if self.combat_appear():
                break

    def raid_expected_end(self):
        if self.appear_then_click(raid_assets.RAID_REWARDS, offset=(30, 30), interval=3):
            return False
        if self.is_raid_rpg():
            return self.appear(page_rpg_stage.check_button, offset=(30, 30))
        return self.appear(RAID_CHECK, offset=(30, 30))

    def raid_execute_once(self, mode, raid):
        """
        Args:
            mode:
            raid:

        Returns:
            in: page_raid
            out: page_raid
        """
        logger.hr("Raid Execute")
        self.config.override(
            Campaign_Name=f"{raid}_{mode}", Campaign_UseAutoSearch=False, Fleet_FleetOrder="fleet1_all_fleet2_standby"
        )

        if mode == "ex":
            backup = self.config.temporary(Submarine_Fleet=1, Submarine_Mode="every_combat")

        self.emotion.check_reduce(1)

        self.raid_enter(mode=mode, raid=raid)
        self.combat(balance_hp=False, expected_end=self.raid_expected_end)

        if mode == "ex":
            backup.recover()

        logger.hr("Raid End")

    def get_event_pt(self):
        """
        Returns:
            int: Raid PT, 0 if raid event is not supported

        Pages:
            in: page_raid
        """
        skip_first_screenshot = True
        timeout = Timer(1.5, count=5).start()
        ocr = pt_ocr(self.config.Campaign_Event)
        if ocr is not None:
            # 70000 seems to be a default value, wait
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                pt = ocr.ocr(self.device.image)
                if timeout.reached():
                    logger.warning("Wait PT timeout, assume it is")
                    return pt
                if pt in [70000, 70001]:
                    continue
                return pt
        else:
            logger.info(f"Raid {self.config.Campaign_Event} does not support PT ocr, skip")
            return 0
        return 0

    def is_raid_rpg(self):
        return self.config.Campaign_Event == "raid_20240328"

    def raid_rpg_swipe(self, skip_first_screenshot=True):
        """
        Swipe til the rightmost in RPG raid (raid_20240328)
        """
        interval = Timer(1)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            # End
            if self.appear(raid_assets.RPG_RAID_EASY, offset=(10, 10)):
                logger.info("RPG raid already at rightmost")
                break

            if self.handle_story_skip():
                continue
            if self.handle_get_items():
                continue
            if interval.reached():
                self.device.swipe_vector((-900, 0), SwipeVectorOptions(box=(0, 130, 1280, 440)))
                interval.reset()
                continue
