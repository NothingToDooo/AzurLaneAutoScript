import json
import logging
from dataclasses import replace
from datetime import datetime
from typing import TYPE_CHECKING

import numpy as np
import pytest
from PIL import Image

import module.ocr.failure_store as failure_store_module
from module.ocr.failure_store import OCR_FAILURE_STORE, OcrFailureRecorder, OcrFailureSample, OcrFailureStore
from module.ocr.ocr import DigitCounter
from module.ocr.result import RawOcrResult, RecognitionFailureReason, RecognitionResult

if TYPE_CHECKING:
    from pathlib import Path

    from module.base.atomic import FileData

RAW_IMAGE = np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
PROCESSED_IMAGE = np.arange(12, dtype=np.uint8).reshape(3, 4)
ALTERNATE_RAW_IMAGE = 255 - RAW_IMAGE
ALTERNATE_PROCESSED_IMAGE = 255 - PROCESSED_IMAGE
COUNTER_AREA = (0, 0, 4, 3)


class _CounterEngine:
    model_name = "densenet_lite_136-gru"

    def __init__(self, text: str) -> None:
        self.result = RawOcrResult(text=text, score=0.9)

    def atomic_ocr_for_single_lines_raw(
        self,
        image_list: list[np.ndarray],
        cand_alphabet: str | None = None,
    ) -> list[RawOcrResult]:
        del cand_alphabet
        return [self.result for _ in image_list]


class _StoreTestCounter(DigitCounter):
    def __init__(self, text: str) -> None:
        self._engine = _CounterEngine(text)
        super().__init__(COUNTER_AREA, name="TEST_COUNTER")

    @property
    def cnocr(self) -> _CounterEngine:
        return self._engine


def _failure_result(
    *,
    profile: str = "counter.v1",
    raw_text: str = "99/15",
) -> RecognitionResult[tuple[int, int, int]]:
    return RecognitionResult(
        raw_text=raw_text,
        normalized_text=raw_text,
        score=0.25,
        value=None,
        valid=False,
        reason=RecognitionFailureReason.CURRENT_EXCEEDS_TOTAL,
        latency_seconds=0.125,
        profile=profile,
        model="densenet_lite_136-gru",
    )


def _sample(
    result: RecognitionResult[tuple[int, int, int]] | None = None,
    *,
    raw_image: np.ndarray = RAW_IMAGE,
    processed_image: np.ndarray = PROCESSED_IMAGE,
    expected_total: int | None = None,
) -> OcrFailureSample[tuple[int, int, int]]:
    return OcrFailureSample(
        result=_failure_result() if result is None else result,
        raw_image=raw_image,
        processed_image=processed_image,
        area=(1, 2, 5, 6),
        alphabet="0123456789/IDSB",
        letter=(140, 113, 99),
        threshold=64,
        expected_total=expected_total,
    )


def _read_png(path: Path) -> np.ndarray:
    with Image.open(path) as image:
        return np.asarray(image)


def test_failure_store_is_lazy_and_exports_the_default_recorder(tmp_path: Path) -> None:
    root = tmp_path / "missing"
    recorder: OcrFailureRecorder = OcrFailureStore(root)

    assert isinstance(recorder, OcrFailureStore)
    assert isinstance(OCR_FAILURE_STORE, OcrFailureStore)
    assert not root.exists()


def test_failure_store_writes_one_complete_profile_snapshot(tmp_path: Path) -> None:
    result = replace(
        _failure_result(),
        raw_text="识别失败 99/15",
        normalized_text="99/15",
    )

    directory = OcrFailureStore(tmp_path).record(_sample(result, expected_total=15))

    assert directory == tmp_path / "counter.v1"
    assert directory is not None
    assert {path.name for path in directory.iterdir()} == {"raw.png", "processed.png", "metadata.json"}
    np.testing.assert_array_equal(_read_png(directory / "raw.png"), RAW_IMAGE)
    np.testing.assert_array_equal(_read_png(directory / "processed.png"), PROCESSED_IMAGE)
    metadata = json.loads((directory / "metadata.json").read_text(encoding="utf-8"))
    assert metadata == {
        "alphabet": "0123456789/IDSB",
        "area": [1, 2, 5, 6],
        "captured_at": metadata["captured_at"],
        "expected_total": 15,
        "latency_seconds": 0.125,
        "letter": [140, 113, 99],
        "model": "densenet_lite_136-gru",
        "normalized_text": "99/15",
        "processed_dtype": "uint8",
        "processed_shape": [3, 4],
        "profile": "counter.v1",
        "raw_dtype": "uint8",
        "raw_shape": [3, 4, 3],
        "raw_text": "识别失败 99/15",
        "reason": "current_exceeds_total",
        "schema_version": 1,
        "score": 0.25,
        "threshold": 64,
        "valid": False,
        "value": None,
    }
    assert datetime.fromisoformat(metadata["captured_at"]).utcoffset() is not None


