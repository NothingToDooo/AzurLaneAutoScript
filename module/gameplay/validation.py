from datetime import datetime, timedelta


def validate_aware_datetime(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.tzinfo is None or value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)


def validate_positive_duration(value: timedelta, *, field_name: str) -> None:
    if not isinstance(value, timedelta):
        message = f"{field_name} must be a timedelta"
        raise TypeError(message)
    if value <= timedelta(0):
        message = f"{field_name} must be positive"
        raise ValueError(message)


def validate_bool(*, value: bool, field_name: str) -> None:
    if type(value) is not bool:
        message = f"{field_name} must be a bool"
        raise TypeError(message)


def validate_non_negative_integer(value: int, *, field_name: str) -> None:
    if type(value) is not int:
        message = f"{field_name} must be an integer"
        raise TypeError(message)
    if value < 0:
        message = f"{field_name} must be non-negative"
        raise ValueError(message)


def validate_positive_integer(value: int, *, field_name: str) -> None:
    if type(value) is not int:
        message = f"{field_name} must be an integer"
        raise TypeError(message)
    if value <= 0:
        message = f"{field_name} must be positive"
        raise ValueError(message)
