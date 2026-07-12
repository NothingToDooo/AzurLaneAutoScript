from dataclasses import dataclass
from typing import TYPE_CHECKING, TypedDict, override

import numpy as np
import pytest

from module.exception import ScriptError
from module.meowfficer import buy as buy_module
from module.meowfficer.buy import MeowfficerBuy
from module.ocr.failure_store import OCR_FAILURE_STORE, OcrFailureStore
from module.ocr.result import RecognitionFailureReason, RecognitionResult

if TYPE_CHECKING:
    from collections.abc import Iterator

    from module.base.timer import Timer
    from module.base.type_alias import ImageArray


class _OcrCall(TypedDict):
    expected_total: int | None
    failure_store: OcrFailureStore | None


class SequenceOcr[T]:
    def __init__(self, results: list[RecognitionResult[T]]) -> None:
        self._results = iter(results)
        self.calls: list[_OcrCall] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def recognize(
        self,
        image: ImageArray,
        *,
        expected_total: int | None = None,
        failure_store: OcrFailureStore | None = None,
    ) -> RecognitionResult[T]:
        del image
        self.calls.append({"expected_total": expected_total, "failure_store": failure_store})
        return next(self._results)


class ListOcr[T]:
    def __init__(self, result: RecognitionResult[T]) -> None:
        self._result = result
        self.calls: list[_OcrCall] = []

    def recognize(
        self,
        image: ImageArray,
        *,
        expected_total: int | None = None,
        failure_store: OcrFailureStore | None = None,
    ) -> list[RecognitionResult[T]]:
        del image
        self.calls.append({"expected_total": expected_total, "failure_store": failure_store})
        return [self._result]


@dataclass(slots=True)
class _BuyerDevice:
    image: ImageArray


@dataclass(slots=True)
class _BuyerConfig:
    Error_SaveError: bool


class _TestBuyer(MeowfficerBuy):
    config: _BuyerConfig
    device: _BuyerDevice

    def __init__(self, frames: list[ImageArray], *, save_error: bool) -> None:
        self._frames = frames
        self.device = _BuyerDevice(frames[0])
        self.config = _BuyerConfig(Error_SaveError=save_error)

    @override
    def loop(
        self,
        *,
        skip_first: bool = True,
        timeout: float | Timer | None = None,
    ) -> Iterator[ImageArray]:
        del skip_first, timeout
        for frame in self._frames:
            self.device.image = frame
            yield frame


def make_buyer_with_frames(count: int, *, save_error: bool) -> _TestBuyer:
    frames = [np.full((2, 2, 3), index, dtype=np.uint8) for index in range(count)]
    return _TestBuyer(frames, save_error=save_error)


def valid_counter(value: tuple[int, int, int]) -> RecognitionResult[tuple[int, int, int]]:
    current, _remain, total = value
    text = f"{current}/{total}"
    return RecognitionResult(
        raw_text=text,
        normalized_text=text,
        score=1.0,
        value=value,
        valid=True,
        reason=None,
        latency_seconds=0.0,
        profile="meowfficer-counter",
        model="test-model",
    )


def invalid_counter(
    raw_text: str,
    reason: RecognitionFailureReason = RecognitionFailureReason.FORMAT_MISMATCH,
) -> RecognitionResult[tuple[int, int, int]]:
    return RecognitionResult(
        raw_text=raw_text,
        normalized_text=raw_text,
        score=0.0,
        value=None,
        valid=False,
        reason=reason,
        latency_seconds=0.0,
        profile="meowfficer-counter",
        model="test-model",
    )


def valid_digit(value: int) -> RecognitionResult[int]:
    text = str(value)
    return RecognitionResult(
        raw_text=text,
        normalized_text=text,
        score=1.0,
        value=value,
        valid=True,
        reason=None,
        latency_seconds=0.0,
        profile="meowfficer-coins",
        model="test-model",
    )


def invalid_digit(raw_text: str) -> RecognitionResult[int]:
    return RecognitionResult(
        raw_text=raw_text,
        normalized_text=raw_text,
        score=0.0,
        value=None,
        valid=False,
        reason=RecognitionFailureReason.FORMAT_MISMATCH,
        latency_seconds=0.0,
        profile="meowfficer-coins",
        model="test-model",
    )


