from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal, TypedDict, Unpack, override

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
    from collections.abc import Mapping, Sequence

    from module.base.button import Button, ButtonGrid
    from module.base.type_alias import Area, Color, ImageArray, Point

type ScannerLimitValue = int | str
type ShipLimitValue = ScannerLimitValue | tuple[int, int] | list[ScannerLimitValue] | None
type ScannerName = Literal["level", "emotion", "rarity", "fleet", "status"]


class ShipScannerSettings(TypedDict, total=False):
    rarity: str | list[str]
    level: tuple[int, int]
    emotion: tuple[int, int]
    fleet: int | list[int]
    status: str | list[str]


class EmotionDigit(Digit):
    def after_process(self, result: str) -> int:
        # 唐斯头发容易造成随机 OCR 错误。
        # OCR DOCK_EMOTION_OCR 会把 "044" 修正为 "44"。
        if result in {"044", "D44"}:
            result = "0"

        return super().after_process(result)


@dataclass(frozen=True)
class Ship:
    button: Button
    rarity: str | None = ""
    level: int | None = 0
    emotion: int | None = 0
    fleet: int | None = 0
    status: str | None = ""

    def satisfy_limitation(self, limitaion: Mapping[ScannerName, ShipLimitValue]) -> bool:
        values: dict[ScannerName, ScannerLimitValue | None] = {
            "rarity": self.rarity,
            "level": self.level,
            "emotion": self.emotion,
            "fleet": self.fleet,
            "status": self.status,
        }
        for key, current in values.items():
            value = limitaion.get(key)
            if current is not None and value is not None:
                # 标量精确匹配，元组按闭区间匹配，列表按成员匹配。
                if isinstance(value, (str, int)):
                    if value == "any":
                        continue
                    if current != value:
                        return False
                elif isinstance(value, tuple):
                    if not isinstance(current, int) or not (value[0] <= current <= value[1]):
                        return False
                elif isinstance(value, list):
                    if current not in value:
                        return False

        return True


class Scanner[ResultT](ABC):
    _results: list[ResultT | None] | None = None
    _enabled: bool = True
    _disabled_value: list[None] = [None] * 14
    grids: ButtonGrid | None = None

    @property
    def results(self) -> list[ResultT | None]:
        if self._results is None:
            self._results = []
        return self._results

    @abstractmethod
    def _scan(self, image: ImageArray) -> list[ResultT]:
        pass

    @abstractmethod
    def limit_value(self, value: ScannerLimitValue) -> ScannerLimitValue:
        pass

    def clear(self) -> None:
        self.results.clear()

    def _scan_or_disabled(self, image: ImageArray) -> list[ResultT | None]:
        if not self._enabled:
            return [None] * len(self._disabled_value)
        return list(self._scan(image))

    def scan(
        self,
        image: ImageArray,
        *,
        cached: bool = False,
        output: bool = False,
    ) -> Sequence[ResultT | None] | None:
        """禁用时产生 14 个 None；cached=True 时追加到缓存并返回 None。"""
        results = self._scan_or_disabled(image)

        if output:
            for result in results:
                logger.info(f"{result}")

        if cached:
            self.results.extend(results)
        else:
            return results
        return None

    def move(self, vector: Point) -> None:
        grids = self.grids
        if grids is None:
            raise RuntimeError
        self.grids = grids.move(vector)

    def enable(self) -> None:
        self._enabled = True

    def disable(self) -> None:
        self._enabled = False


class LevelScanner(Scanner[int]):
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_LEVEL_GRIDS
        self.ocr_model = LevelOcr(self.grids.buttons, name="DOCK_LEVEL_OCR", threshold=64)

    def _scan(self, image: ImageArray) -> list[int]:
        if self.grids is None:
            raise RuntimeError
        images = [crop(image, button.area) for button in self.grids.buttons]
        return self.ocr_model.ocr_many(images)

    @override
    def limit_value(self, value: ScannerLimitValue) -> int:
        if not isinstance(value, int):
            message = "level limitation must be an integer"
            raise TypeError(message)
        return int(limit_in(value, 1, 125))


class EmotionScanner(Scanner[int]):
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_EMOTION_GRIDS
        self.ocr_model = EmotionDigit(self.grids.buttons, name="DOCK_EMOTION_OCR", threshold=176)

    def _scan(self, image: ImageArray) -> list[int]:
        if self.grids is None:
            raise RuntimeError
        images = [crop(image, button.area) for button in self.grids.buttons]
        return self.ocr_model.ocr_many(images)

    @override
    def limit_value(self, value: ScannerLimitValue) -> int:
        if not isinstance(value, int):
            message = "emotion limitation must be an integer"
            raise TypeError(message)
        return int(limit_in(value, 0, 150))


class RarityScanner(Scanner[str]):
    def __init__(self) -> None:
        super().__init__()
        self._results = []
        self.grids = CARD_RARITY_GRIDS
        self.value_list: list[str] = ["common", "rare", "elite", "super_rare"]

    @staticmethod
    def color_to_rarity(color: Color) -> str:
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

    def _scan(self, image: ImageArray) -> list[str]:
        if self.grids is None:
            raise RuntimeError
        return [self.color_to_rarity(get_color(image, button.area)) for button in self.grids.buttons]

    def limit_value(self, value: ScannerLimitValue) -> str:
        if not isinstance(value, str):
            message = "rarity limitation must be a string"
            raise TypeError(message)
        return value if value in self.value_list else "any"


