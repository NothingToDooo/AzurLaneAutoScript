# ruff: noqa: SLF001

import json
import logging
import shutil
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

import module.ocr.failure_store as failure_store_module
from module.ocr.failure_store import (
    OCR_FAILURE_STORE,
    OcrFailureRecorder,
    OcrFailureRecordStatus,
    OcrFailureStore,
)
from module.ocr.ocr import DigitCounter
from module.ocr.result import RawOcrResult, RecognitionFailureReason, RecognitionResult

RAW_IMAGE = np.arange(36, dtype=np.uint8).reshape(3, 4, 3)
PROCESSED_IMAGE = np.arange(12, dtype=np.uint8).reshape(3, 4)
ALTERNATE_RAW_IMAGE = 255 - RAW_IMAGE


def make_invalid_counter_result() -> RecognitionResult[tuple[int, int, int]]:
    return RecognitionResult(
        raw_text="99/15",
        normalized_text="99/15",
        score=0.25,
        value=None,
        valid=False,
        reason=RecognitionFailureReason.CURRENT_EXCEEDS_TOTAL,
        latency_seconds=0.125,
        profile="counter.v1",
        model="densenet_lite_136-gru",
    )


def bundle_size(directory: Path) -> int:
    return sum(path.stat().st_size for path in directory.iterdir())


@dataclass(frozen=True, slots=True)
class _DigestCase:
    label: str
    result: RecognitionResult[tuple[int, int, int]] | None = None
    area: tuple[int, int, int, int] | None = (1, 2, 5, 6)
    alphabet: str | None = "0123456789/IDSB"
    letter: tuple[int, int, int] = (140, 113, 99)
    threshold: int = 64
    expected_total: int | None = None
    processed_image: np.ndarray | None = None


_DIGEST_CASES = (
    _DigestCase(
        "reason",
        result=replace(make_invalid_counter_result(), reason=RecognitionFailureReason.FORMAT_MISMATCH),
    ),
    _DigestCase("model", result=replace(make_invalid_counter_result(), model="alternate-model")),
    _DigestCase("profile", result=replace(make_invalid_counter_result(), profile="counter.v2")),
    _DigestCase("raw_text", result=replace(make_invalid_counter_result(), raw_text="98/15")),
    _DigestCase("normalized_text", result=replace(make_invalid_counter_result(), normalized_text="98/15")),
    _DigestCase("area", area=(1, 2, 5, 7)),
    _DigestCase("alphabet", alphabet="0123456789/"),
    _DigestCase("letter", letter=(140, 113, 98)),
    _DigestCase("threshold", threshold=65),
    _DigestCase("expected_total", expected_total=15),
    _DigestCase("processed_bytes", processed_image=np.roll(PROCESSED_IMAGE, 1)),
    _DigestCase("processed_shape", processed_image=PROCESSED_IMAGE.reshape(4, 3)),
)


def test_failure_store_constructor_does_not_create_root(tmp_path: Path) -> None:
    root = tmp_path / "missing"

    OcrFailureStore(root)

    assert not root.exists()


def test_failure_store_exports_default_store_and_recorder_protocol(tmp_path: Path) -> None:
    recorder: OcrFailureRecorder = OcrFailureStore(tmp_path / "missing")

    assert isinstance(recorder, OcrFailureStore)
    assert isinstance(OCR_FAILURE_STORE, OcrFailureStore)


