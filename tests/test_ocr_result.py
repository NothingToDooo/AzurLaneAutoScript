import inspect
from datetime import timedelta
from typing import TypedDict

import cnocr.cn_ocr as cnocr_module
import numpy as np
import pytest
from cnocr import CnOcr

import module.ocr.ocr as ocr_module
from module.ocr.al_ocr import AlOcr
from module.ocr.failure_store import (
    OcrFailureRecordResult,
    OcrFailureRecordStatus,
    OcrFailureSample,
)
from module.ocr.ocr import Digit, DigitCounter, Duration, Ocr
from module.ocr.result import RawOcrResult, RecognitionFailureReason, RecognitionResult

TEST_AREA = (0, 0, 4, 4)
TEST_IMAGE = np.zeros((4, 4, 3), dtype=np.uint8)


class _RecognitionLogPayload(TypedDict):
    text: str
    raw_text: str
    profile: str
    score: float
    valid: bool
    reason: str | None


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

    def atomic_ocr_for_single_lines(
        self,
        image_list: list[np.ndarray],
        cand_alphabet: str | None = None,
    ) -> list[str]:
        del cand_alphabet
        return [self.result.text for _ in image_list]


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

    def record(self, sample: OcrFailureSample[T]) -> OcrFailureRecordResult:
        self.calls.append(sample)
        return OcrFailureRecordResult(OcrFailureRecordStatus.SAVED, "test-digest", None)


class _TestOcr(Ocr):
    def __init__(self, engine: _FakeEngine, buttons=TEST_AREA) -> None:
        self._engine = engine
        super().__init__(buttons, name="TEST_OCR")

    @property
    def cnocr(self) -> _FakeEngine:
        return self._engine


class _TestDigit(Digit):
    def __init__(self, engine: _FakeEngine, buttons=TEST_AREA) -> None:
        self._engine = engine
        super().__init__(buttons, name="TEST_DIGIT")

    @property
    def cnocr(self) -> _FakeEngine:
        return self._engine


class _TestCounter(DigitCounter):
    def __init__(self, engine: _FakeEngine, buttons=TEST_AREA) -> None:
        self._engine = engine
        super().__init__(buttons, name="TEST_COUNTER")

    @property
    def cnocr(self) -> _FakeEngine:
        return self._engine


class _TestDuration(Duration):
    def __init__(self, engine: _FakeEngine, buttons=TEST_AREA) -> None:
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


class _IntegerCorrectingDigit(_TestDigit):
    def after_process(self, result: str) -> int:
        if result == "seven":
            return 7
        return super().after_process(result)


class _UnnamedDigit(Digit):
    def __init__(self, engine: _FakeEngine) -> None:
        self._engine = engine
        super().__init__(TEST_AREA)

    @property
    def cnocr(self) -> _FakeEngine:
        return self._engine


def make_digit(text: str, *, score: float = 0.9, buttons=TEST_AREA) -> _TestDigit:
    return _TestDigit(_FakeEngine(text, score), buttons=buttons)


def make_counter(text: str, *, score: float = 0.9, buttons=TEST_AREA) -> _TestCounter:
    return _TestCounter(_FakeEngine(text, score), buttons=buttons)


def make_duration(text: str, *, score: float = 0.9, buttons=TEST_AREA) -> _TestDuration:
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


def test_structured_recognize_signatures_are_introspectable() -> None:
    for recognize in (Digit.recognize, DigitCounter.recognize, Duration.recognize):
        signature = inspect.signature(recognize)
        assert signature.parameters["failure_store"].default is None


def test_counter_recognize_rejects_multiple_rois() -> None:
    engine = _FakeEngine("14/15", 0.9)
    counter = _TestCounter(engine, buttons=[TEST_AREA, TEST_AREA])

    with pytest.raises(ValueError, match="one ROI"):
        counter.recognize(TEST_IMAGE)

    assert engine.raw_calls == 0


