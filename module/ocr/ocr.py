import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Protocol, TypedDict, Unpack, cast

import cv2
import numpy as np

import module.ocr.failure_store as failure_store_module
from module.base.button import Button
from module.base.decorator import cached_property
from module.base.type_alias import Area, Color, ImageArray, NumericArray, Scalar
from module.base.utils import _cv_scalar, crop, extract_letters, float2str, rgb2luma
from module.logger import logger
from module.ocr.models import OCR_MODEL
from module.ocr.result import RawOcrResult, RecognitionFailureReason, RecognitionResult


class _OcrEngine(Protocol):
    @property
    def model_name(self) -> str: ...

    def atomic_ocr_for_single_lines(
        self,
        image_list: list[ImageArray],
        cand_alphabet: str | None = None,
    ) -> list[str]: ...

    def atomic_ocr_for_single_lines_raw(
        self,
        image_list: list[ImageArray],
        cand_alphabet: str | None = None,
    ) -> list[RawOcrResult]: ...


@dataclass(frozen=True, slots=True)
class _OcrInference:
    raw_image: ImageArray
    processed_image: ImageArray
    area: Area | None
    result: RawOcrResult


@dataclass(frozen=True, slots=True)
class _OcrInferenceBatch:
    """一次原始批量推理；耗时属于整批调用，不是各 ROI 的独立耗时。"""

    items: tuple[_OcrInference, ...]
    latency_seconds: float
    model: str


type DigitCounterValue = tuple[int, int, int]
type OcrArea = tuple[Scalar, Scalar, Scalar, Scalar] | NumericArray
type OcrRegion = Button | OcrArea
type OcrRegions = OcrRegion | Sequence[OcrRegion]
type OcrInput = ImageArray | Sequence[ImageArray]


class OcrOptions(TypedDict, total=False):
    lang: str
    letter: Color
    threshold: int
    alphabet: str | None
    name: str | None


@dataclass(frozen=True, slots=True)
class _ResolvedOcrOptions:
    lang: str = "azur_lane"
    letter: Color = (255, 255, 255)
    threshold: int = 128
    alphabet: str | None = None
    name: str | None = None


def ocr_options(
    options: OcrOptions | _ResolvedOcrOptions | None = None,
    settings: OcrOptions | None = None,
    *,
    alphabet: str | None = None,
) -> _ResolvedOcrOptions:
    if isinstance(options, _ResolvedOcrOptions):
        resolved = options
    else:
        resolved = _ResolvedOcrOptions(
            lang="azur_lane" if options is None else options.get("lang", "azur_lane"),
            letter=(255, 255, 255) if options is None else options.get("letter", (255, 255, 255)),
            threshold=128 if options is None else options.get("threshold", 128),
            alphabet=None if options is None else options.get("alphabet"),
            name=None if options is None else options.get("name"),
        )
    if alphabet is not None and resolved.alphabet is None:
        resolved = replace(resolved, alphabet=alphabet)
    if settings:
        resolved = replace(
            resolved,
            lang=settings.get("lang", resolved.lang),
            letter=settings.get("letter", resolved.letter),
            threshold=settings.get("threshold", resolved.threshold),
            alphabet=settings.get("alphabet", resolved.alphabet),
            name=settings.get("name", resolved.name),
        )
    return resolved


