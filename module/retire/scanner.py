from abc import ABCMeta, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import cv2
import numpy as np

from module.base.utils import color_similar, crop, get_color, limit_in
from module.combat.level import LevelOcr
from module.logger import logger
from module.ocr.ocr import Digit
from module.retire.assets import (
    TEMPLATE_FLEET_1,
    TEMPLATE_FLEET_2,
    TEMPLATE_FLEET_3,
    TEMPLATE_FLEET_4,
    TEMPLATE_FLEET_5,
    TEMPLATE_FLEET_6,
    TEMPLATE_IN_BATTLE,
    TEMPLATE_IN_COMMISSION,
    TEMPLATE_IN_EVENT_FLEET,
)
from module.retire.dock import CARD_EMOTION_GRIDS, CARD_GRIDS, CARD_LEVEL_GRIDS, CARD_RARITY_GRIDS

if TYPE_CHECKING:
    from module.base.button import ButtonGrid

type ScannerLimitValue = int | str
type ShipLimitValue = ScannerLimitValue | tuple[ScannerLimitValue, ScannerLimitValue] | list[ScannerLimitValue] | None


class EmotionDigit(Digit):
    def after_process(self, result):
        # 唐斯头发容易造成随机 OCR 错误。
        # OCR DOCK_EMOTION_OCR 会把 "044" 修正为 "44"。
        if result in {"044", "D44"}:
            result = "0"

        return super().after_process(result)


@dataclass(frozen=True)
class Ship:
    rarity: str = ""
    level: int = 0
    emotion: int = 0
    fleet: int = 0
    status: str = ""
    button: Any = None

    def satisfy_limitation(self, limitaion: dict[str, ShipLimitValue]) -> bool:
        for key in self.__dict__:
            value = limitaion.get(key)
            if self.__dict__[key] is not None and value is not None:
                # 标量精确匹配，元组按闭区间匹配，列表按成员匹配。
                if isinstance(value, (str, int)):
                    if value == "any":
                        continue
                    if self.__dict__[key] != value:
                        return False
                elif isinstance(value, tuple):
                    if not (value[0] <= self.__dict__[key] <= value[1]):
                        return False
                elif isinstance(value, list):
                    if self.__dict__[key] not in value:
                        return False

        return True


class Scanner(metaclass=ABCMeta):
    _results: list | None = None
    _enabled: bool = True
    _disabled_value: list[None] = [None] * 14
    grids: ButtonGrid | None = None

    @property
    def results(self) -> list:
        if self._results is None:
            self._results = []
        return self._results

    @abstractmethod
    def _scan(self, image) -> list:
        pass

    @abstractmethod
    def limit_value(self, value) -> ScannerLimitValue:
        pass

    def clear(self) -> None:
        self.results.clear()

    def scan(self, image, cached=False, output=False) -> list | None:
        """禁用时产生 14 个 None；cached=True 时追加到缓存并返回 None。"""
        results: list = self._scan(image) if self._enabled else self._disabled_value

        if output:
            for result in results:
                logger.info(f"{result}")

        if cached:
            self.results.extend(results)
        else:
            return results
        return None

    def move(self, vector) -> None:
        grids = self.grids
        if grids is None:
            raise RuntimeError
        self.grids = grids.move(vector)

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False


class LevelScanner(Scanner):
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_LEVEL_GRIDS
        self.ocr_model = LevelOcr(self.grids.buttons, name="DOCK_LEVEL_OCR", threshold=64)

    def _scan(self, image) -> list:
        return self.ocr_model.ocr(image)

    def limit_value(self, value) -> int:
        return limit_in(value, 1, 125)


class EmotionScanner(Scanner):
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_EMOTION_GRIDS
        self.ocr_model = EmotionDigit(self.grids.buttons, name="DOCK_EMOTION_OCR", threshold=176)

    def _scan(self, image) -> list:
        return self.ocr_model.ocr(image)

    def limit_value(self, value) -> int:
        return limit_in(value, 0, 150)