@pytest.mark.parametrize("images", [[], [TEST_IMAGE, TEST_IMAGE]])
def test_counter_recognize_rejects_non_single_direct_rois_before_inference(images: list[np.ndarray]) -> None:
    engine = _FakeEngine("14/15", 0.9)
    counter = _TestCounter(engine)

    with pytest.raises(ValueError, match="one ROI"):
        counter.recognize(images, direct_ocr=True)

    assert engine.raw_calls == 0


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


def test_legacy_counter_ocr_keeps_clamping_until_callers_migrate() -> None:
    counter = make_counter("99/15")

    assert counter.ocr(TEST_IMAGE) == (15, 0, 15)
    assert counter.recognize(TEST_IMAGE).valid is False


def test_legacy_counter_ocr_keeps_empty_fallback() -> None:
    assert make_counter("").ocr(TEST_IMAGE) == (0, 0, 0)


@pytest.mark.parametrize("text", ["01:3000", "0130:00"])
def test_legacy_duration_ocr_keeps_accepting_mixed_formats(text: str) -> None:
    assert make_duration(text).ocr(TEST_IMAGE) == timedelta(hours=1, minutes=30)
    assert require_single(make_duration(text).recognize(TEST_IMAGE)).valid is False


def test_legacy_ocr_keeps_single_and_multiple_roi_shapes() -> None:
    single = _TestOcr(_FakeEngine("7", 0.9)).ocr(TEST_IMAGE)
    multiple = _TestOcr(_FakeEngine("7", 0.9), buttons=[TEST_AREA, TEST_AREA]).ocr(TEST_IMAGE)

    assert single == "7"
    assert multiple == ["7", "7"]


def test_ocr_single_returns_scalar_for_one_roi() -> None:
    assert _TestOcr(_FakeEngine("7", 0.9)).ocr_single(TEST_IMAGE) == "7"


def test_ocr_single_rejects_multiple_button_rois_before_inference() -> None:
    engine = _FakeEngine("7", 0.9)
    ocr = _TestOcr(engine, buttons=[TEST_AREA, TEST_AREA])

    with pytest.raises(ValueError, match="one ROI"):
        ocr.ocr_single(TEST_IMAGE)

    assert engine.inference_batches == []


def test_ocr_single_uses_direct_input_cardinality() -> None:
    ocr = _TestOcr(_FakeEngine("7", 0.9), buttons=[TEST_AREA, TEST_AREA])

    assert ocr.ocr_single([TEST_IMAGE], direct_ocr=True) == "7"
    with pytest.raises(ValueError, match="one ROI"):
        ocr.ocr_single([TEST_IMAGE, TEST_IMAGE], direct_ocr=True)


@pytest.mark.parametrize("images", [[], [TEST_IMAGE], [TEST_IMAGE, TEST_IMAGE]])
def test_ocr_many_keeps_list_shape_for_every_cardinality(images: list[np.ndarray]) -> None:
    assert _TestOcr(_FakeEngine("7", 0.9)).ocr_many(images) == ["7"] * len(images)


def test_digit_recognize_returns_list_for_multiple_rois() -> None:
    results = make_digit("7", buttons=[TEST_AREA, TEST_AREA]).recognize(TEST_IMAGE)

    assert isinstance(results, list)
    assert [result.value for result in results] == [7, 7]


def test_digit_recognize_direct_single_roi_returns_scalar() -> None:
    result = make_digit("7", buttons=[TEST_AREA, TEST_AREA]).recognize([TEST_IMAGE], direct_ocr=True)

    assert not isinstance(result, list)
    assert result.value == 7


def test_digit_recognize_direct_multiple_rois_returns_list() -> None:
    results = make_digit("7").recognize([TEST_IMAGE, TEST_IMAGE], direct_ocr=True)

    assert isinstance(results, list)
    assert [result.value for result in results] == [7, 7]


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


def test_duration_recognize_returns_list_for_multiple_rois() -> None:
    results = make_duration("01:30:00", buttons=[TEST_AREA, TEST_AREA]).recognize(TEST_IMAGE)

    assert isinstance(results, list)
    assert [result.value for result in results] == [timedelta(hours=1, minutes=30)] * 2


