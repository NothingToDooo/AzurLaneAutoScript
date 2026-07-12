from concurrent.futures import ThreadPoolExecutor

import pytest

from module.ocr.metrics import OcrMetrics


def test_metrics_aggregate_profiles_latency_and_fixed_width_buckets() -> None:
    metrics = OcrMetrics()

    metrics.observe("counter", latency_seconds=0.25, processed_widths=[1, 32, 33, 64, 65, 512, 513])
    metrics.observe("counter", latency_seconds=0.5, processed_widths=[])
    metrics.observe("duration", latency_seconds=0.125, processed_widths=[96])

    snapshot = metrics.snapshot()
    counter = snapshot["counter"]
    assert counter.call_count == 2
    assert counter.total_latency_seconds == 0.75
    assert counter.max_latency_seconds == 0.5
    assert counter.roi_count == 7
    assert counter.processed_width_histogram == (
        (32, 2),
        (64, 2),
        (96, 1),
        (128, 0),
        (192, 0),
        (256, 0),
        (384, 0),
        (512, 1),
        (None, 1),
    )
    assert snapshot["duration"].call_count == 1


def test_metrics_snapshot_is_detached_from_future_observations() -> None:
    metrics = OcrMetrics()
    metrics.observe("counter", latency_seconds=0.25, processed_widths=[32])

    first = metrics.snapshot()
    metrics.observe("counter", latency_seconds=0.5, processed_widths=[64])

    assert first["counter"].call_count == 1
    assert first["counter"].processed_width_histogram[0] == (32, 1)
    assert metrics.snapshot()["counter"].call_count == 2


def test_metrics_concurrent_observations_are_consistent() -> None:
    metrics = OcrMetrics()

    def observe_many(_worker: int) -> None:
        for _iteration in range(200):
            metrics.observe("shared", latency_seconds=0.001, processed_widths=[32, 513])

    with ThreadPoolExecutor(max_workers=8) as executor:
        list(executor.map(observe_many, range(8)))

    shared = metrics.snapshot()["shared"]
    assert shared.call_count == 1600
    assert shared.total_latency_seconds == pytest.approx(1.6)
    assert shared.roi_count == 3200
    assert shared.processed_width_histogram[0] == (32, 1600)
    assert shared.processed_width_histogram[-1] == (None, 1600)
