from types import SimpleNamespace
from typing import TYPE_CHECKING, cast, override

import numpy as np
import pytest

import module.dorm.dorm as dorm_module
from module.dorm.dorm import Food, RewardDorm
from module.ocr.failure_store import OCR_FAILURE_STORE, OcrFailureRecorder
from module.ocr.result import RecognitionFailureReason, RecognitionResult

if TYPE_CHECKING:
    from collections.abc import Iterator, Sequence

    from module.base.base import _HasArea
    from module.base.button import Button
    from module.base.timer import Timer
    from module.base.type_alias import Area, ImageArray
    from module.config.config import AzurLaneConfig
    from module.device.device import Device


TEST_IMAGE = np.zeros((720, 1280, 3), dtype=np.uint8)


def _valid_digit(value: int) -> RecognitionResult[int]:
    return RecognitionResult(
        raw_text=str(value),
        normalized_text=str(value),
        score=0.95,
        value=value,
        valid=True,
        reason=None,
        latency_seconds=0.001,
        profile="OCR_DORM_FOOD",
        model="test-model",
    )


def _invalid_digit(raw_text: str = "loading") -> RecognitionResult[int]:
    return RecognitionResult(
        raw_text=raw_text,
        normalized_text=raw_text,
        score=0.1,
        value=None,
        valid=False,
        reason=RecognitionFailureReason.FORMAT_MISMATCH,
        latency_seconds=0.001,
        profile="OCR_DORM_FOOD",
        model="test-model",
    )


def _valid_fill(value: tuple[int, int, int]) -> RecognitionResult[tuple[int, int, int]]:
    current, remain, total = value
    text = f"{current}/{total}"
    return RecognitionResult(
        raw_text=text,
        normalized_text=text,
        score=0.96,
        value=(current, remain, total),
        valid=True,
        reason=None,
        latency_seconds=0.001,
        profile="OCR_DORM_FILL",
        model="test-model",
    )


def _invalid_fill(raw_text: str = "loading") -> RecognitionResult[tuple[int, int, int]]:
    return RecognitionResult(
        raw_text=raw_text,
        normalized_text=raw_text,
        score=0.1,
        value=None,
        valid=False,
        reason=RecognitionFailureReason.FORMAT_MISMATCH,
        latency_seconds=0.001,
        profile="OCR_DORM_FILL",
        model="test-model",
    )


class _FoodOcr:
    def __init__(self, results: list[RecognitionResult[int]]) -> None:
        self.buttons: tuple[Area, ...] = tuple((index, 0, index, 0) for index in range(6))
        self.results = results
        self.calls: list[tuple[tuple[int, ...], bool, OcrFailureRecorder | None]] = []

    def recognize(
        self,
        images: Sequence[ImageArray],
        *,
        direct_ocr: bool = False,
        failure_store: OcrFailureRecorder | None = None,
    ) -> RecognitionResult[int] | list[RecognitionResult[int]]:
        image_ids = tuple(int(image[0, 0, 0]) for image in images)
        self.calls.append((image_ids, direct_ocr, failure_store))
        if len(self.results) == 1:
            return self.results[0]
        return list(self.results)


class _FillOcr:
    def __init__(self, result: RecognitionResult[tuple[int, int, int]]) -> None:
        self.result = result
        self.calls: list[tuple[ImageArray, OcrFailureRecorder | None]] = []

    def recognize(
        self,
        image: ImageArray,
        *,
        failure_store: OcrFailureRecorder | None = None,
    ) -> RecognitionResult[tuple[int, int, int]]:
        self.calls.append((image, failure_store))
        return self.result


class _EmptyFoodFilter:
    def load(self, value: str) -> None:
        self.loaded = value

    @staticmethod
    def apply(food: list[Food]) -> list[Food]:
        del food
        return []


class _Dorm(RewardDorm):
    def __init__(self, has_food: list[bool], food_ocr: _FoodOcr, *, save_error: bool) -> None:
        self.config = cast("AzurLaneConfig", SimpleNamespace(Error_SaveError=save_error))
        self.device = cast("Device", SimpleNamespace(image=TEST_IMAGE))
        self._has_food = iter(has_food)
        self.cropped_areas: list[int] = []
        self.__dict__["_dorm_food_ocr"] = food_ocr

    @override
    def _dorm_has_food(self, button: Button) -> bool:
        del button
        return next(self._has_food)

    @override
    def image_crop(self, button: Button | _HasArea | Area, *, copy: bool = True) -> ImageArray:
        del copy
        if not (isinstance(button, tuple) and isinstance(button[0], int)):
            message = "test food OCR areas must be integer coordinate tuples"
            raise TypeError(message)
        slot = button[0]
        self.cropped_areas.append(slot)
        return np.full((2, 2, 3), slot, dtype=np.uint8)


