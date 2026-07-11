# ruff: noqa: SLF001

import numpy as np
import pytest
from cnocr import CnOcr

from module.ocr.al_ocr import AlOcr
from module.ocr.result import RawOcrResult, RecognitionFailureReason, RecognitionResult


def _loaded_ocr() -> AlOcr:
    ocr = AlOcr()
    ocr._model_loaded = True
    return ocr


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


def test_extract_raw_result_preserves_text_and_score() -> None:
    result = AlOcr._extract_raw_result({"text": "14/15", "score": 0.875})

    assert result == RawOcrResult(text="14/15", score=0.875)


def test_extract_raw_result_accepts_numpy_real_score() -> None:
    result = AlOcr._extract_raw_result({"text": "14/15", "score": np.float32(0.875)})

    assert result == RawOcrResult(text="14/15", score=0.875)
    assert type(result.score) is float


@pytest.mark.parametrize(
    "payload",
    [None, "14/15", {}, {"text": 14, "score": 0.9}, {"text": "14/15", "score": float("nan")}],
)
def test_extract_raw_result_rejects_malformed_payload(payload: object) -> None:
    with pytest.raises((TypeError, ValueError)):
        AlOcr._extract_raw_result(payload)


@pytest.mark.parametrize("payload", [{"text": "14/15"}, {"score": 0.9}])
def test_extract_raw_result_translates_missing_fields_to_type_error(payload: object) -> None:
    with pytest.raises(TypeError):
        AlOcr._extract_raw_result(payload)


@pytest.mark.parametrize("score", [True, False, "0.9", None])
def test_extract_raw_result_rejects_non_real_score(score: object) -> None:
    with pytest.raises(TypeError):
        AlOcr._extract_raw_result({"text": "14/15", "score": score})


@pytest.mark.parametrize("score", [float("-inf"), -0.001, 1.001, float("inf")])
def test_extract_raw_result_rejects_non_finite_or_out_of_range_score(score: float) -> None:
    with pytest.raises(ValueError, match="finite and between"):
        AlOcr._extract_raw_result({"text": "14/15", "score": score})


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

    assert ocr._model_loaded is False
    assert ocr._model_name == "densenet_lite_136-gru"
    assert ocr.model_name == "densenet_lite_136-gru"


def test_raw_batch_preserves_text_and_score(monkeypatch: pytest.MonkeyPatch) -> None:
    images = [object(), object()]
    calls = _patch_cnocr_batch(
        monkeypatch,
        [{"text": "14/15", "score": 0.875}, {"text": "01:30:00", "score": 0.625}],
    )
    ocr = _loaded_ocr()

    results = ocr.ocr_for_single_lines_raw(images, batch_size=4)

    assert results == [RawOcrResult("14/15", 0.875), RawOcrResult("01:30:00", 0.625)]
    assert calls == [(images, 4)]


def test_raw_batch_keeps_empty_list(monkeypatch: pytest.MonkeyPatch) -> None:
    images: list[object] = []
    calls = _patch_cnocr_batch(monkeypatch, [])
    ocr = _loaded_ocr()

    assert ocr.ocr_for_single_lines_raw(images) == []
    assert calls == [(images, 1)]


def test_single_line_projects_text_from_raw_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    image = object()
    calls = _patch_cnocr_batch(monkeypatch, [{"text": "14/15", "score": 0.875}])
    monkeypatch.setattr(
        CnOcr,
        "ocr_for_single_line",
        lambda _ocr, _image: pytest.fail("single-line projection bypassed the raw batch"),
    )
    ocr = _loaded_ocr()

    assert ocr.ocr_for_single_line(image) == "14/15"
    assert calls == [([image], 1)]


def test_string_batch_projects_text_from_raw_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    images = [object(), object()]
    calls = _patch_cnocr_batch(
        monkeypatch,
        [{"text": "14/15", "score": 0.875}, {"text": "01:30:00", "score": 0.625}],
    )
    ocr = _loaded_ocr()

    assert ocr.ocr_for_single_lines(images, batch_size=4) == ["14/15", "01:30:00"]
    assert calls == [(images, 4)]


def test_atomic_raw_batch_sets_alphabet_and_preserves_score(monkeypatch: pytest.MonkeyPatch) -> None:
    image = object()
    _patch_cnocr_batch(monkeypatch, [{"text": "14/15", "score": 0.875}])
    alphabets: list[str | None] = []
    monkeypatch.setattr(AlOcr, "set_cand_alphabet", lambda _ocr, alphabet: alphabets.append(alphabet))
    ocr = _loaded_ocr()

    results = ocr.atomic_ocr_for_single_lines_raw([image], cand_alphabet="0123456789/")

    assert results == [RawOcrResult("14/15", 0.875)]
    assert alphabets == ["0123456789/"]


def test_atomic_string_batch_projects_text_from_raw_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    image = object()
    _patch_cnocr_batch(monkeypatch, [{"text": "14/15", "score": 0.875}])
    alphabets: list[str | None] = []
    monkeypatch.setattr(AlOcr, "set_cand_alphabet", lambda _ocr, alphabet: alphabets.append(alphabet))
    ocr = _loaded_ocr()

    results = ocr.atomic_ocr_for_single_lines([image], cand_alphabet="0123456789/")

    assert results == ["14/15"]
    assert alphabets == ["0123456789/"]


def test_atomic_single_line_projects_text_from_raw_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    image = object()
    calls = _patch_cnocr_batch(monkeypatch, [{"text": "14/15", "score": 0.875}])
    alphabets: list[str | None] = []
    monkeypatch.setattr(AlOcr, "set_cand_alphabet", lambda _ocr, alphabet: alphabets.append(alphabet))
    monkeypatch.setattr(
        CnOcr,
        "ocr_for_single_line",
        lambda _ocr, _image: pytest.fail("atomic single-line projection bypassed the raw batch"),
    )
    ocr = _loaded_ocr()

    assert ocr.atomic_ocr_for_single_line(image, cand_alphabet="0123456789/") == "14/15"
    assert alphabets == ["0123456789/"]
    assert calls == [([image], 1)]


def test_detection_ocr_keeps_string_projection(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CnOcr, "ocr", lambda _ocr, _image, **_kwargs: [{"text": "14/15", "score": 0.875}])
    ocr = _loaded_ocr()

    assert ocr.ocr(object()) == ["14/15"]


def test_detection_ocr_rejects_payload_without_score(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(CnOcr, "ocr", lambda _ocr, _image, **_kwargs: [{"text": "14/15"}])
    ocr = _loaded_ocr()

    with pytest.raises(TypeError):
        ocr.ocr(object())
