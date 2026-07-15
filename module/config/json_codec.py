import json
from typing import Never


class StrictJsonDecodeError(ValueError):
    pass


class DuplicateJsonFieldError(StrictJsonDecodeError):
    def __init__(self, field: str) -> None:
        self.field = field
        super().__init__(f"duplicate JSON field: {field}")


class NonFiniteJsonNumberError(StrictJsonDecodeError):
    def __init__(self, constant: str) -> None:
        self.constant = constant
        super().__init__(f"non-finite JSON number: {constant}")


def _unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonFieldError(key)
        result[key] = value
    return result


def _reject_non_finite_constant(constant: str) -> Never:
    raise NonFiniteJsonNumberError(constant)


def decode_json(content: str | bytes | bytearray) -> object:
    """严格解码 JSON，拒绝重复字段和非有限数字。"""

    if not isinstance(content, (str, bytes, bytearray)):
        message = "JSON content must be text or bytes"
        raise TypeError(message)
    try:
        return json.loads(
            content,
            object_pairs_hook=_unique_object,
            parse_constant=_reject_non_finite_constant,
        )
    except StrictJsonDecodeError:
        raise
    except json.JSONDecodeError as error:
        message = f"invalid JSON at line {error.lineno} column {error.colno}: {error.msg}"
        raise StrictJsonDecodeError(message) from error