class _DormFeedLoop(RewardDorm):
    def __init__(self, results: list[tuple[list[Food], int]]) -> None:
        self.config = cast("AzurLaneConfig", SimpleNamespace(Dorm_FeedFilter=""))
        self.results = iter(results)
        self.food_get_calls = 0

    @override
    def loop(self, *, skip_first: bool = True, timeout: float | Timer | None = None) -> Iterator[ImageArray]:
        del skip_first, timeout
        yield TEST_IMAGE
        yield TEST_IMAGE

    @override
    def handle_info_bar(self) -> bool:
        return False

    def dorm_food_get(self) -> tuple[list[Food], int]:
        self.food_get_calls += 1
        return next(self.results)


def test_dorm_food_get_only_recognizes_present_slots_and_accepts_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    food_ocr = _FoodOcr([_valid_digit(0), _valid_digit(11)])
    fill_ocr = _FillOcr(_valid_fill((10000, 30000, 40000)))
    monkeypatch.setattr(dorm_module, "OCR_FILL", fill_ocr)
    dorm = _Dorm([False, True, False, True, False, False], food_ocr, save_error=True)

    food, fill = dorm.dorm_food_get()

    assert [item.amount for item in food] == [0, 0, 0, 11, 0, 0]
    assert fill == 30000
    assert dorm.cropped_areas == [1, 3]
    assert food_ocr.calls == [((1, 3), True, OCR_FAILURE_STORE)]
    assert len(fill_ocr.calls) == 1
    assert fill_ocr.calls[0][0] is TEST_IMAGE
    assert fill_ocr.calls[0][1] is OCR_FAILURE_STORE


def test_dorm_food_get_does_not_submit_empty_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    food_ocr = _FoodOcr([])
    fill_ocr = _FillOcr(_valid_fill((5000, 35000, 40000)))
    monkeypatch.setattr(dorm_module, "OCR_FILL", fill_ocr)
    dorm = _Dorm([False] * 6, food_ocr, save_error=False)

    food, fill = dorm.dorm_food_get()

    assert [item.amount for item in food] == [0] * 6
    assert fill == 35000
    assert food_ocr.calls == []
    assert fill_ocr.calls == [(TEST_IMAGE, None)]


def test_dorm_food_get_retries_frame_before_fill_when_food_amount_is_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    food_ocr = _FoodOcr([_valid_digit(4), _invalid_digit()])
    fill_ocr = _FillOcr(_valid_fill((10000, 30000, 40000)))
    monkeypatch.setattr(dorm_module, "OCR_FILL", fill_ocr)
    dorm = _Dorm([True, True, False, False, False, False], food_ocr, save_error=False)

    food, fill = dorm.dorm_food_get()

    assert [item.amount for item in food] == [4, 0, 0, 0, 0, 0]
    assert fill == -1
    assert food_ocr.calls == [((0, 1), True, None)]
    assert fill_ocr.calls == []


@pytest.mark.parametrize("fill_result", [_invalid_fill(), _valid_fill((0, 0, 0))])
def test_dorm_food_get_retries_frame_when_fill_is_unusable(
    monkeypatch: pytest.MonkeyPatch,
    fill_result: RecognitionResult[tuple[int, int, int]],
) -> None:
    food_ocr = _FoodOcr([_valid_digit(8)])
    fill_ocr = _FillOcr(fill_result)
    monkeypatch.setattr(dorm_module, "OCR_FILL", fill_ocr)
    dorm = _Dorm([True, False, False, False, False, False], food_ocr, save_error=True)

    food, fill = dorm.dorm_food_get()

    assert [item.amount for item in food] == [8, 0, 0, 0, 0, 0]
    assert fill == -1
    assert food_ocr.calls == [((0,), True, OCR_FAILURE_STORE)]
    assert len(fill_ocr.calls) == 1
    assert fill_ocr.calls[0][1] is OCR_FAILURE_STORE


def test_dorm_feed_once_retries_after_invalid_frame(monkeypatch: pytest.MonkeyPatch) -> None:
    food_filter = _EmptyFoodFilter()
    monkeypatch.setattr(dorm_module, "FOOD_FILTER", food_filter)
    valid_food = [Food(feed=1000, amount=1)]
    dorm = _DormFeedLoop([([], -1), (valid_food, 0)])

    assert dorm.dorm_feed_once() is False
    assert dorm.food_get_calls == 2
    assert food_filter.loaded == ""
