import re
import sys
from functools import cache
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar

from module.base.decorator import del_cached_property
from module.logger import logger
from module.ocr.models import OCR_MODEL

if TYPE_CHECKING:
    from module.base.type_alias import FilePath


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

    def resource_add(self, key: FilePath) -> None:
        Resource.instances[key] = self

    def resource_release(self) -> None:
        for property_name in self.cached:
            del_cached_property(self, property_name)

    @classmethod
    def is_loaded(cls, obj: Resource) -> bool:
        missing = object()
        unloaded = getattr(obj, "_image", missing) is None or getattr(obj, "image", missing) is None
        return not unloaded

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
    # OCR 通常加载两个约 20MB 的模型；下一任务马上使用时保留对应缓存。
    if "Opsi" in next_task or "commission" in next_task:
        models = []
    elif next_task:
        models = ["cnocr"]
    else:
        models = ["azur_lane", "cnocr"]
    for model in models:
        del_cached_property(OCR_MODEL, model)

    for obj in Resource.instances.values():
        # 保留 UI 切换需要的资源。
        if next_task and str(obj) in _preserved_ui_assets():
            continue
        obj.resource_release()

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
