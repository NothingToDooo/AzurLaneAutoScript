from datetime import datetime, timedelta, tzinfo
from typing import TYPE_CHECKING, cast

import pytest

import module.config.utils as config_utils
from module.config.utils import (
    dict_to_kv,
    get_server_last_update,
    get_server_next_update,
    read_file,
    server_time_offset,
    write_file,
)

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from module.config.deep import MutableDeepData


class _FixedDatetime(datetime):
    @classmethod
    def now(cls, tz: tzinfo | None = None) -> _FixedDatetime:
        return cls(2026, 7, 10, 11, 30, tzinfo=tz)


def test_cn_personal_branch_uses_local_time_as_server_time() -> None:
    assert server_time_offset() == timedelta()


def test_write_file_serializes_datetime_explicitly(tmp_path: Path) -> None:
    path = tmp_path / "config.json"

    write_file(path, {"NextRun": datetime(2026, 7, 16, 9, 30, 45)})

    assert '"NextRun": "2026-07-16 09:30:45"' in path.read_text(encoding="utf-8")


def test_write_file_rejects_unknown_object_without_overwriting(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"kept": true}', encoding="utf-8")
    invalid = cast("MutableDeepData", {"Broken": object()})

    with pytest.raises(TypeError, match="unsupported JSON value type: object"):
        write_file(path, invalid)

    assert path.read_text(encoding="utf-8") == '{"kept": true}'


def test_write_file_rejects_non_finite_number_without_overwriting(tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text('{"kept": true}', encoding="utf-8")

    with pytest.raises(ValueError, match="Out of range float values"):
        write_file(path, {"Broken": float("nan")})

    assert path.read_text(encoding="utf-8") == '{"kept": true}'


@pytest.mark.parametrize(
    "content",
    ['{"value": 1, "value": 2}', '{"value": NaN}', '{"value": Infinity}'],
)
def test_read_file_rejects_non_canonical_json(content: str, tmp_path: Path) -> None:
    path = tmp_path / "config.json"
    path.write_text(content, encoding="utf-8")

    with pytest.raises(ValueError, match=r"duplicate JSON field|non-finite number"):
        read_file(path)


def test_config_log_includes_smtp_password_for_local_debugging() -> None:
    credential_value = "local-smtp-password"
    output = dict_to_kv(
        {
            "Alas.Error.SmtpPassword": credential_value,
            "GemsFarming.Scheduler.Enable": True,
        }
    )

    assert f"Alas.Error.SmtpPassword={credential_value!r}" in output
    assert "GemsFarming.Scheduler.Enable=True" in output


def test_server_update_selects_nearest_nonempty_trigger(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(config_utils, "datetime", _FixedDatetime)

    assert get_server_next_update(["10:00", "12:00"]) == datetime(2026, 7, 10, 12)
    assert get_server_last_update(["10:00", "12:00"]) == datetime(2026, 7, 10, 10)


@pytest.mark.parametrize("get_update", [get_server_next_update, get_server_last_update])
def test_server_update_rejects_empty_trigger(get_update: Callable[[list[str]], datetime]) -> None:
    with pytest.raises(ValueError, match="daily_trigger"):
        get_update([])
