import re
import time
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Protocol

import cv2
import numpy as np

from module.base.button import Button
from module.base.decorator import cached_property
from module.base.utils import _cv_scalar, crop, extract_letters, float2str, rgb2luma
from module.logger import logger
from module.ocr.models import OCR_MODEL
from module.ocr.result import RawOcrResult, RecognitionFailureReason, RecognitionResult


class _OcrEngine(Protocol):
    @property
    def model_name(self) -> str: ...

    def atomic_ocr_for_single_lines(
        self,
        image_list: list[np.ndarray],
        cand_alphabet: str | None = None,
    ) -> list[str]: ...

    def atomic_ocr_for_single_lines_raw(
        self,
        image_list: list[np.ndarray],
        cand_alphabet: str | None = None,
    ) -> list[RawOcrResult]: ...


@dataclass(frozen=True, slots=True)
class _OcrInference:
    raw_image: np.ndarray
    processed_image: np.ndarray
    area: tuple[int, int, int, int] | None
    result: RawOcrResult


@dataclass(frozen=True, slots=True)
class _OcrInferenceBatch:
    """一次原始批量推理；耗时属于整批调用，不是各 ROI 的独立耗时。"""

    items: tuple[_OcrInference, ...]
    latency_seconds: float
    model: str


type DigitCounterValue = tuple[int, int, int]


@dataclass(frozen=True, slots=True)
class OcrOptions:
    lang: str = "azur_lane"
    letter: tuple[int, int, int] | list[int] = (255, 255, 255)
    threshold: int = 128
    alphabet: str | None = None
    name: str | None = None


def ocr_options(options=None, settings=None, *, alphabet=None) -> OcrOptions:
    options = OcrOptions(alphabet=alphabet) if options is None else options
    if alphabet is not None and options.alphabet is None:
        options = replace(options, alphabet=alphabet)
    if settings:
        options = replace(options, **settings)
    return options


class Ocr:
    SHOW_LOG = True
    SHOW_REVISE_WARNING = False

    def __init__(self, buttons, options=None, **settings):
        """buttons 接受单个 Button／区域或列表；settings 覆盖 OcrOptions 字段。"""
        options = ocr_options(options, settings)
        self.name = str(buttons) if isinstance(buttons, Button) else options.name
        self._profile = options.name or type(self).__name__
        self._buttons = buttons
        self.letter = options.letter
        self.threshold = options.threshold
        self.alphabet = options.alphabet
        self.lang = options.lang

    @property
    def cnocr(self) -> _OcrEngine:
        return OCR_MODEL.__getattribute__(self.lang)

    @property
    def buttons(self):
        buttons = self._buttons
        buttons = buttons if isinstance(buttons, list) else [buttons]
        return [button.area if isinstance(button, Button) else button for button in buttons]

    @buttons.setter
    def buttons(self, value):
        self._buttons = value

    def pre_process(self, image):
        """按目标 RGB 与阈值把 (height, width, 3) 图像映射为二维 uint8。"""
        image = extract_letters(image, letter=self.letter, threshold=self.threshold)

        return image.astype(np.uint8)

    def after_process(self, result):
        return result

    def _infer_raw(self, image, direct_ocr=False) -> _OcrInferenceBatch:
        if direct_ocr:
            raw_images = list(image)
            areas = [None] * len(raw_images)
        else:
            areas = self.buttons
            raw_images = [crop(image, area) for area in areas]
        processed_images = [self.pre_process(raw_image) for raw_image in raw_images]

        engine = self.cnocr
        start_time = time.perf_counter()
        raw_results = engine.atomic_ocr_for_single_lines_raw(processed_images, self.alphabet)
        latency_seconds = time.perf_counter() - start_time
        items = tuple(
            _OcrInference(
                raw_image=raw_image,
                processed_image=processed_image,
                area=area,
                result=result,
            )
            for raw_image, processed_image, area, result in zip(
                raw_images,
                processed_images,
                areas,
                raw_results,
                strict=True,
            )
        )
        return _OcrInferenceBatch(items=items, latency_seconds=latency_seconds, model=engine.model_name)

    def _log_recognition[T](self, result: RecognitionResult[T]) -> None:
        if not self.SHOW_LOG:
            return
        attributes = {
            "text": result.normalized_text,
            "raw_text": result.raw_text,
            "profile": result.profile,
            "score": result.score,
            "valid": result.valid,
            "reason": result.reason.value if result.reason is not None else None,
        }
        logger.attr(
            name=f"{result.profile} {float2str(result.latency_seconds)}s",
            text=attributes,
        )

    def ocr(self, image, direct_ocr=False):
        """单区域返回字符串，多区域返回字符串列表。
        direct_ocr=True 时 image 是区域图像列表，仅跳过按 buttons 裁剪。
        """
        start_time = time.time()

        if direct_ocr:
            image_list = [self.pre_process(i) for i in image]
        else:
            image_list = [self.pre_process(crop(image, area)) for area in self.buttons]

        result_list = self.cnocr.atomic_ocr_for_single_lines(image_list, self.alphabet)
        result_list = ["".join(result) for result in result_list]
        result_list = [self.after_process(result) for result in result_list]

        if len(self.buttons) == 1:
            result_list = result_list[0]
        if self.SHOW_LOG:
            logger.attr(name=f"{self.name} {float2str(time.time() - start_time)}s", text=str(result_list))

        return result_list