def test_duration_recognize_direct_single_roi_returns_scalar() -> None:
    result = make_duration("01:30:00", buttons=[TEST_AREA, TEST_AREA]).recognize([TEST_IMAGE], direct_ocr=True)

    assert not isinstance(result, list)
    assert result.value == timedelta(hours=1, minutes=30)


def test_duration_recognize_direct_multiple_rois_returns_list() -> None:
    results = make_duration("01:30:00").recognize([TEST_IMAGE, TEST_IMAGE], direct_ocr=True)

    assert isinstance(results, list)
    assert [result.value for result in results] == [timedelta(hours=1, minutes=30)] * 2


def test_duration_recognize_records_only_invalid_item_from_multiple_rois() -> None:
    valid_image = TEST_IMAGE.copy()
    invalid_image = np.full_like(TEST_IMAGE, 255)
    engine = _SequenceEngine([RawOcrResult("01:30:00", 0.9), RawOcrResult("01:60:00", 0.2)])
    duration = _TestDuration(engine)
    recorder = _RecordingFailureRecorder()

    results = duration.recognize([valid_image, invalid_image], direct_ocr=True, failure_store=recorder)

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


def test_digit_recognize_uses_dynamic_after_process() -> None:
    digit = _IntegerCorrectingDigit(_FakeEngine("seven", 0.84))

    result = require_single(digit.recognize(TEST_IMAGE))

    assert (result.value, result.normalized_text, result.score) == (7, "7", 0.84)


def test_digit_recognize_rejects_non_integer_after_process_result(monkeypatch: pytest.MonkeyPatch) -> None:
    digit = _TestDigit(_FakeEngine("seven", 0.84))
    monkeypatch.setattr(digit, "after_process", lambda _result: "7")

    result = require_single(digit.recognize(TEST_IMAGE))

    assert result.reason is RecognitionFailureReason.FORMAT_MISMATCH


def test_digit_recognize_translates_integer_conversion_error() -> None:
    result = require_single(make_digit("not-a-number").recognize(TEST_IMAGE))

    assert result.reason is RecognitionFailureReason.FORMAT_MISMATCH


def test_duration_recognize_applies_character_correction() -> None:
    result = require_single(make_duration("DI:3D:DD").recognize(TEST_IMAGE))

    assert (result.value, result.normalized_text) == (timedelta(hours=1, minutes=30), "01:30:00")


def test_recognize_copies_batch_latency_model_and_explicit_profile(monkeypatch: pytest.MonkeyPatch) -> None:
    timestamps = iter([10.0, 10.25])
    monkeypatch.setattr(ocr_module.time, "perf_counter", lambda: next(timestamps))

    results = make_digit("7", buttons=[TEST_AREA, TEST_AREA]).recognize(TEST_IMAGE)

    assert isinstance(results, list)
    assert [result.latency_seconds for result in results] == [0.25, 0.25]
    assert [result.model for result in results] == [_FakeEngine.model_name] * 2
    assert [result.profile for result in results] == ["TEST_DIGIT"] * 2


def test_recognize_uses_class_name_as_default_profile() -> None:
    result = require_single(_UnnamedDigit(_FakeEngine("7", 0.9)).recognize(TEST_IMAGE))

    assert result.profile == "_UnnamedDigit"


def test_structured_recognition_logs_success_and_failure_attributes(monkeypatch: pytest.MonkeyPatch) -> None:
    entries: list[tuple[str, _RecognitionLogPayload]] = []

    def capture(name: str, text: _RecognitionLogPayload) -> None:
        entries.append((name, text))

    monkeypatch.setattr(ocr_module.logger, "attr", capture)

    make_counter("14/15", score=0.87).recognize(TEST_IMAGE)
    make_counter("99/15", score=0.22).recognize(TEST_IMAGE)

    assert len(entries) == 2
    success = entries[0][1]
    failure = entries[1][1]
    assert isinstance(success, dict)
    assert isinstance(failure, dict)
    assert {"profile", "score", "valid", "reason"} <= success.keys()
    assert {"profile", "score", "valid", "reason"} <= failure.keys()
    assert (success["profile"], success["score"], success["valid"], success["reason"]) == (
        "TEST_COUNTER",
        0.87,
        True,
        None,
    )
    assert (failure["profile"], failure["score"], failure["valid"], failure["reason"]) == (
        "TEST_COUNTER",
        0.22,
        False,
        RecognitionFailureReason.CURRENT_EXCEEDS_TOTAL.value,
    )


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


