import re
import sys
from pathlib import Path

import module.config.server as server
from module.base.decorator import cached_property, del_cached_property
from module.logger import logger
from module.ocr.models import OCR_MODEL


def get_assets_from_file(file, regex):
    assets = set()
    with Path(file).open(encoding="utf-8") as f:
        for row in f:
            result = regex.search(row)
            if result:
                assets.add(result.group(1))
    return assets


class PreservedAssets:
    @cached_property
    def ui(self):
        assets = set()
        assets |= get_assets_from_file(file="./module/ui/assets.py", regex=re.compile(r"^([A-Za-z][A-Za-z0-9_]+) = "))
        assets |= get_assets_from_file(file="./module/ui/ui.py", regex=re.compile(r"\(([A-Z][A-Z0-9_]+),"))
        assets |= get_assets_from_file(
            file="./module/handler/info_handler.py", regex=re.compile(r"\(([A-Z][A-Z0-9_]+),")
        )
        # MAIN_CHECK == MAIN_GOTO_CAMPAIGN
        # assets.add('MAIN_GOTO_CAMPAIGN')
        return assets


_preserved_assets = PreservedAssets()


class Resource:
    # Class property, record all button and templates
    instances = {}
    # Instance property, record cached properties of instance
    cached = []

    def resource_add(self, key):
        Resource.instances[key] = self

    def resource_release(self):
        for cache in self.cached:
            del_cached_property(self, cache)

    @classmethod
    def is_loaded(cls, obj):
        unloaded = (hasattr(obj, "_image") and obj._image is None) or (hasattr(obj, "image") and obj.image is None)
        return not unloaded

    @classmethod
    def resource_show(cls):
        logger.hr("Show resource")
        for key, obj in cls.instances.items():
            if cls.is_loaded(obj):
                continue
            logger.info(f"{obj}: {key}")

    @staticmethod
    def parse_property(data, s=None):
        """
        Parse properties of Button or Template object input.
        Such as `area`, `color` and `button`.

        Args:
            data: Dict or str
            s (str): Load from given a server or load from global attribute `server.server`
        """
        if s is None:
            s = server.server
        if isinstance(data, dict):
            return data[s]
        return data


def release_resources(next_task=""):
    # 释放 OCR 模型。通常会加载 2 个模型，每个约 20MB。
    if "Opsi" in next_task or "commission" in next_task:
        # 马上会用到 OCR，不释放。
        models = []
    elif next_task:
        # 保留常用的 azur_lane 模型。
        models = ["cnocr", "jp", "tw"]
    else:
        models = ["azur_lane", "cnocr", "jp", "tw"]
    for model in models:
        del_cached_property(OCR_MODEL, model)

    # 释放已加载资源缓存。
    # module.ui 约 80 个资源，占用约 3MB。
    # Alas 约 800 个资源，但不会全部加载。
    # Template 图片更大，每张约 6MB。
    for obj in Resource.instances.values():
        # 保留 UI 切换需要的资源。
        if next_task and str(obj) in _preserved_assets.ui:
            continue
        # if Resource.is_loaded(obj):
        #     logger.info(f'Release {obj}')
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

    # 多数情况下收益不大，暂时不主动调用。
    # gc.collect()