class OcrYuv(Ocr):
    """在 RGB 图像的 YUV 亮度通道上识别。"""

    @cached_property
    def letter_y(self):
        arr = np.array([[self.letter]], dtype=np.uint8)
        return rgb2luma(arr)[0][0]

    def pre_process(self, image):
        """输入 (height, width, 3) RGB，返回二维 uint8 亮度差图。"""
        y = rgb2luma(image)
        letter_y = (np.ones(y.shape) * self.letter_y).astype(np.uint8)
        diff = cv2.absdiff(y, letter_y)
        return cv2.multiply(diff, _cv_scalar((255.0 / self.threshold,) * 4))


class Digit(Ocr):
    """识别单个或多个数字区域，返回 int 或 int 列表。"""

    def __init__(self, buttons, options=None, **settings):
        super().__init__(buttons, options=ocr_options(options, settings, alphabet="0123456789IDSB"))

    def after_process(self, result):
        result = super().after_process(result)
        result = result.replace("I", "1").replace("D", "0").replace("S", "5")
        result = result.replace("B", "8")

        prev = result
        result = int(result) if result else 0
        if self.SHOW_REVISE_WARNING and str(result) != prev:
            logger.warning(f'OCR {self.name}: Result "{prev}" is revised to "{result}"')

        return result

    def _parse_result(
        self,
        raw: RawOcrResult,
        *,
        latency_seconds: float,
        model: str,
    ) -> RecognitionResult[int]:
        if not raw.text:
            return RecognitionResult(
                raw_text=raw.text,
                normalized_text="",
                score=raw.score,
                value=None,
                valid=False,
                reason=RecognitionFailureReason.EMPTY_TEXT,
                latency_seconds=latency_seconds,
                profile=self._profile,
                model=model,
            )

        try:
            value = self.after_process(raw.text)
        except ValueError:
            return RecognitionResult(
                raw_text=raw.text,
                normalized_text=raw.text,
                score=raw.score,
                value=None,
                valid=False,
                reason=RecognitionFailureReason.FORMAT_MISMATCH,
                latency_seconds=latency_seconds,
                profile=self._profile,
                model=model,
            )
        if type(value) is not int:
            return RecognitionResult(
                raw_text=raw.text,
                normalized_text=raw.text,
                score=raw.score,
                value=None,
                valid=False,
                reason=RecognitionFailureReason.FORMAT_MISMATCH,
                latency_seconds=latency_seconds,
                profile=self._profile,
                model=model,
            )
        return RecognitionResult(
            raw_text=raw.text,
            normalized_text=str(value),
            score=raw.score,
            value=value,
            valid=True,
            reason=None,
            latency_seconds=latency_seconds,
            profile=self._profile,
            model=model,
        )

    def recognize(self, image, direct_ocr=False) -> RecognitionResult[int] | list[RecognitionResult[int]]:
        batch = self._infer_raw(image, direct_ocr=direct_ocr)
        results = [
            self._parse_result(item.result, latency_seconds=batch.latency_seconds, model=batch.model)
            for item in batch.items
        ]
        for result in results:
            self._log_recognition(result)
        if len(batch.items) == 1:
            return results[0]
        return results


