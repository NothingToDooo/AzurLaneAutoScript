from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, overload

import cv2
import numpy as np

from module.base.button import Button
from module.base.timer import Timer
from module.campaign.campaign_event import CampaignEvent
from module.combat.assets import BATTLE_PREPARATION
from module.device.control_options import SwipeVectorOptions
from module.exception import ScriptError
from module.logger import logger
from module.map.map_operation import MapOperation
from module.ocr.ocr import Digit, DigitCounter, DigitCounterValue, OcrOptions
from module.raid import assets as raid_assets
from module.raid.combat import RaidCombat
from module.ui.assets import RAID_CHECK
from module.ui.page import page_rpg_stage

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray


class RaidCounterPostMixin(DigitCounter):
    @staticmethod
    def normalize_text(result: str) -> str:
        # 修正 915/、1515 等缺少分隔符的结果。
        result = DigitCounter.normalize_text(result)
        result = result.strip("/")
        if result.isdigit() and len(result) > 2 and result.endswith("15"):
            result = f"{result[:-2]}/15"
        return result


class RaidCounter(DigitCounter):
    def pre_process(self, image: ImageArray) -> ImageArray:
        image = super().pre_process(image)
        return np.pad(image, ((2, 2), (0, 0)), mode="constant", constant_values=255)


class HuanChangCounter(DigitCounter):
    """春节共斗次数纵向排列；返回 (上半部分识别值, 0, 15)。"""

    def after_process(self, result: str) -> DigitCounterValue:
        normalized = self.normalize_text(result)
        value = int(normalized) if normalized else 0
        if self.SHOW_REVISE_WARNING and str(value) != normalized:
            logger.warning(f'OCR {self.name}: Result "{normalized}" is revised to "{value}"')
        return value, 0, 15


class HuanChangPtOcr(Digit):
    def pre_process(self, image: ImageArray) -> ImageArray:
        """把 H×W×C 截图预处理为 H×W 数字掩码。"""
        gray = np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), dtype=np.uint8)
        binary = np.asarray(cv2.threshold(gray, self.threshold, 255, cv2.THRESH_BINARY_INV)[1], dtype=np.uint8)
        count, cc = cv2.connectedComponents(binary)
        # 面积大于 60 的连通域视为数字；英语服需同时排除右上、右下背景连通域。
        num_idx = [
            i for i in range(1, count + 1) if i != cc[0, -1] and i != cc[-1, -1] and np.count_nonzero(cc == i) > 60
        ]
        mask = ~(np.isin(cc, num_idx) * 255)  # 数字需反相为白色。
        return mask.astype(np.uint8)


type StandardRaidMode = Literal["easy", "normal", "hard"]
type RaidMode = StandardRaidMode | Literal["ex"]
type RaidPrefix = Literal[
    "ESSEX",
    "SURUGA",
    "BRISTOL",
    "IRIS",
    "ALBION",
    "KUYBYSHEY",
    "GORIZIA",
    "HUANCHANG",
    "RPG",
    "CHIENWU",
    "CHANGWU",
]


