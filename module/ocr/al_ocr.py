from collections.abc import Collection, Sequence
from math import isfinite
from numbers import Real
from typing import TYPE_CHECKING, ClassVar, Protocol, TypedDict, Unpack, cast

import cv2
import numpy as np
from cnocr import CnOcr
from PIL import Image

from module.logger import logger
from module.ocr.result import RawOcrResult

if TYPE_CHECKING:
    from pathlib import Path

    from numpy.typing import NDArray
    from torch import Tensor

    from module.base.type_alias import ImageArray

type CnOcrImage = str | Path | Image.Image | Tensor | np.ndarray
type CnOcrLineImage = str | Path | Tensor | np.ndarray
type _CnOcrResultPayload = dict[str, str | Real | np.ndarray]
type _ModelArguments = tuple[str, Collection[str] | str | None, str]


class OcrDetectionOptions(TypedDict, total=False):
    resized_shape: int | tuple[int, int]
    preserve_aspect_ratio: bool
    min_box_size: int
    box_score_thresh: float
    batch_size: int


class _AlphabetModel(Protocol):
    def set_cand_alphabet(self, cand_alphabet: Collection[str] | str | None) -> None: ...


logger.info("OCR dependencies loaded")


class AlOcr(CnOcr):
    CNOCR_CONTEXT = "cpu"
    MODEL_NAME_ALIASES: ClassVar[dict[str, str]] = {
        "densenet-lite-gru": "densenet_lite_136-gru",
    }

    def __init__(
        self,
        model_name: str = "densenet-lite-gru",
        cand_alphabet: Collection[str] | str | None = None,
        context: str = "cpu",
    ) -> None:
        self._args: _ModelArguments = (model_name, cand_alphabet, context)
        self._model_name = self._normalize_model_name(model_name)
        self._model_loaded = False

    @classmethod
    def _normalize_model_name(cls, model_name: str) -> str:
        return cls.MODEL_NAME_ALIASES.get(model_name, model_name)

    @property
    def model_name(self) -> str:
        return self._model_name

    @staticmethod
    def _extract_raw_result(result: _CnOcrResultPayload) -> RawOcrResult:
        if not isinstance(result, dict):
            message = "OCR result must be a dictionary"
            raise TypeError(message)
        try:
            text = result["text"]
            score = result["score"]
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
        model_name: str = "densenet-lite-gru",
        cand_alphabet: Collection[str] | str | None = None,
        context: str = "cpu",
    ) -> None:
        model_name = self._normalize_model_name(model_name)
        logger.info(f"Loading OCR model: {model_name}")

        super().__init__(
            rec_model_name=model_name,
            det_model_name="",
            cand_alphabet=cand_alphabet,
            context=context or self.CNOCR_CONTEXT,
        )

    def ensure_loaded(self) -> None:
        if not self._model_loaded:
            self.init(*self._args)
            self._model_loaded = True

    def ocr_texts(
        self,
        img_fp: CnOcrImage,
        rec_batch_size: int = 1,
        *,
        return_cropped_image: bool = False,
        **det_kwargs: Unpack[OcrDetectionOptions],
    ) -> list[str]:
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

    def ocr_for_single_lines_raw(
        self,
        img_list: Sequence[CnOcrLineImage],
        batch_size: int = 1,
    ) -> list[RawOcrResult]:
        self.ensure_loaded()
        return [
            self._extract_raw_result(item)
            for item in super().ocr_for_single_lines(list(img_list), batch_size=batch_size)
        ]

    def set_cand_alphabet(self, cand_alphabet: Collection[str] | str | None) -> None:
        self.ensure_loaded()
        cast("_AlphabetModel", self.rec_model).set_cand_alphabet(cand_alphabet)

    def atomic_ocr_for_single_lines_raw(
        self,
        img_list: Sequence[CnOcrLineImage],
        cand_alphabet: Collection[str] | str | None = None,
    ) -> list[RawOcrResult]:
        self.set_cand_alphabet(cand_alphabet)
        return self.ocr_for_single_lines_raw(img_list)

    def atomic_ocr_for_single_lines(
        self,
        img_list: Sequence[CnOcrLineImage],
        cand_alphabet: Collection[str] | str | None = None,
    ) -> list[str]:
        return [result.text for result in self.atomic_ocr_for_single_lines_raw(img_list, cand_alphabet=cand_alphabet)]

    @staticmethod
    def _preprocess_img_array(img: ImageArray) -> NDArray[np.float32]:
        height, width = img.shape[:2]
        new_width = round(32 / height * width)
        resized = cv2.resize(img, (new_width, 32))
        return cast("NDArray[np.float32]", np.expand_dims(resized, 0).astype(np.float32) / np.float32(255))

    def debug(self, img_list: Sequence[ImageArray]) -> None:
        display_images = [(self._preprocess_img_array(img) * 255.0).astype(np.uint8) for img in img_list]
        image = cv2.hconcat(display_images)[0, :, :]
        Image.fromarray(image).show()
