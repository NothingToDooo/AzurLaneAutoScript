from math import isfinite
from numbers import Real
from typing import ClassVar, cast

import cv2
import numpy as np
from cnocr import CnOcr
from cnocr.utils import data_dir
from PIL import Image

from module.logger import logger
from module.ocr.result import RawOcrResult

_DEFAULT_OCR_ROOT = data_dir()
logger.info("OCR dependencies loaded")


class AlOcr(CnOcr):
    CNOCR_CONTEXT = "cpu"
    MODEL_NAME_ALIASES: ClassVar[dict[str, str]] = {
        "densenet-lite-gru": "densenet_lite_136-gru",
    }

    def __init__(
        self,
        model_name="densenet-lite-gru",
        cand_alphabet=None,
        root=_DEFAULT_OCR_ROOT,
        context="cpu",
    ):
        self._args = (model_name, cand_alphabet, root, context)
        self._model_name = self._normalize_model_name(model_name)
        self._model_loaded = False

    @classmethod
    def _normalize_model_name(cls, model_name) -> str:
        return cls.MODEL_NAME_ALIASES.get(model_name, model_name)

    @property
    def model_name(self) -> str:
        return self._model_name

    @staticmethod
    def _extract_raw_result(result: object) -> RawOcrResult:
        if not isinstance(result, dict):
            message = "OCR result must be a dictionary"
            raise TypeError(message)
        payload = cast("dict[object, object]", result)
        try:
            text = payload["text"]
            score = payload["score"]
        except KeyError as error:
            message = "OCR result must contain text and score"
            raise TypeError(message) from error
        if not isinstance(text, str):
            message = "OCR result text must be a string"
            raise TypeError(message)
        if isinstance(score, bool) or not isinstance(score, Real):
            message = "OCR result score must be a real number"
            raise TypeError(message)
        score = float(score)
        if not isfinite(score) or not 0 <= score <= 1:
            message = "OCR result score must be finite and between 0 and 1"
            raise ValueError(message)
        return RawOcrResult(text=text, score=score)

    def init(
        self,
        model_name="densenet-lite-gru",
        cand_alphabet=None,
        root=_DEFAULT_OCR_ROOT,
        context="cpu",
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

    def ocr(self, img_fp, rec_batch_size=1, return_cropped_image=False, **det_kwargs):
        self.ensure_loaded()
        return [
            self._extract_raw_result(item).text
            for item in super().ocr(
                img_fp,
                rec_batch_size=rec_batch_size,
                return_cropped_image=return_cropped_image,
                **det_kwargs,
            )
        ]

    def ocr_for_single_lines_raw(self, img_list, batch_size=1) -> list[RawOcrResult]:
        self.ensure_loaded()
        return [
            self._extract_raw_result(item) for item in super().ocr_for_single_lines(img_list, batch_size=batch_size)
        ]

    def set_cand_alphabet(self, cand_alphabet):
        self.ensure_loaded()
        return self.rec_model.set_cand_alphabet(cand_alphabet)

    def atomic_ocr_for_single_lines_raw(self, img_list, cand_alphabet=None) -> list[RawOcrResult]:
        self.set_cand_alphabet(cand_alphabet)
        return self.ocr_for_single_lines_raw(img_list)

    def atomic_ocr_for_single_lines(self, img_list, cand_alphabet=None):
        return [result.text for result in self.atomic_ocr_for_single_lines_raw(img_list, cand_alphabet=cand_alphabet)]

    def _preprocess_img_array(self, img):
        height, width = img.shape[:2]
        new_width = round(32 / height * width)
        img = cv2.resize(img, (new_width, 32))
        return np.expand_dims(img, 0).astype("float32") / 255.0

    def debug(self, img_list):
        img_list = [(self._preprocess_img_array(img) * 255.0).astype(np.uint8) for img in img_list]
        image = cv2.hconcat(img_list)[0, :, :]
        Image.fromarray(image).show()