def test_failure_store_replaces_the_previous_snapshot_for_the_same_profile(tmp_path: Path) -> None:
    store = OcrFailureStore(tmp_path)
    first = store.record(_sample())
    second = store.record(
        _sample(
            _failure_result(raw_text="98/15"),
            raw_image=ALTERNATE_RAW_IMAGE,
            processed_image=ALTERNATE_PROCESSED_IMAGE,
        )
    )

    assert first == second == tmp_path / "counter.v1"
    assert second is not None
    assert {path.name for path in second.iterdir()} == {"raw.png", "processed.png", "metadata.json"}
    assert not [path for path in second.iterdir() if path.is_dir()]
    np.testing.assert_array_equal(_read_png(second / "raw.png"), ALTERNATE_RAW_IMAGE)
    np.testing.assert_array_equal(_read_png(second / "processed.png"), ALTERNATE_PROCESSED_IMAGE)
    metadata = json.loads((second / "metadata.json").read_text(encoding="utf-8"))
    assert metadata["raw_text"] == "98/15"


def test_failure_store_keeps_one_snapshot_per_profile(tmp_path: Path) -> None:
    store = OcrFailureStore(tmp_path)

    first = store.record(_sample(_failure_result(profile="counter.v1")))
    second = store.record(_sample(_failure_result(profile="counter.v2")))

    assert first == tmp_path / "counter.v1"
    assert second == tmp_path / "counter.v2"
    assert {path.name for path in tmp_path.iterdir()} == {"counter.v1", "counter.v2"}
    for directory in (first, second):
        assert directory is not None
        assert {path.name for path in directory.iterdir()} == {"raw.png", "processed.png", "metadata.json"}


def test_failure_store_marks_an_interrupted_write_as_incomplete(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    store = OcrFailureStore(tmp_path)
    directory = store.record(_sample())
    assert directory is not None
    atomic_write = failure_store_module.atomic_write

    def fail_processed(path: Path, content: FileData) -> None:
        if path.name == "processed.png":
            message = "disk full while writing 98/15"
            raise OSError(message)
        atomic_write(path, content)

    monkeypatch.setattr(failure_store_module, "atomic_write", fail_processed)
    with caplog.at_level(logging.WARNING, logger="alas"):
        saved = store.record(
            _sample(
                _failure_result(raw_text="98/15"),
                raw_image=ALTERNATE_RAW_IMAGE,
                processed_image=ALTERNATE_PROCESSED_IMAGE,
            )
        )

    assert saved is None
    assert not (directory / "metadata.json").exists()
    warnings = [record.getMessage() for record in caplog.records if "OCR failure snapshot" in record.getMessage()]
    assert len(warnings) == 1
    assert "OSError" in warnings[0]
    assert "98/15" not in warnings[0]


def test_snapshot_write_failure_does_not_change_recognition_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_write(_path: Path, _content: object) -> None:
        message = "read-only filesystem"
        raise OSError(message)

    monkeypatch.setattr(failure_store_module, "atomic_write", fail_write)

    result = _StoreTestCounter("99/15").recognize(
        RAW_IMAGE,
        failure_store=OcrFailureStore(tmp_path),
    )

    assert result.valid is False
    assert result.reason is RecognitionFailureReason.CURRENT_EXCEEDS_TOTAL


@pytest.mark.parametrize("profile", ["../escape", "a/b", ".", "..", "a" * 65])
def test_failure_store_rejects_unsafe_profile_before_writing(tmp_path: Path, profile: str) -> None:
    root = tmp_path / "root"

    with pytest.raises(ValueError, match="profile"):
        OcrFailureStore(root).record(_sample(_failure_result(profile=profile)))

    assert not root.exists()


def test_failure_store_rejects_successful_results_and_invalid_images(tmp_path: Path) -> None:
    root = tmp_path / "root"
    valid_result = replace(
        _failure_result(),
        valid=True,
        reason=None,
        value=(14, 1, 15),
    )
    store = OcrFailureStore(root)

    with pytest.raises(ValueError, match="failed"):
        store.record(_sample(valid_result))
    with pytest.raises(ValueError, match="uint8"):
        store.record(_sample(raw_image=RAW_IMAGE.astype(np.float32)))

    assert not root.exists()