class FleetScanner(Scanner[int]):
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

    @staticmethod
    def pre_process(image: ImageArray) -> ImageArray:
        """绿色通道二值化可稳定分离舰队编号；更新 TEMPLATE_FLEET 时也必须先做此预处理。"""
        _, g, _ = cv2.split(image)
        _, thresholded = cv2.threshold(g, 205, 255, cv2.THRESH_BINARY)
        return np.asarray(cv2.merge([thresholded, thresholded, thresholded]), dtype=np.uint8)

    def _match(self, image: ImageArray) -> int:
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

    def _scan(self, image: ImageArray) -> list[int]:
        image = self.pre_process(image)
        if self.grids is None:
            raise RuntimeError
        image_list = [crop(image, button.area) for button in self.grids.buttons]

        return [self._match(image) for image in image_list]

    @override
    def limit_value(self, value: ScannerLimitValue) -> int:
        if not isinstance(value, int):
            message = "fleet limitation must be an integer"
            raise TypeError(message)
        return int(limit_in(value, 0, 6))


class StatusScanner(Scanner[str]):
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

    def _match(self, image: ImageArray) -> str:
        for template, status in self.templates.items():
            if template.match(image, similarity=0.75):
                return status

        return "free"

    def _scan(self, image: ImageArray) -> list[str]:
        if self.grids is None:
            raise RuntimeError
        image_list = [crop(image, button.area) for button in self.grids.buttons]

        return [self._match(image) for image in image_list]

    def limit_value(self, value: ScannerLimitValue) -> str:
        if not isinstance(value, str):
            message = "status limitation must be a string"
            raise TypeError(message)
        return value if value in self.value_list else "any"


class ShipScanner(Scanner[Ship]):
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
        self.limitaion: dict[ScannerName, ShipLimitValue] = {
            "level": (1, 125),
            "emotion": (0, 150),
            "rarity": "any",
            "fleet": 0,
            "status": "any",
        }

        self.level_scanner = LevelScanner()
        self.emotion_scanner = EmotionScanner()
        self.rarity_scanner = RarityScanner()
        self.fleet_scanner = FleetScanner()
        self.status_scanner = StatusScanner()
        self.sub_scanners: dict[ScannerName, Scanner[int] | Scanner[str]] = {
            "level": self.level_scanner,
            "emotion": self.emotion_scanner,
            "rarity": self.rarity_scanner,
            "fleet": self.fleet_scanner,
            "status": self.status_scanner,
        }

        self.set_limitation(level=level, emotion=emotion, rarity=rarity, fleet=fleet, status=status)

    def _scan(self, image: ImageArray) -> list[Ship]:
        for scanner in self.sub_scanners.values():
            scanner.scan(image, cached=True)

        grids = self.grids
        if grids is None:
            raise RuntimeError
        candidates: list[Ship] = [
            Ship(level=level, emotion=emotion, rarity=rarity, fleet=fleet, status=status, button=button)
            for level, emotion, rarity, fleet, status, button in zip(
                self.level_scanner.results,
                self.emotion_scanner.results,
                self.rarity_scanner.results,
                self.fleet_scanner.results,
                self.status_scanner.results,
                grids.buttons,
                strict=True,
            )
        ]

        for scanner in self.sub_scanners.values():
            scanner.clear()

        return candidates

    def scan(
        self,
        image: ImageArray,
        *,
        cached: bool = False,
        output: bool = True,
    ) -> list[Ship] | None:
        ships = super().scan(image, cached=cached, output=output)
        if not cached:
            return [ship for ship in ships or [] if isinstance(ship, Ship) and ship.satisfy_limitation(self.limitaion)]
        return None

    def move(self, vector: Point) -> None:
        for scanner in self.sub_scanners.values():
            scanner.move(vector)

        super().move(vector)

    @override
    def limit_value(self, value: ScannerLimitValue) -> ScannerLimitValue:
        return value

    def _set_limitation_value(self, key: ScannerName, value: ShipLimitValue) -> None:
        if value is None:
            self.limitaion[key] = None
        elif isinstance(value, tuple):
            lower, upper = value
            lower = self.sub_scanners[key].limit_value(lower)
            upper = self.sub_scanners[key].limit_value(upper)
            if not isinstance(lower, int) or not isinstance(upper, int):
                message = f"{key} range limitation must contain integers"
                raise TypeError(message)
            self.limitaion[key] = (lower, upper)
        elif isinstance(value, list):
            self.limitaion[key] = [self.sub_scanners[key].limit_value(v) for v in value]
        else:
            self.limitaion[key] = self.sub_scanners[key].limit_value(value)

    def enable(self, *args: ScannerName) -> None:
        for name, scanner in self.sub_scanners.items():
            if name in args:
                scanner.enable()

    def disable(self, *args: ScannerName) -> None:
        for name, scanner in self.sub_scanners.items():
            if name in args:
                scanner.disable()

    def set_limitation(self, **kwargs: Unpack[ShipScannerSettings]) -> None:
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
        super().__init__(rarity=rarity, level=level, emotion=emotion, fleet=fleet, status=status)
        self.scan_zone: Area = (93, 76, 1218, 719)
        self.card_bottom: list[int] = []

    def multi_scan(self, image: ImageArray) -> None:
        """用舰船卡片间低方差空隙的位移估算滚动偏移，再同步移动扫描网格。"""
        scan_image = crop(image, self.scan_zone, copy=False)

        def find_bound(image: ImageArray) -> list[int]:
            gray = np.asarray(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), dtype=np.uint8)
            std = np.std(gray, axis=1)
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

        self.move((0, int(offset_rough)))

    def scan_one_fleet(self, fleet: int | None = None) -> list[Ship]:
        raise NotImplementedError

    def scan_whole_dock(self) -> list[Ship]:
        raise NotImplementedError