def test_buy_count_retries_counter_before_reading_coins(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = SequenceOcr([invalid_counter("loading"), valid_counter((15, 0, 15))])
    coins = SequenceOcr([valid_digit(1500)])
    buyer = make_buyer_with_frames(2, save_error=True)
    monkeypatch.setattr(buy_module, "MEOWFFICER", counter)
    monkeypatch.setattr(buy_module, "MEOWFFICER_COINS", coins)

    assert buyer.meow_get_buy_count(buy_amount=1, overflow_th=-1) == 1
    assert counter.call_count == 2
    assert coins.call_count == 1
    assert counter.calls == [
        {"expected_total": 15, "failure_store": OCR_FAILURE_STORE},
        {"expected_total": 15, "failure_store": OCR_FAILURE_STORE},
    ]
    assert coins.calls == [{"expected_total": None, "failure_store": OCR_FAILURE_STORE}]


def test_buy_count_passes_counter_constraint_and_default_failure_store(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = SequenceOcr([valid_counter((15, 0, 15))])
    coins = SequenceOcr([valid_digit(1500)])
    buyer = make_buyer_with_frames(1, save_error=True)
    monkeypatch.setattr(buy_module, "MEOWFFICER", counter)
    monkeypatch.setattr(buy_module, "MEOWFFICER_COINS", coins)

    assert buyer.meow_get_buy_count(buy_amount=1, overflow_th=-1) == 1
    assert counter.calls == [{"expected_total": 15, "failure_store": OCR_FAILURE_STORE}]
    assert coins.calls == [{"expected_total": None, "failure_store": OCR_FAILURE_STORE}]


def test_buy_count_disables_failure_store_with_save_error_off(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = SequenceOcr([valid_counter((15, 0, 15))])
    coins = SequenceOcr([valid_digit(1500)])
    buyer = make_buyer_with_frames(1, save_error=False)
    monkeypatch.setattr(buy_module, "MEOWFFICER", counter)
    monkeypatch.setattr(buy_module, "MEOWFFICER_COINS", coins)

    assert buyer.meow_get_buy_count(buy_amount=1, overflow_th=-1) == 1
    assert counter.calls == [{"expected_total": 15, "failure_store": None}]
    assert coins.calls == [{"expected_total": None, "failure_store": None}]


def test_buy_count_accepts_zero_counter_and_zero_coins(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = SequenceOcr([valid_counter((0, 15, 15)), valid_counter((15, 0, 15))])
    coins = SequenceOcr([valid_digit(0), valid_digit(1500)])
    buyer = make_buyer_with_frames(2, save_error=False)
    monkeypatch.setattr(buy_module, "MEOWFFICER", counter)
    monkeypatch.setattr(buy_module, "MEOWFFICER_COINS", coins)

    assert buyer.meow_get_buy_count(buy_amount=1, overflow_th=-1) == 0
    assert counter.call_count == 1
    assert coins.call_count == 1


def test_buy_count_skips_coins_for_unexpected_total(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = SequenceOcr(
        [invalid_counter("0/0", reason=RecognitionFailureReason.UNEXPECTED_TOTAL)],
    )
    coins = SequenceOcr([])
    buyer = make_buyer_with_frames(1, save_error=True)
    monkeypatch.setattr(buy_module, "MEOWFFICER", counter)
    monkeypatch.setattr(buy_module, "MEOWFFICER_COINS", coins)

    assert buyer.meow_get_buy_count(buy_amount=1, overflow_th=-1) == 0
    assert counter.calls == [{"expected_total": 15, "failure_store": OCR_FAILURE_STORE}]
    assert coins.call_count == 0


def test_buy_count_retries_entire_frame_when_coins_are_invalid(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = SequenceOcr([valid_counter((15, 0, 15)), valid_counter((15, 0, 15))])
    coins = SequenceOcr([invalid_digit("coins"), valid_digit(1500)])
    buyer = make_buyer_with_frames(2, save_error=True)
    monkeypatch.setattr(buy_module, "MEOWFFICER", counter)
    monkeypatch.setattr(buy_module, "MEOWFFICER_COINS", coins)

    assert buyer.meow_get_buy_count(buy_amount=1, overflow_th=-1) == 1
    assert counter.call_count == 2
    assert coins.call_count == 2


def test_buy_count_returns_zero_and_warns_after_finite_failures(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = SequenceOcr([invalid_counter("loading"), invalid_counter("loading")])
    coins = SequenceOcr([])
    buyer = make_buyer_with_frames(2, save_error=False)
    warnings: list[str] = []
    monkeypatch.setattr(buy_module, "MEOWFFICER", counter)
    monkeypatch.setattr(buy_module, "MEOWFFICER_COINS", coins)
    monkeypatch.setattr(buy_module.logger, "warning", warnings.append)

    assert buyer.meow_get_buy_count(buy_amount=1, overflow_th=-1) == 0
    assert counter.call_count == 2
    assert coins.call_count == 0
    assert warnings == ["Failed to get meowfficer buy status"]


def test_buy_count_rejects_list_from_single_coin_roi(monkeypatch: pytest.MonkeyPatch) -> None:
    counter = SequenceOcr([valid_counter((15, 0, 15))])
    coins = ListOcr(valid_digit(1500))
    buyer = make_buyer_with_frames(1, save_error=False)
    monkeypatch.setattr(buy_module, "MEOWFFICER", counter)
    monkeypatch.setattr(buy_module, "MEOWFFICER_COINS", coins)

    with pytest.raises(ScriptError, match="MEOWFFICER_COINS 必须使用单个 OCR 区域"):
        buyer.meow_get_buy_count(buy_amount=1, overflow_th=-1)