def test_failure_store_writes_complete_bundle(tmp_path: Path) -> None:
    store = OcrFailureStore(tmp_path)

    record = store.record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet="0123456789/IDSB",
        letter=(140, 113, 99),
        threshold=64,
    )

    assert record.status is OcrFailureRecordStatus.SAVED
    assert record.directory == tmp_path / "counter.v1" / record.digest
    assert len(record.digest) == 64
    assert set(record.digest) <= set("0123456789abcdef")
    assert record.directory is not None
    assert {path.name for path in record.directory.iterdir()} == {
        "raw.png",
        "processed.png",
        "metadata.json",
    }
    with Image.open(record.directory / "raw.png") as image:
        assert np.array_equal(np.asarray(image), RAW_IMAGE)
    with Image.open(record.directory / "processed.png") as image:
        assert np.array_equal(np.asarray(image), PROCESSED_IMAGE)

    metadata_text = (record.directory / "metadata.json").read_text(encoding="utf-8")
    metadata = json.loads(metadata_text)
    assert metadata_text == json.dumps(metadata, ensure_ascii=False, sort_keys=True) + "\n"
    assert datetime.fromisoformat(metadata["captured_at"]).utcoffset() is not None
    assert metadata == {
        "alphabet": "0123456789/IDSB",
        "area": [1, 2, 5, 6],
        "captured_at": metadata["captured_at"],
        "digest": record.digest,
        "expected_total": None,
        "latency_seconds": 0.125,
        "letter": [140, 113, 99],
        "model": "densenet_lite_136-gru",
        "normalized_text": "99/15",
        "processed_dtype": "uint8",
        "processed_shape": [3, 4],
        "profile": "counter.v1",
        "raw_dtype": "uint8",
        "raw_shape": [3, 4, 3],
        "raw_text": "99/15",
        "reason": "current_exceeds_total",
        "schema_version": 1,
        "score": 0.25,
        "threshold": 64,
        "valid": False,
        "value": None,
    }


def test_failure_store_preserves_grayscale_raw_and_non_ascii_metadata(tmp_path: Path) -> None:
    result = replace(
        make_invalid_counter_result(),
        raw_text="识别错误",
        normalized_text="识别错误",
        reason=RecognitionFailureReason.FORMAT_MISMATCH,
    )

    record = OcrFailureStore(tmp_path).record(
        result,
        raw_image=PROCESSED_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=None,
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )

    assert record.directory is not None
    with Image.open(record.directory / "raw.png") as image:
        assert np.array_equal(np.asarray(image), PROCESSED_IMAGE)
    metadata_text = (record.directory / "metadata.json").read_text(encoding="utf-8")
    assert "识别错误" in metadata_text
    assert r"\u8bc6" not in metadata_text


def test_failure_store_persistently_deduplicates_inference_input(tmp_path: Path) -> None:
    first_result = make_invalid_counter_result()
    first = OcrFailureStore(tmp_path).record(
        first_result,
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet="0123456789/IDSB",
        letter=(140, 113, 99),
        threshold=64,
    )

    duplicate = OcrFailureStore(
        tmp_path,
        max_total_samples=0,
        max_samples_per_profile=0,
        max_total_bytes=0,
        max_new_samples_per_process=0,
    ).record(
        replace(first_result, score=0.75, latency_seconds=9.5),
        raw_image=ALTERNATE_RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet="0123456789/IDSB",
        letter=(140, 113, 99),
        threshold=64,
    )

    assert duplicate.status is OcrFailureRecordStatus.DUPLICATE
    assert duplicate.digest == first.digest
    assert duplicate.directory == first.directory
    assert first.directory is not None
    with Image.open(first.directory / "raw.png") as image:
        assert np.array_equal(np.asarray(image), RAW_IMAGE)
    metadata = json.loads((first.directory / "metadata.json").read_text(encoding="utf-8"))
    assert (metadata["score"], metadata["latency_seconds"]) == (0.25, 0.125)


