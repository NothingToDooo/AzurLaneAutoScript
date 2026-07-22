from datetime import timedelta
from typing import TYPE_CHECKING

import numpy as np
import pytest
from cnocr import CnOcr

from module.ocr.al_ocr import AlOcr
from module.ocr.ocr import Digit, DigitCounter, Duration, OcrRegions
from module.ocr.result import RawOcrResult, RecognitionFailureReason, RecognitionResult

if TYPE_CHECKING:
    from module.ocr.failure_store import OcrFailureSample

TEST_AREA = (0, 0, 4, 4)
TEST_IMAGE = np.zeros((4, 4, 3), dtype=np.uint8)


class _FakeEngine:
    model_name = "densenet_lite_136-gru"

    def __init__(self, text: str, score: float) -> None:
        self.result = RawOcrResult(text=text, score=score)
        self.raw_calls = 0
        self.inference_batches: list[list[np.ndarray]] = []

    def atomic_ocr_for_single_lines_raw(
        self,
        image_list: list[np.ndarray],
        cand_alphabet: str | None = None,
    ) -> list[RawOcrResult]:
        del cand_alphabet
        self.raw_calls += 1
        self.inference_batches.append(image_list)
        return [self.result for _ in image_list]


class _SequenceEngine(_FakeEngine):
    def __init__(self, results: list[RawOcrResult]) -> None:
        super().__init__(results[0].text, results[0].score)
        self.results = results

    def atomic_ocr_for_single_lines_raw(
        self,
        image_list: list[np.ndarray],
        cand_alphabet: str | None = None,
    ) -> list[RawOcrResult]:
        del cand_alphabet
        self.raw_calls += 1
        self.inference_batches.append(image_list)
        return self.results


class _RecordingFailureRecorder[T]:
    def __init__(self) -> None:
        self.calls: list[OcrFailureSample[T]] = []

    def record(self, sample: OcrFailureSample[T]) -> None:
        self.calls.append(sample)


class _TestDigit(Digit):
    def __init__(self, engine: _FakeEngine, buttons: OcrRegions = TEST_AREA) -> None:
        self._engine = engine
        super().__init__(buttons, name="TEST_DIGIT")

    @property
    def cnocr(self) -> _FakeEngine:
        return self._engine


class _TestCounter(DigitCounter):
    def __init__(self, engine: _FakeEngine, buttons: OcrRegions = TEST_AREA) -> None:
        self._engine = engine
        super().__init__(buttons, name="TEST_COUNTER")

    @property
    def cnocr(self) -> _FakeEngine:
        return self._engine


class _TestDuration(Duration):
    def __init__(self, engine: _FakeEngine, buttons: OcrRegions = TEST_AREA) -> None:
        self._engine = engine
        super().__init__(buttons, name="TEST_DURATION")

    @property
    def cnocr(self) -> _FakeEngine:
        return self._engine


class _SlashCounter(_TestCounter):
    @staticmethod
    def normalize_text(result: str) -> str:
        result = DigitCounter.normalize_text(result)
        return "14/15" if result == "1415" else result


def make_digit(text: str, *, score: float = 0.9, buttons: OcrRegions = TEST_AREA) -> _TestDigit:
    return _TestDigit(_FakeEngine(text, score), buttons=buttons)


def make_counter(text: str, *, score: float = 0.9, buttons: OcrRegions = TEST_AREA) -> _TestCounter:
    return _TestCounter(_FakeEngine(text, score), buttons=buttons)


def make_duration(text: str, *, score: float = 0.9, buttons: OcrRegions = TEST_AREA) -> _TestDuration:
    return _TestDuration(_FakeEngine(text, score), buttons=buttons)


def require_single[T](
    result: RecognitionResult[T] | list[RecognitionResult[T]],
) -> RecognitionResult[T]:
    assert not isinstance(result, list)
    return result


def test_digit_recognize_distinguishes_zero_from_empty() -> None:
    zero = require_single(make_digit("0", score=0.91).recognize(TEST_IMAGE))
    empty = require_single(make_digit("", score=0.12).recognize(TEST_IMAGE))

    assert (zero.valid, zero.value, zero.reason) == (True, 0, None)
    assert (empty.valid, empty.value, empty.reason) == (
        False,
        None,
        RecognitionFailureReason.EMPTY_TEXT,
    )


def test_counter_recognize_rejects_current_above_total() -> None:
    result = make_counter("99/15", score=0.99).recognize(TEST_IMAGE)

    assert result.valid is False
    assert result.value is None
    assert result.reason is RecognitionFailureReason.CURRENT_EXCEEDS_TOTAL
    assert result.raw_text == "99/15"
    assert result.score == 0.99


@pytest.mark.parametrize("text", ["x14/15", "14/15/", "1/2/3"])
def test_counter_recognize_requires_full_match(text: str) -> None:
    assert make_counter(text).recognize(TEST_IMAGE).reason is RecognitionFailureReason.FORMAT_MISMATCH


def test_counter_recognize_rejects_empty_text() -> None:
    result = make_counter("", score=0.11).recognize(TEST_IMAGE)

    assert (result.valid, result.value, result.reason) == (
        False,
        None,
        RecognitionFailureReason.EMPTY_TEXT,
    )
    assert result.score == 0.11


@pytest.mark.parametrize("expected_total", [None, 15])
def test_counter_recognize_accepts_expected_total(expected_total: int | None) -> None:
    result = make_counter("14/15").recognize(TEST_IMAGE, expected_total=expected_total)

    assert (result.valid, result.value, result.reason) == (True, (14, 1, 15), None)
    assert result.normalized_text == "14/15"


