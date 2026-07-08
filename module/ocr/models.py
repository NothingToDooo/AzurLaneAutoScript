from importlib import import_module

from module.base.decorator import cached_property


def _al_ocr_class():
    """按需加载重 OCR 依赖。"""
    return import_module("module.ocr.al_ocr").AlOcr


class OcrModel:
    @cached_property
    def azur_lane(self):
        # Folder: ./bin/cnocr_models/azur_lane
        # Size: 3.25MB
        # Model: densenet-lite-gru
        # Epoch: 15
        # Validation accuracy: 99.43%
        # Font: Impact, AgencyFB-Regular, MStiffHeiHK-UltraBold
        # Charset: 0123456789ABCDEFGHIJKLMNPQRSTUVWXYZ:/- (Letter 'O' and <space> is not included)
        # _num_classes: 39
        AlOcr = _al_ocr_class()
        return AlOcr(model_name="densenet-lite-gru", root="./bin/cnocr_models/azur_lane")

    @cached_property
    def cnocr(self):
        # Folder: ./bin/cnocr_models/cnocr
        # Size: 9.51MB
        # Model: densenet-lite-gru
        # Epoch: 39
        # Validation accuracy: 99.04%
        # Font: Various
        # Charset: Number, English character, Chinese character, symbols, <space>
        # _num_classes: 6426
        AlOcr = _al_ocr_class()
        return AlOcr(model_name="densenet-lite-gru", root="./bin/cnocr_models/cnocr")


OCR_MODEL = OcrModel()