@pytest.mark.parametrize(
    "case",
    _DIGEST_CASES,
    ids=[case.label for case in _DIGEST_CASES],
)
def test_failure_store_digest_covers_versioned_inference_context(tmp_path: Path, case: _DigestCase) -> None:
    result = make_invalid_counter_result()
    base = OcrFailureStore(tmp_path).record(
        result,
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet="0123456789/IDSB",
        letter=(140, 113, 99),
        threshold=64,
    )
    changed_result = case.result if case.result is not None else result
    processed_image = case.processed_image if case.processed_image is not None else PROCESSED_IMAGE

    changed = OcrFailureStore(tmp_path).record(
        changed_result,
        raw_image=RAW_IMAGE,
        processed_image=processed_image,
        area=case.area,
        alphabet=case.alphabet,
        letter=case.letter,
        threshold=case.threshold,
        expected_total=case.expected_total,
    )

    assert changed.status is OcrFailureRecordStatus.SAVED
    assert changed.digest != base.digest


def test_failure_store_enforces_global_sample_limit_without_creating_profile(tmp_path: Path) -> None:
    store = OcrFailureStore(tmp_path, max_total_samples=1)
    store.record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )

    rejected = store.record(
        replace(make_invalid_counter_result(), profile="other-profile"),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )

    assert rejected.status is OcrFailureRecordStatus.LIMIT_REACHED
    assert rejected.directory is None
    assert not (tmp_path / "other-profile").exists()


def test_failure_store_enforces_per_profile_sample_limit(tmp_path: Path) -> None:
    store = OcrFailureStore(tmp_path, max_samples_per_profile=1)
    store.record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )

    rejected = store.record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 7),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )

    assert rejected.status is OcrFailureRecordStatus.LIMIT_REACHED
    assert len(list((tmp_path / "counter.v1").iterdir())) == 1


def test_failure_store_enforces_process_limit_without_charging_duplicates(tmp_path: Path) -> None:
    store = OcrFailureStore(tmp_path, max_new_samples_per_process=2)
    first = store.record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )
    duplicate = store.record(
        make_invalid_counter_result(),
        raw_image=ALTERNATE_RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )
    second = store.record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 7),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )
    duplicate_at_limit = store.record(
        make_invalid_counter_result(),
        raw_image=ALTERNATE_RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 7),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )
    rejected = store.record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 8),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )

    assert first.status is OcrFailureRecordStatus.SAVED
    assert duplicate.status is OcrFailureRecordStatus.DUPLICATE
    assert second.status is OcrFailureRecordStatus.SAVED
    assert duplicate_at_limit.status is OcrFailureRecordStatus.DUPLICATE
    assert rejected.status is OcrFailureRecordStatus.LIMIT_REACHED


def test_failure_store_rejects_bundle_larger_than_total_byte_budget(tmp_path: Path) -> None:
    root = tmp_path / "too-large"
    store = OcrFailureStore(root, max_total_bytes=1)

    rejected = store.record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )

    assert rejected.status is OcrFailureRecordStatus.TOO_LARGE
    assert rejected.directory is None
    assert not root.exists()


def test_failure_store_enforces_cumulative_byte_limit(tmp_path: Path) -> None:
    first = OcrFailureStore(tmp_path).record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )
    assert first.directory is not None
    byte_budget = bundle_size(first.directory) + 16

    rejected = OcrFailureStore(tmp_path, max_total_bytes=byte_budget).record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 7),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )

    assert rejected.status is OcrFailureRecordStatus.LIMIT_REACHED
    assert len(list((tmp_path / "counter.v1").iterdir())) == 1


def test_failure_store_ignores_and_preserves_unknown_directories(tmp_path: Path) -> None:
    measured = OcrFailureStore(tmp_path / "measurement").record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )
    assert measured.directory is not None
    byte_budget = bundle_size(measured.directory) + 16

    root = tmp_path / "target"
    profile_directory = root / "counter.v1"
    unknown_name = profile_directory / "not-a-digest"
    unknown_name.mkdir(parents=True)
    (unknown_name / "metadata.json").write_bytes(b"x" * (byte_budget * 2))

    invalid_metadata = profile_directory / ("a" * 64)
    invalid_metadata.mkdir()
    (invalid_metadata / "raw.png").write_bytes(b"unknown raw")
    (invalid_metadata / "processed.png").write_bytes(b"unknown processed")
    (invalid_metadata / "metadata.json").write_text(
        json.dumps({"schema_version": 1, "digest": invalid_metadata.name}),
        encoding="utf-8",
    )
    stale_temp = profile_directory / "other-process.abcdef.tmp"
    stale_temp.mkdir()
    (stale_temp / "metadata.json").write_text("leave me", encoding="utf-8")

    saved = OcrFailureStore(root, max_total_samples=1, max_total_bytes=byte_budget).record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )

    assert saved.status is OcrFailureRecordStatus.SAVED
    assert unknown_name.is_dir()
    assert invalid_metadata.is_dir()
    assert stale_temp.is_dir()


