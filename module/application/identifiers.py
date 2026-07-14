from dataclasses import dataclass


def _validate_identifier(value: str, *, kind: str) -> None:
    if not isinstance(value, str):
        message = f"{kind} must be a string"
        raise TypeError(message)
    if not value or any(character.isspace() for character in value):
        message = f"{kind} must not be empty or contain whitespace"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class TaskId:
    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, kind="task id")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RunId:
    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, kind="run id")

    def __str__(self) -> str:
        return self.value
