from importlib import import_module
from typing import TYPE_CHECKING, cast

from module.base.decorator import cached_property

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.ocr.al_ocr import AlOcr


def _al_ocr_class() -> type[AlOcr]:
    """按需加载重 OCR 依赖。"""
    return cast("type[AlOcr]", import_module("module.ocr.al_ocr").AlOcr)


class OcrModel:
    def __init__(self, loader: Callable[[], type[AlOcr]] = _al_ocr_class) -> None:
        self._loader = loader

    @cached_property
    def azur_lane(self) -> AlOcr:
        al_ocr_class = self._loader()
        return al_ocr_class(model_name="densenet-lite-gru", root="./bin/cnocr_models/azur_lane")

    @cached_property
    def cnocr(self) -> AlOcr:
        al_ocr_class = self._loader()
        return al_ocr_class(model_name="densenet-lite-gru", root="./bin/cnocr_models/cnocr")


OCR_MODEL = OcrModel()
