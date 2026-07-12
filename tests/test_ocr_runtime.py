import sys
from concurrent.futures import ThreadPoolExecutor
from threading import Event
from typing import TYPE_CHECKING, override

import numpy as np
import pytest

import module.base.resource as resource_module
from module.base.resource import Resource
from module.ocr.models import OcrModel, OcrRuntime
from module.ocr.result import RawOcrResult

if TYPE_CHECKING:
    from collections.abc import Collection, Sequence

    from module.base.type_alias import ImageArray

TEST_IMAGE = np.zeros((4, 4), dtype=np.uint8)


class _Session:
    def __init__(self) -> None:
        self.ensure_loaded_calls = 0
        self.alphabets: list[Collection[str] | str | None] = []

    def ensure_loaded(self) -> None:
        self.ensure_loaded_calls += 1

    def atomic_ocr_for_single_lines_raw(
        self,
        img_list: Sequence[ImageArray],
        cand_alphabet: Collection[str] | str | None = None,
    ) -> list[RawOcrResult]:
        self.alphabets.append(cand_alphabet)
        return [RawOcrResult(text=str(cand_alphabet), score=1.0) for _image in img_list]


class _BlockingSession(_Session):
    def __init__(self, first_started: Event, release_first: Event, second_started: Event) -> None:
        super().__init__()
        self.first_started = first_started
        self.release_first = release_first
        self.second_started = second_started

    def atomic_ocr_for_single_lines_raw(
        self,
        img_list: Sequence[ImageArray],
        cand_alphabet: Collection[str] | str | None = None,
    ) -> list[RawOcrResult]:
        if cand_alphabet == "first":
            self.first_started.set()
            assert self.release_first.wait(timeout=5)
        else:
            self.second_started.set()
        return super().atomic_ocr_for_single_lines_raw(img_list, cand_alphabet=cand_alphabet)


def test_logical_model_names_share_one_lazy_runtime() -> None:
    sessions: list[_Session] = []

    def factory() -> _Session:
        session = _Session()
        sessions.append(session)
        return session

    models = OcrModel(factory)

    assert models.azur_lane is models.cnocr
    assert sessions == []

    models.azur_lane.atomic_ocr_for_single_lines_raw([TEST_IMAGE], cand_alphabet="azur_lane")
    models.cnocr.atomic_ocr_for_single_lines_raw([TEST_IMAGE], cand_alphabet="cnocr")

    assert len(sessions) == 1
    assert sessions[0].ensure_loaded_calls == 1
    assert sessions[0].alphabets == ["azur_lane", "cnocr"]


def test_runtime_serializes_first_load_alphabet_and_inference() -> None:
    first_started = Event()
    release_first = Event()
    second_attempted = Event()
    second_started = Event()
    sessions: list[_BlockingSession] = []

    def factory() -> _BlockingSession:
        session = _BlockingSession(first_started, release_first, second_started)
        sessions.append(session)
        return session

    def infer_second(runtime: OcrRuntime) -> list[RawOcrResult]:
        second_attempted.set()
        return runtime.atomic_ocr_for_single_lines_raw([TEST_IMAGE], cand_alphabet="second")

    runtime = OcrRuntime(factory)
    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(runtime.atomic_ocr_for_single_lines_raw, [TEST_IMAGE], "first")
        assert first_started.wait(timeout=5)
        second = executor.submit(infer_second, runtime)
        assert second_attempted.wait(timeout=5)
        assert not second_started.wait(timeout=0.05)
        release_first.set()
        first.result(timeout=5)
        second.result(timeout=5)

    assert len(sessions) == 1
    assert sessions[0].ensure_loaded_calls == 1
    assert sessions[0].alphabets == ["first", "second"]


def test_runtime_release_waits_for_inference_and_recreates_session() -> None:
    first_started = Event()
    release_first = Event()
    second_started = Event()
    release_attempted = Event()
    release_finished = Event()
    sessions: list[_Session] = []

    def factory() -> _Session:
        session = _Session() if sessions else _BlockingSession(first_started, release_first, second_started)
        sessions.append(session)
        return session

    runtime = OcrRuntime(factory)

    def release() -> None:
        release_attempted.set()
        runtime.release()
        release_finished.set()

    with ThreadPoolExecutor(max_workers=2) as executor:
        inference = executor.submit(runtime.atomic_ocr_for_single_lines_raw, [TEST_IMAGE], "first")
        assert first_started.wait(timeout=5)
        releasing = executor.submit(release)
        assert release_attempted.wait(timeout=5)
        assert not release_finished.wait(timeout=0.05)
        release_first.set()
        inference.result(timeout=5)
        releasing.result(timeout=5)

    runtime.atomic_ocr_for_single_lines_raw([TEST_IMAGE], cand_alphabet="after-release")

    assert len(sessions) == 2
    assert sessions[1].alphabets == ["after-release"]


def test_runtime_does_not_cache_failed_initialization() -> None:
    sessions: list[_Session] = []

    class _FailedSession(_Session):
        @override
        def ensure_loaded(self) -> None:
            message = "load failed"
            raise RuntimeError(message)

    def factory() -> _Session:
        session = _FailedSession() if not sessions else _Session()
        sessions.append(session)
        return session

    runtime = OcrRuntime(factory)

    with pytest.raises(RuntimeError, match="load failed"):
        runtime.atomic_ocr_for_single_lines_raw([TEST_IMAGE])

    assert runtime.atomic_ocr_for_single_lines_raw([TEST_IMAGE]) == [RawOcrResult("None", 1.0)]
    assert len(sessions) == 2


def test_release_resources_only_releases_shared_runtime_when_idle(monkeypatch: pytest.MonkeyPatch) -> None:
    release_calls: list[None] = []

    class _Models:
        @staticmethod
        def release() -> None:
            release_calls.append(None)

    monkeypatch.setattr(resource_module, "OCR_MODEL", _Models())
    monkeypatch.setattr(Resource, "instances", {})
    monkeypatch.delitem(sys.modules, "module.map_detection.utils_assets", raising=False)

    resource_module.release_resources(next_task="Daily")
    resource_module.release_resources()

    assert release_calls == [None]