@pytest.mark.parametrize(
    "profile",
    ["", ".", "..", "../escape", "nested/profile", "nested\\profile", "bad profile", "计数器", "a" * 65],
)
def test_failure_store_rejects_unsafe_profile_before_writing(tmp_path: Path, profile: str) -> None:
    root = tmp_path / "root"
    result = make_invalid_counter_result()
    object.__setattr__(result, "profile", profile)

    with pytest.raises(ValueError, match="profile"):
        OcrFailureStore(root).record(
            result,
            raw_image=RAW_IMAGE,
            processed_image=PROCESSED_IMAGE,
            area=(1, 2, 5, 6),
            alphabet=None,
            letter=(140, 113, 99),
            threshold=64,
        )

    assert not root.exists()
    assert not (tmp_path / "escape").exists()


def test_failure_store_rejects_successful_result_before_writing(tmp_path: Path) -> None:
    root = tmp_path / "root"
    result = RecognitionResult(
        raw_text="14/15",
        normalized_text="14/15",
        score=0.9,
        value=(14, 1, 15),
        valid=True,
        reason=None,
        latency_seconds=0.1,
        profile="counter.v1",
        model="densenet_lite_136-gru",
    )

    with pytest.raises(ValueError, match="failed"):
        OcrFailureStore(root).record(
            result,
            raw_image=RAW_IMAGE,
            processed_image=PROCESSED_IMAGE,
            area=(1, 2, 5, 6),
            alphabet=None,
            letter=(140, 113, 99),
            threshold=64,
        )

    assert not root.exists()


@pytest.mark.parametrize(
    ("raw_image", "processed_image"),
    [
        (np.empty((0, 4, 3), dtype=np.uint8), PROCESSED_IMAGE),
        (RAW_IMAGE, np.empty((0, 4), dtype=np.uint8)),
        (RAW_IMAGE.astype(np.float32), PROCESSED_IMAGE),
        (RAW_IMAGE, PROCESSED_IMAGE.astype(np.float32)),
        (np.zeros((3, 4, 1), dtype=np.uint8), PROCESSED_IMAGE),
        (np.zeros((3, 4, 2), dtype=np.uint8), PROCESSED_IMAGE),
        (np.zeros((3, 4, 4), dtype=np.uint8), PROCESSED_IMAGE),
        (RAW_IMAGE, np.zeros((3, 4, 3), dtype=np.uint8)),
    ],
    ids=[
        "empty-raw",
        "empty-processed",
        "float-raw",
        "float-processed",
        "one-channel-raw",
        "two-channel-raw",
        "four-channel-raw",
        "three-dimensional-processed",
    ],
)
def test_failure_store_rejects_invalid_images_before_writing(
    tmp_path: Path,
    raw_image: np.ndarray,
    processed_image: np.ndarray,
) -> None:
    root = tmp_path / "root"

    with pytest.raises(ValueError, match="image"):
        OcrFailureStore(root).record(
            make_invalid_counter_result(),
            raw_image=raw_image,
            processed_image=processed_image,
            area=(1, 2, 5, 6),
            alphabet=None,
            letter=(140, 113, 99),
            threshold=64,
        )

    assert not root.exists()


