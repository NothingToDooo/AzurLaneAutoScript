from dataclasses import dataclass

from module.application._validation import validate_reason


@dataclass(frozen=True, slots=True)
class Succeeded:
    pass


@dataclass(frozen=True, slots=True)
class Deferred:
    reason: str

    def __post_init__(self) -> None:
        validate_reason(self.reason)


@dataclass(frozen=True, slots=True)
class Retryable:
    reason: str

    def __post_init__(self) -> None:
        validate_reason(self.reason)


@dataclass(frozen=True, slots=True)
class Blocked:
    reason: str

    def __post_init__(self) -> None:
        validate_reason(self.reason)


@dataclass(frozen=True, slots=True)
class Cancelled:
    reason: str

    def __post_init__(self) -> None:
        validate_reason(self.reason)


@dataclass(frozen=True, slots=True)
class Faulted:
    error: Exception

    def __post_init__(self) -> None:
        if not isinstance(self.error, Exception):
            message = "error must be an Exception"
            raise TypeError(message)


type RunOutcome = Succeeded | Deferred | Retryable | Blocked | Cancelled | Faulted
