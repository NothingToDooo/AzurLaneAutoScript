from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType

import pytest

from module.runtime import (
    FrozenJsonValue,
    SettingsDecoder,
    SettingsDocumentError,
)


class _Mode(StrEnum):
    SAFE = "safe"
    FAST = "fast"


@dataclass(frozen=True, slots=True)
class _Settings:
    enabled: bool
    retries: int
    threshold: float
    name: str
    labels: tuple[str, ...]
    weights: tuple[int, ...]
    due_at: datetime
    mode: _Mode
    nested_value: str


def _decoder(settings: dict[str, FrozenJsonValue]) -> SettingsDecoder:
    return SettingsDecoder(MappingProxyType(settings), path="$.tasks.restart")


def _decode(decoder: SettingsDecoder) -> _Settings:
    nested = decoder.object("nested")
    nested_value = nested.string("value")
    nested.finish()
    return _Settings(
        enabled=decoder.boolean("enabled"),
        retries=decoder.integer("retries", minimum=0, maximum=10),
        threshold=decoder.number("threshold", minimum=0.0, maximum=1.0),
        name=decoder.string("name"),
        labels=decoder.string_tuple("labels", allow_empty=False),
        weights=decoder.integer_tuple("weights", length=3, minimum=1),
        due_at=decoder.datetime("due_at"),
        mode=decoder.enum("mode", _Mode),
        nested_value=nested_value,
    )


def _valid_settings() -> dict[str, FrozenJsonValue]:
    return {
        "enabled": True,
        "retries": 2,
        "threshold": 0.75,
        "name": "primary",
        "labels": ("one", "two"),
        "weights": (1_000, 900, 800),
        "due_at": "2026-07-13T16:00:00+08:00",
        "mode": "safe",
        "nested": MappingProxyType({"value": "nested"}),
    }


def test_decoder_decodes_all_fields_and_normalizes_datetime() -> None:
    decoder = _decoder(_valid_settings())

    settings = _decode(decoder)
    decoder.finish()

    assert settings == _Settings(
        enabled=True,
        retries=2,
        threshold=0.75,
        name="primary",
        labels=("one", "two"),
        weights=(1_000, 900, 800),
        due_at=datetime(2026, 7, 13, 8, tzinfo=UTC),
        mode=_Mode.SAFE,
        nested_value="nested",
    )


@pytest.mark.parametrize(
    ("field", "value", "match"),
    [
        ("enabled", 1, "must be a boolean"),
        ("retries", -1, "at least 0"),
        ("threshold", 1, "must be a float"),
        ("name", " padded ", "trimmed non-empty"),
        ("labels", (), "must not be empty"),
        ("weights", (1_000, 900), "exactly 3"),
        ("weights", (1_000, 0, 800), "at least 1"),
        ("weights", (1_000, "900", 800), "must be an integer"),
        ("due_at", "2026-07-13T08:00:00", "timezone-aware"),
        ("mode", "removed", "must be one of"),
    ],
)
def test_decoder_rejects_invalid_typed_fields(field: str, value: FrozenJsonValue, match: str) -> None:
    settings = _valid_settings()
    settings[field] = value

    with pytest.raises(SettingsDocumentError, match=match):
        _decode(_decoder(settings))


def test_decoder_rejects_missing_unknown_and_double_consumption() -> None:
    missing = _valid_settings()
    del missing["name"]
    with pytest.raises(SettingsDocumentError, match="missing required setting"):
        _decode(_decoder(missing))

    unknown = _valid_settings()
    unknown["obsolete"] = True
    unknown_decoder = _decoder(unknown)
    _decode(unknown_decoder)
    with pytest.raises(SettingsDocumentError, match="unknown settings"):
        unknown_decoder.finish()

    decoder = SettingsDecoder(MappingProxyType({"name": "value"}), path="$.task")
    assert decoder.string("name") == "value"
    with pytest.raises(RuntimeError, match="decoded more than once"):
        decoder.string("name")