def test_counter_recognize_rejects_unexpected_total() -> None:
    result = make_counter("14/15").recognize(TEST_IMAGE, expected_total=10)

    assert result.reason is RecognitionFailureReason.UNEXPECTED_TOTAL


def test_counter_recognize_records_failure_with_complete_inference_context() -> None:
    recorder = _RecordingFailureRecorder()
    counter = make_counter("14/15")
    counter.letter = [140, 113, 99]
    counter.threshold = 64

    result = counter.recognize(TEST_IMAGE, expected_total=10, failure_store=recorder)

    assert result.reason is RecognitionFailureReason.UNEXPECTED_TOTAL
    call = recorder.calls[0]
    assert call.result is result
    assert np.array_equal(call.raw_image, TEST_IMAGE)
    assert call.processed_image is counter.cnocr.inference_batches[0][0]
    assert (call.area, call.alphabet, call.letter, call.threshold, call.expected_total) == (
        TEST_AREA,
        "0123456789/IDSB",
        (140, 113, 99),
        64,
        10,
    )


@pytest.mark.parametrize("text", ["01:60:00", "01:00:60"])
def test_duration_recognize_rejects_invalid_components(text: str) -> None:
    result = require_single(make_duration(text).recognize(TEST_IMAGE))

    assert result.reason is RecognitionFailureReason.TIME_COMPONENT_OUT_OF_RANGE


@pytest.mark.parametrize("text", ["1:30:00", "01:30:00", "13000", "013000"])
def test_duration_recognize_accepts_complete_formats(text: str) -> None:
    result = require_single(make_duration(text).recognize(TEST_IMAGE))

    assert (result.valid, result.value, result.reason) == (True, timedelta(hours=1, minutes=30), None)
    assert result.normalized_text == text


@pytest.mark.parametrize("text", ["01:3000", "0130:00"])
def test_duration_recognize_rejects_mixed_formats(text: str) -> None:
    result = require_single(make_duration(text).recognize(TEST_IMAGE))

    assert result.reason is RecognitionFailureReason.FORMAT_MISMATCH


def test_duration_recognize_rejects_empty_text() -> None:
    result = require_single(make_duration("", score=0.07).recognize(TEST_IMAGE))

    assert (result.valid, result.value, result.reason) == (
        False,
        None,
        RecognitionFailureReason.EMPTY_TEXT,
    )
    assert result.score == 0.07


def test_digit_recognize_records_only_invalid_item_from_multiple_rois() -> None:
    valid_image = TEST_IMAGE.copy()
    invalid_image = np.full_like(TEST_IMAGE, 255)
    engine = _SequenceEngine([RawOcrResult("7", 0.9), RawOcrResult("invalid", 0.2)])
    digit = _TestDigit(engine)
    recorder = _RecordingFailureRecorder()

    results = digit.recognize([valid_image, invalid_image], direct_ocr=True, failure_store=recorder)

    assert isinstance(results, list)
    assert [result.valid for result in results] == [True, False]
    assert len(recorder.calls) == 1
    call = recorder.calls[0]
    assert call.result is results[1]
    assert call.raw_image is invalid_image
    assert call.processed_image is engine.inference_batches[0][1]
    assert (call.area, call.expected_total) == (None, None)


def test_counter_recognize_applies_subclass_correction_before_full_match() -> None:
    counter = _SlashCounter(_FakeEngine("1415", 0.88))

    result = counter.recognize(TEST_IMAGE)

    assert (result.value, result.normalized_text) == ((14, 1, 15), "14/15")
    assert result.score == 0.88


def test_duration_recognize_applies_character_correction() -> None:
    result = require_single(make_duration("DI:3D:DD").recognize(TEST_IMAGE))

    assert (result.value, result.normalized_text) == (timedelta(hours=1, minutes=30), "01:30:00")


def _loaded_ocr() -> AlOcr:
    class _LoadedAlOcr(AlOcr):
        def ensure_loaded(self) -> None:
            pass

    return _LoadedAlOcr()


def _patch_cnocr_batch(
    monkeypatch: pytest.MonkeyPatch,
    payloads: list[object],
) -> list[tuple[list[object], int]]:
    calls: list[tuple[list[object], int]] = []

    def ocr_for_single_lines(_ocr: CnOcr, img_list: list[object], batch_size: int = 1) -> list[object]:
        calls.append((img_list, batch_size))
        return payloads

    monkeypatch.setattr(CnOcr, "ocr_for_single_lines", ocr_for_single_lines)
    return calls


def test_raw_batch_preserves_text_and_score(monkeypatch: pytest.MonkeyPatch) -> None:
    images = [TEST_IMAGE.copy(), TEST_IMAGE.copy()]
    calls = _patch_cnocr_batch(
        monkeypatch,
        [{"text": "14/15", "score": 0.875}, {"text": "01:30:00", "score": 0.625}],
    )
    ocr = _loaded_ocr()

    results = ocr.ocr_for_single_lines_raw(images, batch_size=4)

    assert results == [RawOcrResult("14/15", 0.875), RawOcrResult("01:30:00", 0.625)]
    assert calls == [(images, 4)]


def test_atomic_raw_batch_sets_alphabet_and_preserves_score(monkeypatch: pytest.MonkeyPatch) -> None:
    image = TEST_IMAGE.copy()
    _patch_cnocr_batch(monkeypatch, [{"text": "14/15", "score": 0.875}])
    alphabets: list[str | None] = []
    monkeypatch.setattr(AlOcr, "set_cand_alphabet", lambda _ocr, alphabet: alphabets.append(alphabet))
    ocr = _loaded_ocr()

    results = ocr.atomic_ocr_for_single_lines_raw([image], cand_alphabet="0123456789/")

    assert results == [RawOcrResult("14/15", 0.875)]
    assert alphabets == ["0123456789/"]
