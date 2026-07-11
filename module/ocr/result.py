from dataclasses import dataclass
from enum import StrEnum
from math import isfinite


@dataclass(frozen=True, slots=True)
class RawOcrResult:
    text: str
    score: float


class RecognitionFailureReason(StrEnum):
    EMPTY_TEXT = "empty_text"
    FORMAT_MISMATCH = "format_mismatch"
    CURRENT_EXCEEDS_TOTAL = "current_exceeds_total"
    UNEXPECTED_TOTAL = "unexpected_total"
    TIME_COMPONENT_OUT_OF_RANGE = "time_component_out_of_range"


@dataclass(frozen=True, slots=True)
class RecognitionResult[T]:
    raw_text: str
    normalized_text: str
    score: float
    value: T | None
    valid: bool
    reason: RecognitionFailureReason | None
    latency_seconds: float
    profile: str
    model: str

    def __post_init__(self) -> None:
        if not self.profile.strip():
            message = "profile must not be blank"
            raise ValueError(message)
        if not self.model.strip():
            message = "model must not be blank"
            raise ValueError(message)
        if not isfinite(self.score) or not 0 <= self.score <= 1:
            message = "score must be finite and between 0 and 1"
            raise ValueError(message)
        if not isfinite(self.latency_seconds) or self.latency_seconds < 0:
            message = "latency_seconds must be finite and non-negative"
            raise ValueError(message)
        if self.valid and (self.value is None or self.reason is not None):
            message = "successful result must have a value and no failure reason"
            raise ValueError(message)
        if not self.valid and (self.value is not None or self.reason is None):
            message = "failed result must have no value and a failure reason"
            raise ValueError(message)