class DigitYuv(Digit, OcrYuv):
    pass


class DigitCounter(Ocr):
    def __init__(self, buttons, options=None, **settings):
        super().__init__(buttons, options=ocr_options(options, settings, alphabet="0123456789/IDSB"))

    def after_process(self, result):
        result = super().after_process(result)
        result = result.replace("I", "1").replace("D", "0").replace("S", "5")
        return result.replace("B", "8")

    def _parse_result(
        self,
        raw: RawOcrResult,
        *,
        latency_seconds: float,
        model: str,
        expected_total: int | None = None,
    ) -> RecognitionResult[DigitCounterValue]:
        if not raw.text:
            return RecognitionResult(
                raw_text=raw.text,
                normalized_text="",
                score=raw.score,
                value=None,
                valid=False,
                reason=RecognitionFailureReason.EMPTY_TEXT,
                latency_seconds=latency_seconds,
                profile=self._profile,
                model=model,
            )

        normalized_text = self.after_process(raw.text)
        match = re.fullmatch(r"(\d+)/(\d+)", normalized_text)
        if match is None:
            return RecognitionResult(
                raw_text=raw.text,
                normalized_text=normalized_text,
                score=raw.score,
                value=None,
                valid=False,
                reason=RecognitionFailureReason.FORMAT_MISMATCH,
                latency_seconds=latency_seconds,
                profile=self._profile,
                model=model,
            )

        current, total = (int(component) for component in match.groups())
        if current > total:
            return RecognitionResult(
                raw_text=raw.text,
                normalized_text=normalized_text,
                score=raw.score,
                value=None,
                valid=False,
                reason=RecognitionFailureReason.CURRENT_EXCEEDS_TOTAL,
                latency_seconds=latency_seconds,
                profile=self._profile,
                model=model,
            )
        if expected_total is not None and total != expected_total:
            return RecognitionResult(
                raw_text=raw.text,
                normalized_text=normalized_text,
                score=raw.score,
                value=None,
                valid=False,
                reason=RecognitionFailureReason.UNEXPECTED_TOTAL,
                latency_seconds=latency_seconds,
                profile=self._profile,
                model=model,
            )
        return RecognitionResult(
            raw_text=raw.text,
            normalized_text=normalized_text,
            score=raw.score,
            value=(current, total - current, total),
            valid=True,
            reason=None,
            latency_seconds=latency_seconds,
            profile=self._profile,
            model=model,
        )

    def recognize(
        self,
        image,
        direct_ocr=False,
        *,
        expected_total: int | None = None,
    ) -> RecognitionResult[DigitCounterValue]:
        roi_count = len(image) if direct_ocr else len(self.buttons)
        if roi_count != 1:
            message = "DigitCounter.recognize() accepts exactly one ROI"
            raise ValueError(message)
        batch = self._infer_raw(image, direct_ocr=direct_ocr)
        result = self._parse_result(
            batch.items[0].result,
            latency_seconds=batch.latency_seconds,
            model=batch.model,
            expected_total=expected_total,
        )
        self._log_recognition(result)
        return result

    def ocr(self, image, direct_ocr=False):
        """仅支持单个区域；把 `14/15` 返回为 (current, remain, total)。"""
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        result = result_list[0] if isinstance(result_list, list) else result_list

        result = re.search(r"(\d+)/(\d+)", result)
        if result:
            result = [int(s) for s in result.groups()]
            current, total = int(result[0]), int(result[1])
            current = min(current, total)
            return current, total - current, total
        logger.warning(f"Unexpected ocr result: {result_list}")
        return 0, 0, 0


