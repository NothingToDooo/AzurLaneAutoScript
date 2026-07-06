import cv2
import numpy as np
from PIL import Image

from module.logger import logger

logger.info("Loading OCR dependencies")
from cnocr import CnOcr
from cnocr.utils import data_dir

_DEFAULT_OCR_ROOT = data_dir()


class AlOcr(CnOcr):
    CNOCR_CONTEXT = "cpu"
    MODEL_NAME_ALIASES = {
        "densenet-lite-gru": "densenet_lite_136-gru",
    }

    def __init__(
        self,
        model_name="densenet-lite-gru",
        model_epoch=None,
        cand_alphabet=None,
        root=_DEFAULT_OCR_ROOT,
        context="cpu",
        name=None,
    ):
        self._args = (model_name, model_epoch, cand_alphabet, root, context, name)
        self._model_loaded = False

    @classmethod
    def _normalize_model_name(cls, model_name):
        return cls.MODEL_NAME_ALIASES.get(model_name, model_name)

    @staticmethod
    def _extract_text(result):
        if isinstance(result, dict):
            return result.get("text", "")
        return result

    def init(
        self,
        model_name="densenet-lite-gru",
        model_epoch=None,
        cand_alphabet=None,
        root=_DEFAULT_OCR_ROOT,
        context="cpu",
        name=None,
    ):
        model_name = self._normalize_model_name(model_name)
        logger.info(f"Loading OCR model: {model_name}")
        if root != _DEFAULT_OCR_ROOT:
            logger.warning(f"Custom MXNet OCR model root is ignored by CnOcr 2.x: {root}")

        super().__init__(
            rec_model_name=model_name,
            det_model_name="",
            cand_alphabet=cand_alphabet,
            context=context or self.CNOCR_CONTEXT,
        )

    def ensure_loaded(self):
        if not self._model_loaded:
            self.init(*self._args)
            self._model_loaded = True

    def ocr(self, img_fp):
        self.ensure_loaded()
        return [self._extract_text(item) for item in super().ocr(img_fp)]

    def ocr_for_single_line(self, img_fp):
        self.ensure_loaded()
        return self._extract_text(super().ocr_for_single_line(img_fp))

    def ocr_for_single_lines(self, img_list):
        self.ensure_loaded()
        return [self._extract_text(item) for item in super().ocr_for_single_lines(img_list)]

    def set_cand_alphabet(self, cand_alphabet):
        self.ensure_loaded()
        return self.rec_model.set_cand_alphabet(cand_alphabet)

    def atomic_ocr(self, img_fp, cand_alphabet=None):
        self.set_cand_alphabet(cand_alphabet)
        return self.ocr(img_fp)

    def atomic_ocr_for_single_line(self, img_fp, cand_alphabet=None):
        self.set_cand_alphabet(cand_alphabet)
        return self.ocr_for_single_line(img_fp)

    def atomic_ocr_for_single_lines(self, img_list, cand_alphabet=None):
        self.set_cand_alphabet(cand_alphabet)
        return self.ocr_for_single_lines(img_list)

    def _preprocess_img_array(self, img):
        height, width = img.shape[:2]
        new_width = round(32 / height * width)
        img = cv2.resize(img, (new_width, 32))
        img = np.expand_dims(img, 0).astype("float32") / 255.0
        return img

    def debug(self, img_list):
        img_list = [(self._preprocess_img_array(img) * 255.0).astype(np.uint8) for img in img_list]
        image = cv2.hconcat(img_list)[0, :, :]
        Image.fromarray(image).show()
