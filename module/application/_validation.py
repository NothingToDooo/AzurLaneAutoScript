def validate_reason(reason: str) -> None:
    if not isinstance(reason, str):
        message = "reason must be a string"
        raise TypeError(message)
    if not reason.strip() or reason != reason.strip():
        message = "reason must not be blank or contain surrounding whitespace"
        raise ValueError(message)


def validate_optional_reason(reason: str | None) -> None:
    if reason is not None:
        validate_reason(reason)