class RarityScanner(Scanner):
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_RARITY_GRIDS
        self.value_list: list[str] = ["common", "rare", "elite", "super_rare"]

    def color_to_rarity(self, color: tuple[int, int, int]) -> str:
        """返回 common、rare、elite、super_rare 或 unknown。

        海上传奇颜色差异过大，统一标记为 unknown。
        """
        if color_similar(color, (171, 174, 186)):
            return "common"
        if color_similar(color, (106, 194, 248)):
            return "rare"
        if color_similar(color, (151, 134, 254)):
            return "elite"
        if color_similar(color, (247, 221, 101)):
            return "super_rare"
        # 海上传奇颜色差异过大。
        return "unknown"

    def _scan(self, image) -> list:
        if self.grids is None:
            raise RuntimeError
        return [self.color_to_rarity(get_color(image, button.area)) for button in self.grids.buttons]

    def limit_value(self, value) -> str:
        return value if value in self.value_list else "any"


class FleetScanner(Scanner):
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_GRIDS.crop(area=(0, 117, 35, 162), name="FLEET")
        self.templates = {
            TEMPLATE_FLEET_1: 1,
            TEMPLATE_FLEET_2: 2,
            TEMPLATE_FLEET_3: 3,
            TEMPLATE_FLEET_4: 4,
            TEMPLATE_FLEET_5: 5,
            TEMPLATE_FLEET_6: 6,
        }

    def pre_process(self, image):
        """绿色通道二值化可稳定分离舰队编号；更新 TEMPLATE_FLEET 时也必须先做此预处理。"""
        _, g, _ = cv2.split(image)
        _, image = cv2.threshold(g, 205, 255, cv2.THRESH_BINARY)
        return cv2.merge([image, image, image])

    def _match(self, image) -> int:
        """海上传奇闪光会干扰模板匹配；未命中时按不在舰队中处理。"""
        for template, fleet in self.templates.items():
            if template.match(image):
                return fleet

        if TEMPLATE_FLEET_1.match(image, similarity=0.80):
            return 1
        if TEMPLATE_FLEET_3.match(image, similarity=0.80):
            return 3
        if TEMPLATE_FLEET_4.match(image, similarity=0.80):
            return 4
        return 0

    def _scan(self, image) -> list:
        image = self.pre_process(image)
        if self.grids is None:
            raise RuntimeError
        image_list = [crop(image, button.area) for button in self.grids.buttons]

        return [self._match(image) for image in image_list]

    def limit_value(self, value) -> int:
        return limit_in(value, 0, 6)


class StatusScanner(Scanner):
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_GRIDS
        self.value_list: list[str] = ["free", "battle", "commission"]
        self.templates = {
            TEMPLATE_IN_BATTLE: "battle",
            TEMPLATE_IN_COMMISSION: "commission",
            TEMPLATE_IN_EVENT_FLEET: "in_event_fleet",
        }

    def _match(self, image) -> str:
        for template, status in self.templates.items():
            if template.match(image, similarity=0.75):
                return status

        return "free"

    def _scan(self, image) -> list:
        if self.grids is None:
            raise RuntimeError
        image_list = [crop(image, button.area) for button in self.grids.buttons]

        return [self._match(image) for image in image_list]

    def limit_value(self, value) -> str:
        return value if value in self.value_list else "any"


