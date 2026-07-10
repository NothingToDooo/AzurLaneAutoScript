from dataclasses import dataclass

from module.content.errors import ContentValidationError


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    location: str
    message: str


def require_non_empty_identifier(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value.strip():
        message = f"{field_name} must not be empty or whitespace"
        raise ContentValidationError(message)