class Ocr[OcrValueT = str]:
    SHOW_LOG = True
    SHOW_REVISE_WARNING = False

    @staticmethod
    def _normalize_regions(buttons: OcrRegions) -> list[OcrRegion]:
        if isinstance(buttons, Button):
            return [buttons]
        if isinstance(buttons, np.ndarray):
            return [cast("OcrArea", buttons)]
        if (
            isinstance(buttons, tuple)
            and len(buttons) == 4
            and all(isinstance(value, (int, float, np.integer, np.floating)) for value in buttons)
        ):
            return [cast("OcrArea", buttons)]
        return list(cast("Sequence[OcrRegion]", buttons))

    def __init__(
        self,
        buttons: OcrRegions,
        options: OcrOptions | _ResolvedOcrOptions | None = None,
        **settings: Unpack[OcrOptions],
    ) -> None:
        """buttons 接受单个 Button／区域或列表；settings 覆盖 OcrOptions 字段。"""
        options = ocr_options(options, settings)
        self.name = str(buttons) if isinstance(buttons, Button) else options.name
        self._profile = options.name or type(self).__name__
        self._buttons = self._normalize_regions(buttons)
        self.letter = options.letter
        self.threshold = options.threshold
        self.alphabet = options.alphabet
        self.lang = options.lang

    @property
    def cnocr(self) -> _OcrEngine:
        return getattr(OCR_MODEL, self.lang)

    @property
    def buttons(self) -> list[Area]:
        return [region.area if isinstance(region, Button) else region for region in self._buttons]

    @buttons.setter
    def buttons(self, value: OcrRegions) -> None:
        self._buttons = self._normalize_regions(value)

    def pre_process(self, image: ImageArray) -> ImageArray:
        """按目标 RGB 与阈值把 (height, width, 3) 图像映射为二维 uint8。"""
        image = extract_letters(image, letter=self.letter, threshold=self.threshold)

        return image.astype(np.uint8)

    @staticmethod
    def _identity_text(result: str) -> str:
        return result

    def after_process(self, result: str) -> OcrValueT:
        return cast("OcrValueT", self._identity_text(result))

    def _raw_images(self, image: OcrInput, *, direct_ocr: bool) -> tuple[list[ImageArray], list[Area | None]]:
        if direct_ocr:
            if isinstance(image, np.ndarray):
                message = "direct OCR expects a sequence of ROI images"
                raise TypeError(message)
            raw_images = list(cast("Sequence[ImageArray]", image))
            return raw_images, [None] * len(raw_images)
        if not isinstance(image, np.ndarray):
            message = "button-based OCR expects one source image"
            raise TypeError(message)
        source_image = cast("ImageArray", image)
        areas = self.buttons
        area_options: list[Area | None] = list(areas)
        return [crop(source_image, area) for area in areas], area_options

    def _infer_raw(self, image: OcrInput, *, direct_ocr: bool = False) -> _OcrInferenceBatch:
        raw_images, areas = self._raw_images(image, direct_ocr=direct_ocr)
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

    def _ocr_texts(self, image: OcrInput, *, direct_ocr: bool) -> list[str]:
        raw_images, _ = self._raw_images(image, direct_ocr=direct_ocr)
        processed_images = [self.pre_process(raw_image) for raw_image in raw_images]
        return ["".join(result) for result in self.cnocr.atomic_ocr_for_single_lines(processed_images, self.alphabet)]

    def _finish_ocr(
        self,
        results: list[OcrValueT],
        *,
        start_time: float,
    ) -> OcrValueT | list[OcrValueT]:
        collapsed = results[0] if len(results) == 1 else results
        if self.SHOW_LOG:
            logger.attr(name=f"{self.name} {float2str(time.time() - start_time)}s", text=str(collapsed))
        return collapsed

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

    def _record_failure[T](
        self,
        result: RecognitionResult[T],
        inference: _OcrInference,
        failure_store: failure_store_module.OcrFailureRecorder | None,
        *,
        expected_total: int | None = None,
    ) -> None:
        if result.valid or failure_store is None:
            return
        letter = tuple(int(channel) for channel in self.letter)
        if len(letter) != 3:
            message = "letter must contain exactly three channels"
            raise ValueError(message)
        area = inference.area
        if area is not None and len(area) != 4:
            message = "OCR area must contain exactly four coordinates"
            raise ValueError(message)
        recorded_area = None if area is None else (int(area[0]), int(area[1]), int(area[2]), int(area[3]))
        sample = failure_store_module.OcrFailureSample(
            result=result,
            raw_image=inference.raw_image,
            processed_image=inference.processed_image,
            area=recorded_area,
            alphabet=self.alphabet,
            letter=letter,
            threshold=self.threshold,
            expected_total=expected_total,
        )
        try:
            failure_store.record(sample)
        except OSError as error:
            logger.warning("OCR failure recorder raised %s; recognition result is unchanged", type(error).__name__)

    def ocr(self, image: OcrInput, *, direct_ocr: bool = False) -> OcrValueT | list[OcrValueT]:
        """单区域返回一个处理值，多区域返回同类型值列表。
        direct_ocr=True 时 image 是区域图像列表，仅跳过按 buttons 裁剪。
        """
        start_time = time.time()

        results: list[OcrValueT] = [
            self.after_process(result) for result in self._ocr_texts(image, direct_ocr=direct_ocr)
        ]
        return self._finish_ocr(results, start_time=start_time)

    def ocr_single(self, image: OcrInput, *, direct_ocr: bool = False) -> OcrValueT:
        """识别且只识别一个区域；区域数量不为一时拒绝模糊的返回形状。"""
        roi_count = len(image) if direct_ocr else len(self.buttons)
        if roi_count != 1:
            message = "Ocr.ocr_single() accepts exactly one ROI"
            raise ValueError(message)
        return cast("OcrValueT", self.ocr(image, direct_ocr=direct_ocr))


class OcrYuv[OcrValueT = str](Ocr[OcrValueT]):
    """在 RGB 图像的 YUV 亮度通道上识别。"""

    @cached_property
    def letter_y(self) -> np.uint8:
        arr = np.array([[self.letter]], dtype=np.uint8)
        return rgb2luma(arr)[0][0]

    def pre_process(self, image: ImageArray) -> ImageArray:
        """输入 (height, width, 3) RGB，返回二维 uint8 亮度差图。"""
        y = rgb2luma(image)
        letter_y = (np.ones(y.shape) * self.letter_y).astype(np.uint8)
        diff = cv2.absdiff(y, letter_y)
        return cv2.multiply(diff, _cv_scalar((255.0 / self.threshold,) * 4)).astype(np.uint8, copy=False)


