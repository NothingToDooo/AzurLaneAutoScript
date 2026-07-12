from bisect import bisect_left
from dataclasses import dataclass, field
from threading import Lock

OCR_WIDTH_BUCKET_UPPER_BOUNDS = (32, 64, 96, 128, 192, 256, 384, 512)
_OCR_WIDTH_BUCKET_COUNT = len(OCR_WIDTH_BUCKET_UPPER_BOUNDS) + 1


@dataclass(frozen=True, slots=True)
class OcrProfileMetrics:
    call_count: int
    total_latency_seconds: float
    max_latency_seconds: float
    roi_count: int
    processed_width_histogram: tuple[tuple[int | None, int], ...]


@dataclass(slots=True)
class _MutableOcrProfileMetrics:
    call_count: int = 0
    total_latency_seconds: float = 0.0
    max_latency_seconds: float = 0.0
    roi_count: int = 0
    processed_width_counts: list[int] = field(default_factory=lambda: [0] * _OCR_WIDTH_BUCKET_COUNT)


class OcrMetrics:
    def __init__(self) -> None:
        self._lock = Lock()
        self._profiles: dict[str, _MutableOcrProfileMetrics] = {}

    def observe(self, profile: str, *, latency_seconds: float, processed_widths: list[int]) -> None:
        with self._lock:
            metrics = self._profiles.get(profile)
            if metrics is None:
                metrics = _MutableOcrProfileMetrics()
                self._profiles[profile] = metrics
            metrics.call_count += 1
            metrics.total_latency_seconds += latency_seconds
            metrics.max_latency_seconds = max(metrics.max_latency_seconds, latency_seconds)
            metrics.roi_count += len(processed_widths)
            for width in processed_widths:
                bucket = bisect_left(OCR_WIDTH_BUCKET_UPPER_BOUNDS, width)
                metrics.processed_width_counts[bucket] += 1

    def snapshot(self) -> dict[str, OcrProfileMetrics]:
        bucket_limits: tuple[int | None, ...] = (*OCR_WIDTH_BUCKET_UPPER_BOUNDS, None)
        with self._lock:
            return {
                profile: OcrProfileMetrics(
                    call_count=metrics.call_count,
                    total_latency_seconds=metrics.total_latency_seconds,
                    max_latency_seconds=metrics.max_latency_seconds,
                    roi_count=metrics.roi_count,
                    processed_width_histogram=tuple(zip(bucket_limits, metrics.processed_width_counts, strict=True)),
                )
                for profile, metrics in self._profiles.items()
            }


OCR_METRICS = OcrMetrics()
