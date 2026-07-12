import re
import sys
from collections import Counter
from dataclasses import dataclass
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from module.base.decorator import del_cached_property
from module.logger import logger
from module.ocr.models import OCR_MODEL

if TYPE_CHECKING:
    from module.base.type_alias import FilePath


@dataclass(frozen=True, slots=True)
class ResourceTypeSnapshot:
    resource_type: str
    registered: int
    loaded: int


@dataclass(frozen=True, slots=True)
class ResourceSnapshot:
    registered: int
    loaded: int
    by_type: tuple[ResourceTypeSnapshot, ...]
    last_released: int


def get_assets_from_file(file: FilePath, regex: re.Pattern[str]) -> set[str]:
    assets = set()
    with Path(file).open(encoding="utf-8") as f:
        for row in f:
            result = regex.search(row)
            if result:
                assets.add(result.group(1))
    return assets


@cache
def _preserved_ui_assets() -> frozenset[str]:
    assets = set()
    assets |= get_assets_from_file(file="./module/ui/assets.py", regex=re.compile(r"^([A-Za-z][A-Za-z0-9_]+) = "))
    assets |= get_assets_from_file(file="./module/ui/ui.py", regex=re.compile(r"\(([A-Z][A-Z0-9_]+),"))
    assets |= get_assets_from_file(file="./module/handler/info_handler.py", regex=re.compile(r"\(([A-Z][A-Z0-9_]+),"))
    # MAIN_CHECK 与 MAIN_GOTO_CAMPAIGN 共用资源，无需重复保留。
    return frozenset(assets)


class Resource:
    instances: ClassVar[dict[FilePath, Resource]] = {}
    cached: ClassVar[tuple[str, ...]] = ()
    last_released: ClassVar[int] = 0

    _image_state_fields: ClassVar[tuple[str, ...]] = (
        "_image",
        "image",
        "_image_binary",
        "image_binary",
        "_image_luma",
        "image_luma",
    )

    def resource_add(self, key: FilePath) -> None:
        Resource.instances[key] = self

    def resource_release(self) -> None:
        for property_name in self.cached:
            del_cached_property(self, property_name)

    @staticmethod
    def is_loaded(obj: Resource) -> bool:
        """Inspect instance state without evaluating lazy image properties."""
        try:
            state = vars(obj)
        except TypeError:
            return False
        return any(state.get(field) is not None for field in Resource._image_state_fields if field in state)

    @classmethod
    def snapshot(cls) -> ResourceSnapshot:
        """Return diagnostics for resources that are already registered."""
        resources = tuple(cls.instances.values())
        registered_by_type = Counter(type(obj).__name__ for obj in resources)
        loaded_by_type = Counter(type(obj).__name__ for obj in resources if cls.is_loaded(obj))
        by_type = tuple(
            ResourceTypeSnapshot(
                resource_type=resource_type,
                registered=registered,
                loaded=loaded_by_type[resource_type],
            )
            for resource_type, registered in sorted(registered_by_type.items())
        )
        return ResourceSnapshot(
            registered=len(resources),
            loaded=sum(loaded_by_type.values()),
            by_type=by_type,
            last_released=cls.last_released,
        )

    @classmethod
    def resource_show(cls) -> None:
        logger.hr("Show resource")
        for key, obj in cls.instances.items():
            if cls.is_loaded(obj):
                continue
            logger.info(f"{obj}: {key}")

    @staticmethod
    def parse_property[T](data: T) -> T:
        return data


def release_resources(next_task: str = "") -> None:
    # 下一任务马上使用时保留唯一的 OCR 会话，进入空闲等待时完整释放。
    if not next_task:
        OCR_MODEL.release()

    released = 0
    for obj in Resource.instances.values():
        # 保留 UI 切换需要的资源。
        if next_task and str(obj) in _preserved_ui_assets():
            continue
        was_loaded = Resource.is_loaded(obj)
        obj.resource_release()
        if was_loaded and not Resource.is_loaded(obj):
            released += 1
    Resource.last_released = released

    # 只在地图检测资源已经加载时释放，避免为了清缓存反而导入重资源。
    utils_assets = sys.modules.get("module.map_detection.utils_assets")
    if utils_assets is not None:
        attr_list = [
            "ui_mask",
            "ui_mask_os",
            "ui_mask_stroke",
            "ui_mask_in_map",
            "ui_mask_os_in_map",
            "tile_center_image",
            "tile_corner_image",
            "tile_corner_image_list",
        ]
        for attr in attr_list:
            del_cached_property(utils_assets.ASSETS, attr)