def test_failure_store_cleans_failed_publish_and_disables_after_one_warning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    root = tmp_path / "root"
    store = OcrFailureStore(root, max_new_samples_per_process=1)
    publish_sources: list[Path] = []

    def fail_publish(source: Path, destination: Path) -> None:
        del destination
        publish_sources.append(Path(source))
        raise OSError

    monkeypatch.setattr(failure_store_module, "atomic_replace", fail_publish)
    with caplog.at_level(logging.WARNING, logger="alas"):
        first = store.record(
            make_invalid_counter_result(),
            raw_image=RAW_IMAGE,
            processed_image=PROCESSED_IMAGE,
            area=(1, 2, 5, 6),
            alphabet=None,
            letter=(140, 113, 99),
            threshold=64,
        )
        second = store.record(
            make_invalid_counter_result(),
            raw_image=RAW_IMAGE,
            processed_image=PROCESSED_IMAGE,
            area=(1, 2, 5, 7),
            alphabet=None,
            letter=(140, 113, 99),
            threshold=64,
        )

    assert first.status is OcrFailureRecordStatus.DISABLED
    assert second.status is OcrFailureRecordStatus.DISABLED
    assert len(publish_sources) == 1
    assert not publish_sources[0].exists()
    assert not list(root.rglob("metadata.json"))
    warning_records = [record for record in caplog.records if "OCR failure store disabled" in record.getMessage()]
    assert len(warning_records) == 1


def test_failure_store_treats_competing_complete_publish_as_duplicate(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    competitor = OcrFailureStore(tmp_path / "competitor").record(
        make_invalid_counter_result(),
        raw_image=ALTERNATE_RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )
    assert competitor.directory is not None
    competitor_directory = competitor.directory
    publish_sources: list[Path] = []

    def publish_competitor(source: Path, destination: Path) -> None:
        publish_sources.append(Path(source))
        shutil.copytree(competitor_directory, destination)
        raise FileExistsError(destination)

    monkeypatch.setattr(failure_store_module, "atomic_replace", publish_competitor)
    root = tmp_path / "target"
    store = OcrFailureStore(root, max_new_samples_per_process=1)
    raced = store.record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )

    assert raced.status is OcrFailureRecordStatus.DUPLICATE
    assert raced.directory is not None
    assert not publish_sources[0].exists()
    with Image.open(raced.directory / "raw.png") as image:
        assert np.array_equal(np.asarray(image), ALTERNATE_RAW_IMAGE)

    monkeypatch.undo()
    subsequent = store.record(
        make_invalid_counter_result(),
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 7),
        alphabet=None,
        letter=(140, 113, 99),
        threshold=64,
    )
    assert subsequent.status is OcrFailureRecordStatus.SAVED


def test_failure_store_metadata_replays_digit_counter_parser_offline(tmp_path: Path) -> None:
    stored_result = replace(
        make_invalid_counter_result(),
        raw_text="14/15",
        normalized_text="14/15",
        reason=RecognitionFailureReason.UNEXPECTED_TOTAL,
    )
    stored = OcrFailureStore(tmp_path).record(
        stored_result,
        raw_image=RAW_IMAGE,
        processed_image=PROCESSED_IMAGE,
        area=(1, 2, 5, 6),
        alphabet="0123456789/IDSB",
        letter=(140, 113, 99),
        threshold=64,
        expected_total=10,
    )
    assert stored.directory is not None
    metadata = json.loads((stored.directory / "metadata.json").read_text(encoding="utf-8"))

    replayed = DigitCounter((0, 0, 1, 1), name="counter.v1")._parse_result(
        RawOcrResult(text=metadata["raw_text"], score=metadata["score"]),
        latency_seconds=0.0,
        model=metadata["model"],
        expected_total=metadata["expected_total"],
    )

    assert replayed.normalized_text == metadata["normalized_text"]
    assert replayed.valid is metadata["valid"]
    assert replayed.reason is not None
    assert replayed.reason.value == metadata["reason"]
    assert replayed.value == metadata["value"]