class ShipScanner(Scanner):
    """仅用于筛选后未滚动的船坞首屏；多页扫描应使用 DockScanner。

    等级、心情、舰队范围分别为 1 至 125、0 至 150、0 至 6；禁用字段返回 None。
    rarity 支持 any、common、rare、elite、super_rare，status 支持 any、free、commission、battle；any 表示不限制。
    """

    def __init__(
        self,
        rarity: str | list[str] = "any",
        level: tuple[int, int] = (1, 125),
        emotion: tuple[int, int] = (0, 150),
        fleet: int | list[int] = 0,
        status: str | list[str] = "any",
    ) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_GRIDS
        self.limitaion: dict[str, ShipLimitValue] = {
            "level": (1, 125),
            "emotion": (0, 150),
            "rarity": "any",
            "fleet": 0,
            "status": "any",
        }

        self.sub_scanners: dict[str, Scanner] = {
            "level": LevelScanner(),
            "emotion": EmotionScanner(),
            "rarity": RarityScanner(),
            "fleet": FleetScanner(),
            "status": StatusScanner(),
        }

        self.set_limitation(level=level, emotion=emotion, rarity=rarity, fleet=fleet, status=status)

    def _scan(self, image) -> list:
        for scanner in self.sub_scanners.values():
            scanner.scan(image, cached=True)

        grids = self.grids
        if grids is None:
            raise RuntimeError
        candidates: list[Ship] = [
            Ship(level=level, emotion=emotion, rarity=rarity, fleet=fleet, status=status, button=button)
            for level, emotion, rarity, fleet, status, button in zip(
                self.sub_scanners["level"].results,
                self.sub_scanners["emotion"].results,
                self.sub_scanners["rarity"].results,
                self.sub_scanners["fleet"].results,
                self.sub_scanners["status"].results,
                grids.buttons,
                strict=True,
            )
        ]

        for scanner in self.sub_scanners.values():
            scanner.clear()

        return candidates

    def scan(self, image, cached=False, output=True) -> list | None:
        ships = super().scan(image, cached, output)
        if not cached:
            return [ship for ship in ships or [] if ship.satisfy_limitation(self.limitaion)]
        return None

    def move(self, vector) -> None:
        for scanner in self.sub_scanners.values():
            scanner.move(vector)

        super().move(vector)

    def limit_value(self, value) -> ScannerLimitValue:
        return value

    def _set_limitation_value(self, key, value) -> None:
        if value is None:
            self.limitaion[key] = None
        elif isinstance(value, tuple):
            lower, upper = value
            lower = self.sub_scanners[key].limit_value(lower)
            upper = self.sub_scanners[key].limit_value(upper)
            self.limitaion[key] = (lower, upper)
        elif isinstance(value, list):
            self.limitaion[key] = [self.sub_scanners[key].limit_value(v) for v in value]
        else:
            self.limitaion[key] = self.sub_scanners[key].limit_value(value)

    def enable(self, *args) -> None:
        for name, scanner in self.sub_scanners.items():
            if name in args:
                scanner.enable()

    def disable(self, *args) -> None:
        for name, scanner in self.sub_scanners.items():
            if name in args:
                scanner.disable()

    def set_limitation(self, **kwargs):
        for attr in self.limitaion:
            value = kwargs.get(attr, self.limitaion[attr])
            self._set_limitation_value(key=attr, value=value)

        logger.info(f"Limitaions set to {self.limitaion}")


class DockScanner(ShipScanner):
    scan_grids: ButtonGrid

    def __init__(
        self,
        rarity: str = "any",
        level: tuple[int, int] = (1, 125),
        emotion: tuple[int, int] = (0, 150),
        fleet: int = 0,
        status: str = "any",
    ) -> None:
        raise NotImplementedError
        super().__init__(rarity, level, emotion, fleet, status)
        self.scan_zone = (93, 76, 1218, 719)
        self.card_bottom = []

    def multi_scan(self, image):
        """用舰船卡片间低方差空隙的位移估算滚动偏移，再同步移动扫描网格。"""
        scan_image = crop(image, self.scan_zone, copy=False)

        def find_bound(image):
            image = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
            std = np.std(image, axis=1)
            gap_seq = [720, *np.nonzero(std < 10)[0].tolist()]
            logger.info(f"{gap_seq}")
            bound = [
                gap_seq[pos] for pos in range(len(gap_seq) - 1, 0, -1) if abs(gap_seq[pos - 1] - gap_seq[pos]) > 50
            ]
            if len(bound) < 3:
                bound = [0, *bound]
            return bound

        bounds = [find_bound(crop(scan_image, button.area, copy=False)) for button in self.scan_grids.buttons]
        card_bottom = (np.mean(bounds, axis=0) + 0.5).astype(np.uint8)
        offset_rough = card_bottom[0] - self.card_bottom[0]
        self.card_bottom.clear()
        self.card_bottom.extend(card_bottom)

        offset = offset_rough
        self.move(offset)

    def scan_one_fleet(self, fleet: int | None = None) -> list[Ship]:
        raise NotImplementedError

    def scan_whole_dock(self) -> list[Ship]:
        raise NotImplementedError
