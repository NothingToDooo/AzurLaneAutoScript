from importlib import import_module

from module.base.decorator import cached_property


def _al_ocr_class():
    """按需加载重 OCR 依赖。"""
    return import_module("module.ocr.al_ocr").AlOcr


class OcrModel:
    @cached_property
    def azur_lane(self):
        # 目录：./bin/cnocr_models/azur_lane
        # 大小：3.25MB
        # 模型：densenet-lite-gru
        # 训练轮次：15
        # 验证准确率：99.43%
        # 字体：Impact、AgencyFB-Regular、MStiffHeiHK-UltraBold。
        # 字符集：数字、大写英文字母、冒号、斜杠和连字符，不包含字母 O 和空格。
        # 类别数：39
        al_ocr_class = _al_ocr_class()
        return al_ocr_class(model_name="densenet-lite-gru", root="./bin/cnocr_models/azur_lane")

    @cached_property
    def cnocr(self):
        # 目录：./bin/cnocr_models/cnocr
        # 大小：9.51MB
        # 模型：densenet-lite-gru
        # 训练轮次：39
        # 验证准确率：99.04%
        # 字体：多字体。
        # 字符集：数字、英文、中文、符号和空格。
        # 类别数：6426
        al_ocr_class = _al_ocr_class()
        return al_ocr_class(model_name="densenet-lite-gru", root="./bin/cnocr_models/cnocr")


OCR_MODEL = OcrModel()