class DigitCounterYuv(DigitCounter, OcrYuv):
    pass


class Duration(Ocr):
    def __init__(self, buttons, options=None, **settings):
        super().__init__(buttons, options=ocr_options(options, settings, alphabet="0123456789:IDSB"))

    def after_process(self, result):
        result = super().after_process(result)
        result = result.replace("I", "1").replace("D", "0").replace("S", "5")
        return result.replace("B", "8")

    def _parse_result(
        self,
        raw: RawOcrResult,
        *,
        latency_seconds: float,
        model: str,
    ) -> RecognitionResult[timedelta]:
        if not raw.text:
            return RecognitionResult(
                raw_text=raw.text,
                normalized_text="",
                score=raw.score,
                value=None,
                valid=False,
                reason=RecognitionFailureReason.EMPTY_TEXT,
                latency_seconds=latency_seconds,
                profile=self._profile,
                model=model,
            )

        normalized_text = self.after_process(raw.text)
        match = re.fullmatch(r"(\d{1,2}):(\d{2}):(\d{2})", normalized_text)
        if match is None:
            match = re.fullmatch(r"(\d{1,2})(\d{2})(\d{2})", normalized_text)
        if match is None:
            return RecognitionResult(
                raw_text=raw.text,
                normalized_text=normalized_text,
                score=raw.score,
                value=None,
                valid=False,
                reason=RecognitionFailureReason.FORMAT_MISMATCH,
                latency_seconds=latency_seconds,
                profile=self._profile,
                model=model,
            )

        hours, minutes, seconds = (int(component) for component in match.groups())
        if minutes > 59 or seconds > 59:
            return RecognitionResult(
                raw_text=raw.text,
                normalized_text=normalized_text,
                score=raw.score,
                value=None,
                valid=False,
                reason=RecognitionFailureReason.TIME_COMPONENT_OUT_OF_RANGE,
                latency_seconds=latency_seconds,
                profile=self._profile,
                model=model,
            )
        return RecognitionResult(
            raw_text=raw.text,
            normalized_text=normalized_text,
            score=raw.score,
            value=timedelta(hours=hours, minutes=minutes, seconds=seconds),
            valid=True,
            reason=None,
            latency_seconds=latency_seconds,
            profile=self._profile,
            model=model,
        )

    def recognize(self, image, direct_ocr=False) -> RecognitionResult[timedelta] | list[RecognitionResult[timedelta]]:
        batch = self._infer_raw(image, direct_ocr=direct_ocr)
        results = [
            self._parse_result(item.result, latency_seconds=batch.latency_seconds, model=batch.model)
            for item in batch.items
        ]
        for result in results:
            self._log_recognition(result)
        if len(batch.items) == 1:
            return results[0]
        return results

    def ocr(self, image, direct_ocr=False):
        """识别 `01:30:00` 形式的时长，单区域返回 timedelta，多区域返回列表。"""
        result_list = super().ocr(image, direct_ocr=direct_ocr)
        if not isinstance(result_list, list):
            result_list = [result_list]
        result_list = [self.parse_time(result) for result in result_list]
        if len(self.buttons) == 1:
            result_list = result_list[0]
        return result_list

    @staticmethod
    def parse_time(string):
        result = re.search(r"(\d{1,2}):?(\d{2}):?(\d{2})", string)
        if result:
            result = [int(s) for s in result.groups()]
            return timedelta(hours=result[0], minutes=result[1], seconds=result[2])
        logger.warning(f"Invalid duration: {string}")
        return timedelta(hours=0, minutes=0, seconds=0)


class DurationYuv(Duration, OcrYuv):
    pass
