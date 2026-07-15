import pytest

from module.config.json_codec import (
    DuplicateJsonFieldError,
    NonFiniteJsonNumberError,
    StrictJsonDecodeError,
    decode_json,
)


def test_decode_json_returns_the_decoded_object() -> None:
    assert decode_json(b'{"enabled": true}') == {"enabled": True}


def test_decode_json_rejects_duplicate_fields_with_the_field_name() -> None:
    with pytest.raises(DuplicateJsonFieldError, match="duplicate JSON field: enabled") as caught:
        decode_json('{"enabled": true, "enabled": false}')

    assert caught.value.field == "enabled"


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_decode_json_rejects_non_finite_numbers_with_the_constant(constant: str) -> None:
    with pytest.raises(NonFiniteJsonNumberError, match=constant) as caught:
        decode_json(f'{{"value": {constant}}}')

    assert caught.value.constant == constant


def test_decode_json_wraps_malformed_json() -> None:
    with pytest.raises(StrictJsonDecodeError, match="invalid JSON at line 1 column 2"):
        decode_json("{")