RAID_NAME_PREFIX: dict[str, RaidPrefix] = {
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


@dataclass(frozen=True, slots=True)
class _DigitCounterSpec:
    counter: type[DigitCounter]
    options: OcrOptions

    def create(self, button: Button) -> DigitCounter:
        return self.counter(button, self.options)


@dataclass(frozen=True, slots=True)
class _DigitSpec:
    counter: type[Digit]
    options: OcrOptions

    def create(self, button: Button) -> Digit:
        return self.counter(button, self.options)


@dataclass(frozen=True, slots=True)
class _RaidOcrConfig:
    default: _DigitCounterSpec
    ex: _DigitSpec | None = None


RAID_OCR_CONFIG: dict[RaidPrefix, _RaidOcrConfig] = {
    "ESSEX": _RaidOcrConfig(_DigitCounterSpec(RaidCounter, {"letter": (57, 52, 255), "threshold": 128})),
    "SURUGA": _RaidOcrConfig(_DigitCounterSpec(RaidCounter, {"letter": (49, 48, 49), "threshold": 128})),
    "BRISTOL": _RaidOcrConfig(_DigitCounterSpec(RaidCounter, {"letter": (214, 231, 219), "threshold": 128})),
    "IRIS": _RaidOcrConfig(
        _DigitCounterSpec(DigitCounter, {"letter": (148, 138, 123), "threshold": 128, "lang": "cnocr"})
    ),
    "ALBION": _RaidOcrConfig(_DigitCounterSpec(DigitCounter, {"letter": (99, 73, 57), "threshold": 128})),
    "KUYBYSHEY": _RaidOcrConfig(
        _DigitCounterSpec(DigitCounter, {"letter": (231, 239, 247), "threshold": 128}),
        _DigitSpec(Digit, {"letter": (189, 203, 214), "threshold": 128}),
    ),
    "GORIZIA": _RaidOcrConfig(
        _DigitCounterSpec(DigitCounter, {"letter": (82, 89, 66), "threshold": 128}),
        _DigitSpec(Digit, {"letter": (198, 223, 140), "threshold": 128}),
    ),
    "HUANCHANG": _RaidOcrConfig(
        _DigitCounterSpec(
            HuanChangCounter,
            {"letter": (255, 255, 255), "threshold": 80, "alphabet": "0123456789IDSB"},
        ),
        _DigitSpec(Digit, {"letter": (255, 255, 255), "threshold": 180}),
    ),
    "CHIENWU": _RaidOcrConfig(
        _DigitCounterSpec(DigitCounter, {"letter": (0, 0, 0), "threshold": 128}),
        _DigitSpec(Digit, {"letter": (247, 223, 222), "threshold": 128}),
    ),
    "CHANGWU": _RaidOcrConfig(
        _DigitCounterSpec(RaidCounterPostMixin, {"lang": "cnocr", "letter": (154, 148, 133), "threshold": 128}),
        _DigitSpec(Digit, {"letter": (255, 239, 215), "threshold": 128}),
    ),
}

RAID_PT_OCR_CONFIG: dict[RaidPrefix, _DigitSpec] = {
    "IRIS": _DigitSpec(Digit, {"letter": (181, 178, 165), "threshold": 128}),
    "ALBION": _DigitSpec(Digit, {"letter": (23, 20, 9), "threshold": 128}),
    "KUYBYSHEY": _DigitSpec(Digit, {"letter": (16, 24, 33), "threshold": 64}),
    "GORIZIA": _DigitSpec(Digit, {"letter": (255, 255, 255), "threshold": 64}),
    "HUANCHANG": _DigitSpec(HuanChangPtOcr, {"letter": (23, 20, 6), "threshold": 128}),
    "CHIENWU": _DigitSpec(Digit, {"letter": (255, 231, 231), "threshold": 128}),
    "CHANGWU": _DigitSpec(Digit, {"letter": (255, 239, 215), "threshold": 128}),
}

UNKNOWN_RAID_NAME_TEMPLATE = "Unknown raid name: {name}"
MISSING_RAID_ASSET_TEMPLATE = "Raid asset not exists: {key}"
RAID_OCR_NOT_CONFIGURED_TEMPLATE = "Raid OCR is not configured: {raid}, mode={mode}"
RAID_PT_OCR_NOT_CONFIGURED_TEMPLATE = "Raid PT OCR is not configured: {raid}"


def raid_name_shorten(name: str) -> RaidPrefix:
    """返回共斗活动的资产前缀；活动不受支持时抛出 ScriptError。"""
    if prefix := RAID_NAME_PREFIX.get(name):
        return prefix
    message = UNKNOWN_RAID_NAME_TEMPLATE.format(name=name)
    raise ScriptError(message)


def raid_entrance(raid: str, mode: RaidMode) -> Button:
    """返回 easy、normal、hard 或 ex 共斗入口；资产缺失时抛出 ScriptError。"""
    key = f"{raid_name_shorten(raid)}_RAID_{mode.upper()}"
    return _raid_asset(key)


def _raid_asset(key: str) -> Button:
    try:
        asset = getattr(raid_assets, key)
    except AttributeError as e:
        message = MISSING_RAID_ASSET_TEMPLATE.format(key=key)
        raise ScriptError(message) from e
    if not isinstance(asset, Button):
        message = MISSING_RAID_ASSET_TEMPLATE.format(key=key)
        raise ScriptError(message)
    return asset


@overload
def raid_ocr(raid: str, mode: Literal["ex"]) -> Digit: ...


@overload
def raid_ocr(raid: str, mode: StandardRaidMode) -> DigitCounter: ...


def raid_ocr(raid: str, mode: RaidMode) -> Digit | DigitCounter:
    """返回 easy、normal、hard 或 ex 的剩余次数 OCR；未配置时抛出 ScriptError。"""
    raid = raid_name_shorten(raid)
    config = RAID_OCR_CONFIG.get(raid)
    if config is None:
        message = RAID_OCR_NOT_CONFIGURED_TEMPLATE.format(raid=raid, mode=mode)
        raise ScriptError(message)
    if mode == "ex":
        ex_config = config.ex
        if ex_config is None:
            message = RAID_OCR_NOT_CONFIGURED_TEMPLATE.format(raid=raid, mode=mode)
            raise ScriptError(message)
        key = f"{raid}_OCR_REMAIN_EX"
        return ex_config.create(_raid_asset(key))
    key = f"{raid}_OCR_REMAIN_{mode.upper()}"
    return config.default.create(_raid_asset(key))


def pt_ocr(raid: str) -> Digit | None:
    """返回共斗 PT OCR；活动没有 PT 资产时返回 None，配置缺失时抛出 ScriptError。"""
    raid = raid_name_shorten(raid)
    key = f"{raid}_OCR_PT"
    button = getattr(raid_assets, key, None)
    if button is None:
        return None
    ocr_config = RAID_PT_OCR_CONFIG.get(raid)
    if ocr_config is not None:
        return ocr_config.create(button)
    message = RAID_PT_OCR_NOT_CONFIGURED_TEMPLATE.format(raid=raid)
    raise ScriptError(message)


class Raid(MapOperation, RaidCombat, CampaignEvent):
    @property
    def _raid_has_oil_icon(self) -> bool:
        """共斗 UI 已移除油量显示，固定返回 False；见 issue #5214。"""
        return False

    def triggered_stop_condition(
        self, *, oil_check: bool = False, pt_check: bool = False, coin_check: bool = False
    ) -> bool:
        """检查油量、PT 和金币停止条件；执行对应调度后返回 True。"""
        if oil_check and self.get_oil() < max(500, self.config.StopCondition_OilLimit):
            logger.hr("Triggered stop condition: Oil limit")
            self.config.task_delay(minute=(120, 240))
            return True
        if pt_check and self.event_pt_limit_triggered():
            logger.hr("Triggered stop condition: Event PT limit")
            return True
        if coin_check and self.config.TaskBalancer_Enable and self.triggered_task_balancer():
            logger.hr("Triggered stop condition: Coin limit")
            self.handle_task_balancer()
            return True

        return False

    def _handle_raid_preparation_page(self, *, auto: str, checked: bool) -> tuple[bool, bool]:
        if not self.appear(BATTLE_PREPARATION, offset=(30, 20)):
            return checked, False
        if self.handle_combat_automation_set(auto=auto == "combat_auto"):
            return checked, True
        if not checked and self._raid_has_oil_icon:
            checked = True
            if self.triggered_stop_condition(oil_check=True, coin_check=True):
                self.config.task_stop()
        return checked, False

    def _handle_raid_preparation_actions(self) -> bool:
        return (
            self.handle_raid_ticket_use()
            or self.handle_retirement()
            or self.handle_combat_low_emotion()
            or self.appear_then_click(BATTLE_PREPARATION, offset=(30, 20), interval=2)
            or self.handle_combat_automation_confirm()
            or self.handle_story_skip()
        )

    def _finish_raid_preparation_if_combat_started(self, *, emotion_reduce: bool, fleet_index: int) -> bool:
        pause = self.is_combat_executing()
        if not pause:
            return False
        logger.attr("BattleUI", pause)
        if emotion_reduce:
            self.emotion.reduce(fleet_index)
        return True

    def combat_preparation(
        self,
        *,
        balance_hp: bool = False,
        emotion_reduce: bool = False,
        auto: str = "combat_auto",
        fleet_index: int = 1,
    ) -> None:
        """复用普通战斗准备接口并等待战斗开始。

        balance_hp 故意忽略；auto 控制自动战斗，emotion_reduce 按 fleet_index 扣除心情。
        """
        logger.info("Combat preparation.")

        del balance_hp

        checked = False
        for _ in self.loop():
            checked, handled = self._handle_raid_preparation_page(auto=auto, checked=checked)
            if handled:
                continue
            if self._handle_raid_preparation_actions():
                continue

            if self._finish_raid_preparation_if_combat_started(emotion_reduce=emotion_reduce, fleet_index=fleet_index):
                break

    def handle_raid_ticket_use(self) -> bool:
        """按配置确认或取消使用共斗票，并返回是否点击。"""
        if self.appear(raid_assets.TICKET_USE_CONFIRM, offset=(30, 30), interval=1):
            if self.config.Raid_UseTicket:
                self.device.click(raid_assets.TICKET_USE_CONFIRM)
            else:
                self.device.click(raid_assets.TICKET_USE_CANCEL)
            return True

        return False

    def raid_enter(self, *, mode: RaidMode, raid: str, skip_first_screenshot: bool = True) -> None:
        """从共斗页进入指定活动难度，结束于战斗准备页。"""
        entrance = raid_entrance(raid=raid, mode=mode)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

            if self.appear(entrance, offset=(10, 10), interval=5):
                # 入口从右侧滑入，出现后再检查 PT 停止条件。
                if self.triggered_stop_condition(pt_check=True):
                    self.config.task_stop()
                self.device.click(entrance)
                continue
            if self.appear_then_click(raid_assets.RAID_FLEET_PREPARATION, offset=(20, 20), interval=5):
                continue

            if self.combat_appear():
                break

    def raid_expected_end(self) -> bool:
        """奖励弹窗返回 False 继续处理；RPG 和普通共斗分别以关卡页、共斗页结束。"""
        if self.appear_then_click(raid_assets.RAID_REWARDS, offset=(30, 30), interval=3):
            return False
        if self.is_raid_rpg():
            return self.appear(page_rpg_stage.check_button, offset=(30, 30))
        return self.appear(RAID_CHECK, offset=(30, 30))

    def raid_execute_once(self, *, mode: RaidMode, raid: str) -> None:
        """从共斗页完成一次战斗并返回；ex 会临时启用每战潜艇并在结束后恢复。"""
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

    def get_event_pt(self) -> int:
        """在共斗页读取 PT；不支持 OCR 返回 0，超时返回最后一次结果（可能仍是 70000/70001）。"""
        skip_first_screenshot = True
        timeout = Timer(1.5, count=5).start()
        ocr = pt_ocr(self.config.Campaign_Event)
        if ocr is not None:
            # 70000、70001 是页面未加载完成时的默认值，需要继续等待。
            while 1:
                if skip_first_screenshot:
                    skip_first_screenshot = False
                else:
                    self.device.screenshot()

                pt = ocr.ocr_single(self.device.image)
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

    def is_raid_rpg(self) -> bool:
        return self.config.Campaign_Event == "raid_20240328"

    def raid_rpg_swipe(self, *, skip_first_screenshot: bool = True) -> None:
        """在 2024-03-28 RPG 共斗中滑到最右侧。"""
        interval = Timer(1)
        while 1:
            if skip_first_screenshot:
                skip_first_screenshot = False
            else:
                self.device.screenshot()

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