class Digit(Ocr[int]):
    """识别单个或多个数字区域，返回 int 或 int 列表。"""

    def __init__(
        self,
        buttons: OcrRegions,
        options: OcrOptions | _ResolvedOcrOptions | None = None,
        **settings: Unpack[OcrOptions],
    ) -> None:
        super().__init__(buttons, options=ocr_options(options, settings, alphabet="0123456789IDSB"))

    def after_process(self, result: str) -> int:
        result = result.replace("I", "1").replace("D", "0").replace("S", "5")
        result = result.replace("B", "8")

        prev = result
        value = int(result) if result else 0
        if self.SHOW_REVISE_WARNING and str(value) != prev:
            logger.warning(f'OCR {self.name}: Result "{prev}" is revised to "{value}"')

        return value

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

    def recognize(
        self,
        image: OcrInput,
        *,
        direct_ocr: bool = False,
        failure_store: failure_store_module.OcrFailureRecorder | None = None,
    ) -> RecognitionResult[int] | list[RecognitionResult[int]]:
        batch = self._infer_raw(image, direct_ocr=direct_ocr)
        results = [
            self._parse_result(item.result, latency_seconds=batch.latency_seconds, model=batch.model)
            for item in batch.items
        ]
        for item, result in zip(batch.items, results, strict=True):
            self._log_recognition(result)
            self._record_failure(result, item, failure_store)
        if len(batch.items) == 1:
            return results[0]
        return results


class DigitYuv(Digit, OcrYuv[int]):
    pass


class DigitCounter(Ocr[DigitCounterValue]):
    def __init__(
        self,
        buttons: OcrRegions,
        options: OcrOptions | _ResolvedOcrOptions | None = None,
        **settings: Unpack[OcrOptions],
    ) -> None:
        super().__init__(buttons, options=ocr_options(options, settings, alphabet="0123456789/IDSB"))

    @staticmethod
    def normalize_text(result: str) -> str:
        result = result.replace("I", "1").replace("D", "0").replace("S", "5")
        return result.replace("B", "8")

    def after_process(self, result: str) -> DigitCounterValue:
        normalized_text = self.normalize_text(result)
        match = re.search(r"(\d+)/(\d+)", normalized_text)
        if match is None:
            logger.warning(f"Unexpected ocr result: {normalized_text}")
            return 0, 0, 0
        current, total = (int(component) for component in match.groups())
        current = min(current, total)
        return current, total - current, total

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

        normalized_text = self.normalize_text(raw.text)
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
        image: OcrInput,
        *,
        direct_ocr: bool = False,
        expected_total: int | None = None,
        failure_store: failure_store_module.OcrFailureRecorder | None = None,
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
        self._record_failure(result, batch.items[0], failure_store, expected_total=expected_total)
        return result

    def ocr(self, image: OcrInput, *, direct_ocr: bool = False) -> DigitCounterValue:
        """仅支持单个区域；把 `14/15` 返回为 (current, remain, total)。"""
        roi_count = len(image) if direct_ocr else len(self.buttons)
        if roi_count != 1:
            message = "DigitCounter.ocr() accepts exactly one ROI"
            raise ValueError(message)
        return cast("DigitCounterValue", super().ocr(image, direct_ocr=direct_ocr))


class DigitCounterYuv(DigitCounter, OcrYuv[DigitCounterValue]):
    pass


class Duration(Ocr[timedelta]):
    def __init__(
        self,
        buttons: OcrRegions,
        options: OcrOptions | _ResolvedOcrOptions | None = None,
        **settings: Unpack[OcrOptions],
    ) -> None:
        super().__init__(buttons, options=ocr_options(options, settings, alphabet="0123456789:IDSB"))

    @staticmethod
    def normalize_text(result: str) -> str:
        result = result.replace("I", "1").replace("D", "0").replace("S", "5")
        return result.replace("B", "8")

    def after_process(self, result: str) -> timedelta:
        return self.parse_time(self.normalize_text(result))

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

        normalized_text = self.normalize_text(raw.text)
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

    def recognize(
        self,
        image: OcrInput,
        *,
        direct_ocr: bool = False,
        failure_store: failure_store_module.OcrFailureRecorder | None = None,
    ) -> RecognitionResult[timedelta] | list[RecognitionResult[timedelta]]:
        batch = self._infer_raw(image, direct_ocr=direct_ocr)
        results = [
            self._parse_result(item.result, latency_seconds=batch.latency_seconds, model=batch.model)
            for item in batch.items
        ]
        for item, result in zip(batch.items, results, strict=True):
            self._log_recognition(result)
            self._record_failure(result, item, failure_store)
        if len(batch.items) == 1:
            return results[0]
        return results

    @staticmethod
    def parse_time(string: str) -> timedelta:
        result = re.search(r"(\d{1,2}):?(\d{2}):?(\d{2})", string)
        if result:
            result = [int(s) for s in result.groups()]
            return timedelta(hours=result[0], minutes=result[1], seconds=result[2])
        logger.warning(f"Invalid duration: {string}")
        return timedelta(hours=0, minutes=0, seconds=0)


class DurationYuv(Duration, OcrYuv[timedelta]):
    pass
