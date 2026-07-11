from types import SimpleNamespace
from typing import cast

import numpy as np
import pytest

from module.exception import ScriptError
from module.meowfficer import buy as buy_module
from module.meowfficer.buy import MeowfficerBuy
from module.ocr.failure_store import OCR_FAILURE_STORE
from module.ocr.result import RecognitionFailureReason, RecognitionResult


class SequenceOcr:
    def __init__(self, results: list[RecognitionResult[object]]) -> None:
        self._results = iter(results)
        self.calls: list[dict[str, object]] = []

    @property
    def call_count(self) -> int:
        return len(self.calls)

    def recognize(
        self,
        image: np.ndarray,
        direct_ocr: bool = False,  # noqa: FBT001
        *,
        expected_total: int | None = None,
        failure_store: object | None = None,
    ) -> RecognitionResult[object]:
        del image, direct_ocr
        self.calls.append({"expected_total": expected_total, "failure_store": failure_store})
        return next(self._results)


class ListOcr:
    def __init__(self, result: RecognitionResult[object]) -> None:
        self._result = result
        self.calls: list[dict[str, object]] = []

    def recognize(
        self,
        image: np.ndarray,
        direct_ocr: bool = False,  # noqa: FBT001
        *,
        expected_total: int | None = None,
        failure_store: object | None = None,
    ) -> list[RecognitionResult[object]]:
        del image, direct_ocr
        self.calls.append({"expected_total": expected_total, "failure_store": failure_store})
        return [self._result]


class _TestBuyer:
    _meow_get_buy_count = staticmethod(MeowfficerBuy._meow_get_buy_count)  # noqa: SLF001

    def __init__(self, frames: list[np.ndarray], *, save_error: bool) -> None:
        self._frames = frames
        self.device = SimpleNamespace(image=frames[0])
        self.config = SimpleNamespace(Error_SaveError=save_error)

    def loop(self, skip_first=True, timeout=None):
        del skip_first, timeout
        for frame in self._frames:
            self.device.image = frame
            yield frame

    def meow_get_buy_count(self, buy_amount: int, overflow_th: int) -> int:
        buyer = cast("MeowfficerBuy", self)
        return MeowfficerBuy.meow_get_buy_count(buyer, buy_amount, overflow_th)


def make_buyer_with_frames(count: int, *, save_error: bool) -> _TestBuyer:
    frames = [np.full((2, 2, 3), index, dtype=np.uint8) for index in range(count)]
    return _TestBuyer(frames, save_error=save_error)


def valid_counter(value: tuple[int, int, int]) -> RecognitionResult[object]:
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
) -> RecognitionResult[object]:
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


def valid_digit(value: int) -> RecognitionResult[object]:
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


def invalid_digit(raw_text: str) -> RecognitionResult[object]:
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