def extract_raw_result(monkeypatch: pytest.MonkeyPatch, payload: object) -> RawOcrResult:
    _patch_cnocr_batch(monkeypatch, [payload])
    return _loaded_ocr().ocr_for_single_lines_raw([TEST_IMAGE])[0]


def test_extract_raw_result_preserves_text_and_score(monkeypatch: pytest.MonkeyPatch) -> None:
    result = extract_raw_result(monkeypatch, {"text": "14/15", "score": 0.875})

    assert result == RawOcrResult(text="14/15", score=0.875)


def test_extract_raw_result_accepts_numpy_real_score(monkeypatch: pytest.MonkeyPatch) -> None:
    result = extract_raw_result(monkeypatch, {"text": "14/15", "score": np.float32(0.875)})

    assert result == RawOcrResult(text="14/15", score=0.875)
    assert type(result.score) is float


@pytest.mark.parametrize(
    "payload",
    [None, "14/15", {}, {"text": 14, "score": 0.9}, {"text": "14/15", "score": float("nan")}],
)
def test_extract_raw_result_rejects_malformed_payload(monkeypatch: pytest.MonkeyPatch, payload: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        extract_raw_result(monkeypatch, payload)


@pytest.mark.parametrize("payload", [{"text": "14/15"}, {"score": 0.9}])
def test_extract_raw_result_translates_missing_fields_to_type_error(
    monkeypatch: pytest.MonkeyPatch,
    payload: object,
) -> None:
    with pytest.raises(TypeError):
        extract_raw_result(monkeypatch, payload)


@pytest.mark.parametrize("score", [True, False, "0.9", None])
def test_extract_raw_result_rejects_non_real_score(monkeypatch: pytest.MonkeyPatch, score: object) -> None:
    with pytest.raises(TypeError):
        extract_raw_result(monkeypatch, {"text": "14/15", "score": score})


@pytest.mark.parametrize("score", [float("-inf"), -0.001, 1.001, float("inf")])
def test_extract_raw_result_rejects_non_finite_or_out_of_range_score(
    monkeypatch: pytest.MonkeyPatch,
    score: float,
) -> None:
    with pytest.raises(ValueError, match="finite and between"):
        extract_raw_result(monkeypatch, {"text": "14/15", "score": score})


def test_recognition_result_accepts_consistent_success_and_failure() -> None:
    success = RecognitionResult[int](
        raw_text="14/15",
        normalized_text="14/15",
        score=0.875,
        value=14,
        valid=True,
        reason=None,
        latency_seconds=0.01,
        profile="counter",
        model="densenet_lite_136-gru",
    )
    failure = RecognitionResult[int](
        raw_text="",
        normalized_text="",
        score=0.0,
        value=None,
        valid=False,
        reason=RecognitionFailureReason.EMPTY_TEXT,
        latency_seconds=0.0,
        profile="counter",
        model="densenet_lite_136-gru",
    )

    assert success.value == 14
    assert failure.reason is RecognitionFailureReason.EMPTY_TEXT


@pytest.mark.parametrize("field", ["profile", "model"])
@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_recognition_result_rejects_blank_identity_fields(field: str, value: str) -> None:
    arguments = {
        "raw_text": "14/15",
        "normalized_text": "14/15",
        "score": 0.875,
        "value": 14,
        "valid": True,
        "reason": None,
        "latency_seconds": 0.01,
        "profile": "counter",
        "model": "densenet_lite_136-gru",
    }
    arguments[field] = value

    with pytest.raises(ValueError, match="must not be blank"):
        RecognitionResult(**arguments)


@pytest.mark.parametrize("score", [float("-inf"), -0.001, 1.001, float("inf"), float("nan")])
def test_recognition_result_rejects_invalid_score(score: float) -> None:
    with pytest.raises(ValueError, match="score must be finite and between"):
        RecognitionResult[int](
            raw_text="14/15",
            normalized_text="14/15",
            score=score,
            value=14,
            valid=True,
            reason=None,
            latency_seconds=0.01,
            profile="counter",
            model="densenet_lite_136-gru",
        )


@pytest.mark.parametrize("latency_seconds", [float("-inf"), -0.001, float("inf"), float("nan")])
def test_recognition_result_rejects_invalid_latency(latency_seconds: float) -> None:
    with pytest.raises(ValueError, match="latency_seconds must be finite and non-negative"):
        RecognitionResult[int](
            raw_text="14/15",
            normalized_text="14/15",
            score=0.875,
            value=14,
            valid=True,
            reason=None,
            latency_seconds=latency_seconds,
            profile="counter",
            model="densenet_lite_136-gru",
        )


@pytest.mark.parametrize(
    ("valid", "value", "reason"),
    [
        (True, None, None),
        (True, 14, RecognitionFailureReason.FORMAT_MISMATCH),
        (False, 14, RecognitionFailureReason.FORMAT_MISMATCH),
        (False, None, None),
    ],
)
def test_recognition_result_rejects_inconsistent_state(
    *,
    valid: bool,
    value: int | None,
    reason: RecognitionFailureReason | None,
) -> None:
    with pytest.raises(ValueError, match="result must have"):
        RecognitionResult[int](
            raw_text="14/15",
            normalized_text="14/15",
            score=0.875,
            value=value,
            valid=valid,
            reason=reason,
            latency_seconds=0.01,
            profile="counter",
            model="densenet_lite_136-gru",
        )


def test_model_name_is_normalized_without_loading(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(AlOcr, "ensure_loaded", lambda _ocr: pytest.fail("model_name triggered model loading"))

    ocr = AlOcr(model_name="densenet-lite-gru")

    assert ocr.model_name == "densenet_lite_136-gru"


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


def test_raw_batch_keeps_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    images: list[np.ndarray] = []
    calls = _patch_cnocr_batch(monkeypatch, [])
    ocr = _loaded_ocr()

    assert ocr.ocr_for_single_lines_raw(images) == []
    assert calls == [(images, 1)]


def test_atomic_raw_batch_sets_alphabet_and_preserves_score(monkeypatch: pytest.MonkeyPatch) -> None:
    image = TEST_IMAGE.copy()
    _patch_cnocr_batch(monkeypatch, [{"text": "14/15", "score": 0.875}])
    alphabets: list[str | None] = []
    monkeypatch.setattr(AlOcr, "set_cand_alphabet", lambda _ocr, alphabet: alphabets.append(alphabet))
    ocr = _loaded_ocr()

    results = ocr.atomic_ocr_for_single_lines_raw([image], cand_alphabet="0123456789/")

    assert results == [RawOcrResult("14/15", 0.875)]
    assert alphabets == ["0123456789/"]


def test_atomic_string_batch_projects_text_from_raw_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    image = TEST_IMAGE.copy()
    _patch_cnocr_batch(monkeypatch, [{"text": "14/15", "score": 0.875}])
    alphabets: list[str | None] = []
    monkeypatch.setattr(AlOcr, "set_cand_alphabet", lambda _ocr, alphabet: alphabets.append(alphabet))
    ocr = _loaded_ocr()

    results = ocr.atomic_ocr_for_single_lines([image], cand_alphabet="0123456789/")

    assert results == ["14/15"]
    assert alphabets == ["0123456789/"]


def test_detection_ocr_keeps_cnocr_dictionary_path_before_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    image = np.full((32, 64), 255, dtype=np.uint8)
    payloads: list[object] = [{"text": "14/15", "score": 0.875}]
    calls = _patch_cnocr_batch(monkeypatch, payloads)
    monkeypatch.setattr(cnocr_module, "line_split", lambda _image, **_kwargs: [(image, None)])
    ocr = _loaded_ocr()
    ocr.det_model = None
    monkeypatch.setattr(ocr, "_prepare_img", lambda _image: image)

    assert ocr.ocr_texts(image) == ["14/15"]
    assert len(calls) == 1
    assert calls[0][0][0] is image
    assert calls[0][1] == 1
