from datetime import UTC, datetime
from typing import cast

import pytest

from module.runtime import FrozenJsonValue, TaskStateDocument, TaskStateDocumentError, TaskStateEntry

_NOW = datetime(2026, 7, 13, 8, tzinfo=UTC)


def test_task_state_document_is_deeply_read_only_and_detached_from_payload() -> None:
    payload: object = {"cursor": {"visited": ["a", "b"]}}
    entry = TaskStateEntry(schema_version=3, payload=cast("FrozenJsonValue", payload), updated_at=_NOW)
    document = TaskStateDocument("restart", {"checkpoint": entry})
    raw_cursor = cast("dict[str, object]", cast("dict[str, object]", payload)["cursor"])
    cast("list[str]", raw_cursor["visited"]).append("c")

    stored = document.get("checkpoint")
    assert stored is not None
    frozen_payload = cast("dict[str, FrozenJsonValue]", stored.payload)
    frozen_cursor = cast("dict[str, FrozenJsonValue]", frozen_payload["cursor"])
    assert frozen_cursor["visited"] == ("a", "b")
    with pytest.raises(TypeError):
        cast("dict[str, object]", document.entries)["new"] = entry
    with pytest.raises(TypeError):
        cast("dict[str, object]", frozen_cursor)["new"] = True


def test_task_state_document_rejects_invalid_entries_and_non_json_payloads() -> None:
    with pytest.raises(TypeError, match="TaskStateEntry"):
        TaskStateDocument("restart", {"checkpoint": cast("TaskStateEntry", object())})
    with pytest.raises(TaskStateDocumentError, match="only JSON"):
        TaskStateEntry(
            schema_version=1,
            payload=cast("FrozenJsonValue", {"unsupported": object()}),
            updated_at=_NOW,
        )
