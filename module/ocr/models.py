from importlib import import_module

from module.base.decorator import cached_property


def _al_ocr_class():
    """按需加载重 OCR 依赖。"""
    return import_module("module.ocr.al_ocr").AlOcr


class OcrModel:
    @cached_property
    def azur_lane(self):
        al_ocr_class = _al_ocr_class()
        return al_ocr_class(model_name="densenet-lite-gru", root="./bin/cnocr_models/azur_lane")

    @cached_property
    def cnocr(self):
        al_ocr_class = _al_ocr_class()
        return al_ocr_class(model_name="densenet-lite-gru", root="./bin/cnocr_models/cnocr")


OCR_MODEL = OcrModel()
