import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, cast

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType
    from typing import Self

from module.state.errors import (
    CorruptStateError,
    OutboxStateError,
    RevisionConflictError,
    RunStateError,
    SchemaVersionError,
)
from module.state.models import (
    ConfigurationSourceSnapshot,
    DeleteTaskStateMutation,
    JsonValue,
    OutboxRecord,
    RunEvent,
    RunEventRecord,
    RunFinalization,
    RunMode,
    RunRecord,
    RunStatus,
    ScheduleMutation,
    ScheduleRecord,
    SettingsSnapshot,
    TaskResolutionSnapshot,
    TaskStateMutation,
    TaskStateRecord,
    UpsertTaskStateMutation,
)

SCHEMA_VERSION = 2
_RUN_MUTATIONS_SKIPPED_EVENT = "run.mutations.skipped"

type _EncodedTaskStateMutation = tuple[TaskStateMutation, str | None]

_SCHEMA_STATEMENTS = (
    """
    CREATE TABLE settings (
        singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
        revision INTEGER NOT NULL CHECK (revision > 0),
        payload TEXT NOT NULL CHECK (json_valid(payload)),
        updated_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE configuration_source (
        singleton INTEGER PRIMARY KEY REFERENCES settings(singleton) ON DELETE CASCADE CHECK (singleton = 1),
        source_revision TEXT NOT NULL CHECK (
            length(source_revision) > 0 AND source_revision = trim(source_revision)
        ),
        settings_revision INTEGER NOT NULL CHECK (settings_revision > 0),
        updated_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE schedule (
        task_id TEXT PRIMARY KEY,
        enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
        due_at TEXT,
        priority INTEGER NOT NULL,
        updated_at TEXT NOT NULL
    ) STRICT
    """,
    """
    CREATE TABLE task_state (
        namespace TEXT NOT NULL,
        key TEXT NOT NULL,
        version INTEGER NOT NULL CHECK (version > 0),
        payload TEXT NOT NULL CHECK (json_valid(payload)),
        updated_at TEXT NOT NULL,
        PRIMARY KEY (namespace, key)
    ) STRICT
    """,
    """
    CREATE TABLE runs (
        run_id TEXT PRIMARY KEY,
        task_id TEXT NOT NULL,
        mode TEXT NOT NULL CHECK (mode IN ('scheduled_job', 'assist_session', 'direct_command')),
        settings_revision INTEGER NOT NULL CHECK (settings_revision > 0),
        content_revision TEXT NOT NULL CHECK (
            length(content_revision) > 0 AND content_revision = trim(content_revision)
        ),
        client_ui_revision TEXT NOT NULL CHECK (
            length(client_ui_revision) > 0 AND client_ui_revision = trim(client_ui_revision)
        ),
        status TEXT NOT NULL CHECK (
            status IN ('running', 'succeeded', 'deferred', 'retryable', 'blocked', 'cancelled', 'faulted')
        ),
        started_at TEXT NOT NULL,
        finished_at TEXT,
        result_payload TEXT CHECK (result_payload IS NULL OR json_valid(result_payload)),
        error TEXT,
        CHECK (
            (status = 'running' AND finished_at IS NULL AND result_payload IS NULL AND error IS NULL)
            OR (status != 'running' AND finished_at IS NOT NULL)
        )
    ) STRICT
    """,
    """
    CREATE TABLE run_events (
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
        sequence INTEGER NOT NULL CHECK (sequence > 0),
        kind TEXT NOT NULL,
        payload TEXT NOT NULL CHECK (json_valid(payload)),
        occurred_at TEXT NOT NULL,
        PRIMARY KEY (run_id, sequence)
    ) STRICT
    """,
    """
    CREATE TABLE outbox (
        message_id TEXT PRIMARY KEY,
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
        topic TEXT NOT NULL,
        message_key TEXT,
        payload TEXT NOT NULL CHECK (json_valid(payload)),
        created_at TEXT NOT NULL,
        published_at TEXT
    ) STRICT
    """,
)

_EXPECTED_COLUMNS = {
    "settings": ("singleton", "revision", "payload", "updated_at"),
    "configuration_source": ("singleton", "source_revision", "settings_revision", "updated_at"),
    "schedule": ("task_id", "enabled", "due_at", "priority", "updated_at"),
    "task_state": ("namespace", "key", "version", "payload", "updated_at"),
    "runs": (
        "run_id",
        "task_id",
        "mode",
        "settings_revision",
        "content_revision",
        "client_ui_revision",
        "status",
        "started_at",
        "finished_at",
        "result_payload",
        "error",
    ),
    "run_events": ("run_id", "sequence", "kind", "payload", "occurred_at"),
    "outbox": ("message_id", "run_id", "topic", "message_key", "payload", "created_at", "published_at"),
}

_TABLE_INFO_QUERIES = {
    "settings": "PRAGMA table_info(settings)",
    "configuration_source": "PRAGMA table_info(configuration_source)",
    "schedule": "PRAGMA table_info(schedule)",
    "task_state": "PRAGMA table_info(task_state)",
    "runs": "PRAGMA table_info(runs)",
    "run_events": "PRAGMA table_info(run_events)",
    "outbox": "PRAGMA table_info(outbox)",
}


def _require_non_empty_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value.strip():
        message = f"{field_name} must not be empty or whitespace"
        raise ValueError(message)


def _require_non_negative_integer(value: int, *, field_name: str) -> None:
    if type(value) is not int or value < 0:
        message = f"{field_name} must be a non-negative integer"
        raise ValueError(message)


def _require_positive_integer(value: int, *, field_name: str) -> None:
    if type(value) is not int or value <= 0:
        message = f"{field_name} must be a positive integer"
        raise ValueError(message)


def _require_trimmed_non_empty_text(value: str, *, field_name: str) -> None:
    _require_non_empty_text(value, field_name=field_name)
    if value != value.strip():
        message = f"{field_name} must not contain leading or trailing whitespace"
        raise ValueError(message)


def _encode_datetime(value: datetime, *, field_name: str) -> str:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)
    return value.astimezone(UTC).isoformat(timespec="microseconds")


def _decode_datetime(raw: str, *, field_name: str) -> datetime:
    try:
        value = datetime.fromisoformat(raw)
    except ValueError as error:
        message = f"invalid datetime in {field_name}: {raw!r}"
        raise CorruptStateError(message) from error
    if value.utcoffset() is None:
        message = f"naive datetime in {field_name}: {raw!r}"
        raise CorruptStateError(message)
    return value.astimezone(UTC)


def _validated_json(value: object, *, path: str = "$") -> JsonValue:
    if value is None:
        return None
    if type(value) in {bool, int, str}:
        return cast("bool | int | str", value)
    if type(value) is float:
        number = cast("float", value)
        if not math.isfinite(number):
            message = f"JSON number at {path} must be finite"
            raise ValueError(message)
        return number
    if type(value) is list:
        items = cast("list[object]", value)
        return [_validated_json(item, path=f"{path}[{index}]") for index, item in enumerate(items)]
    if type(value) is dict:
        mapping = cast("dict[object, object]", value)
        normalized: dict[str, JsonValue] = {}
        for key, item in mapping.items():
            if type(key) is not str:
                message = f"JSON object key at {path} must be a string"
                raise TypeError(message)
            text_key = key
            normalized[text_key] = _validated_json(item, path=f"{path}.{text_key}")
        return normalized
    message = f"unsupported JSON value at {path}: {type(value).__name__}"
    raise TypeError(message)


def _encode_json(payload: JsonValue) -> str:
    normalized = _validated_json(payload)
    return json.dumps(normalized, ensure_ascii=False, allow_nan=False, separators=(",", ":"), sort_keys=True)


def _decode_json(raw: str) -> JsonValue:
    try:
        value: object = json.loads(raw)
    except json.JSONDecodeError as error:
        message = "database contains invalid JSON"
        raise CorruptStateError(message) from error
    return _validated_json(value)


def _required_text(row: sqlite3.Row, column: str) -> str:
    value: object = row[column]
    if not isinstance(value, str):
        message = f"column {column} must contain text"
        raise CorruptStateError(message)
    return value


def _optional_text(row: sqlite3.Row, column: str) -> str | None:
    value: object = row[column]
    if value is None:
        return None
    if not isinstance(value, str):
        message = f"column {column} must contain text or NULL"
        raise CorruptStateError(message)
    return value


def _required_integer(row: sqlite3.Row, column: str) -> int:
    value: object = row[column]
    if type(value) is not int:
        message = f"column {column} must contain an integer"
        raise CorruptStateError(message)
    return value


class SQLiteStateStore:
    """一个实例对应一个 SQLite/WAL 状态库。"""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        if str(self._path) == ":memory:":
            message = "SQLiteStateStore requires a file path so WAL is durable"
            raise ValueError(message)
        self._connection = sqlite3.connect(self._path, isolation_level=None, timeout=5.0)
        self._connection.row_factory = sqlite3.Row
        self._closed = False
        try:
            self._configure_connection()
            self._initialize_schema()
        except BaseException:
            self._connection.close()
            self._closed = True
            raise

    @property
    def path(self) -> Path:
        return self._path

    @property
    def journal_mode(self) -> str:
        row = self._connection.execute("PRAGMA journal_mode").fetchone()
        if row is None:
            message = "PRAGMA journal_mode returned no row"
            raise CorruptStateError(message)
        return _required_text(row, "journal_mode").lower()

    @property
    def schema_version(self) -> int:
        row = self._connection.execute("PRAGMA user_version").fetchone()
        if row is None:
            message = "PRAGMA user_version returned no row"
            raise CorruptStateError(message)
        return _required_integer(row, "user_version")

    def table_names(self) -> frozenset[str]:
        rows = self._connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        ).fetchall()
        return frozenset(_required_text(row, "name") for row in rows)

    def close(self) -> None:
        if self._closed:
            return
        self._connection.close()
        self._closed = True

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def read_settings(self) -> SettingsSnapshot | None:
        row = self._connection.execute(
            "SELECT revision, payload, updated_at FROM settings WHERE singleton = 1"
        ).fetchone()
        return None if row is None else self._settings_from_row(row)

    def read_configuration_source(self) -> ConfigurationSourceSnapshot | None:
        """在同一 read transaction 中验证摘要仍指向当前 settings revision。"""
        with self._read_transaction():
            row = self._connection.execute(
                """
                SELECT source_revision, settings_revision, updated_at
                FROM configuration_source
                WHERE singleton = 1
                """
            ).fetchone()
            if row is None:
                return None
            settings_revision = _required_integer(row, "settings_revision")
            current_revision = self._read_settings_revision()
            if current_revision != settings_revision:
                message = (
                    "configuration source revision does not reference the current settings revision: "
                    f"source={settings_revision}, settings={current_revision}"
                )
                raise CorruptStateError(message)
            return self._configuration_source_from_row(row)

    def read_task_resolution_snapshot(self, task_id: str) -> TaskResolutionSnapshot:
        """在同一个 deferred read transaction 中读取 settings、schedule 与 task state。"""
        _require_non_empty_text(task_id, field_name="task_id")
        with self._read_transaction():
            settings_row = self._connection.execute(
                "SELECT revision, payload, updated_at FROM settings WHERE singleton = 1"
            ).fetchone()
            settings = None if settings_row is None else self._settings_from_row(settings_row)
            state_rows = self._connection.execute(
                """
                SELECT namespace, key, version, payload, updated_at
                FROM task_state
                WHERE namespace = ?
                ORDER BY key
                """,
                (task_id,),
            ).fetchall()
            schedule_rows = self._connection.execute(
                """
                SELECT task_id, enabled, due_at, priority, updated_at
                FROM schedule
                ORDER BY task_id
                """
            ).fetchall()
            return TaskResolutionSnapshot(
                task_id=task_id,
                settings=settings,
                state_records=tuple(self._task_state_from_row(row) for row in state_rows),
                schedule_records=tuple(self._schedule_from_row(row) for row in schedule_rows),
            )

    def update_settings(
        self,
        payload: JsonValue,
        *,
        expected_revision: int,
        updated_at: datetime,
    ) -> SettingsSnapshot:
        """expected_revision=0 创建首个 snapshot，其余值执行 CAS 更新。"""
        _require_non_negative_integer(expected_revision, field_name="expected_revision")
        encoded_payload = _encode_json(payload)
        encoded_updated_at = _encode_datetime(updated_at, field_name="updated_at")

        with self._transaction():
            snapshot = self._update_settings(
                encoded_payload=encoded_payload,
                encoded_updated_at=encoded_updated_at,
                expected_revision=expected_revision,
            )
            self._connection.execute("DELETE FROM configuration_source")
            return snapshot

    def publish_configuration(
        self,
        payload: JsonValue,
        schedules: tuple[ScheduleMutation, ...],
        *,
        source_revision: str,
        expected_revision: int,
        updated_at: datetime,
    ) -> SettingsSnapshot:
        """以一次 CAS 事务发布完整 settings 与完整 schedule snapshot。"""
        _require_non_negative_integer(expected_revision, field_name="expected_revision")
        _require_trimmed_non_empty_text(source_revision, field_name="source_revision")
        if not isinstance(schedules, tuple):
            message = "schedules must be a tuple"
            raise TypeError(message)
        if any(not isinstance(mutation, ScheduleMutation) for mutation in schedules):
            message = "schedules must contain only ScheduleMutation values"
            raise TypeError(message)
        task_ids = tuple(mutation.task_id for mutation in schedules)
        if len(task_ids) != len(set(task_ids)):
            message = "schedules must not contain duplicate task_id values"
            raise ValueError(message)

        encoded_payload = _encode_json(payload)
        encoded_updated_at = _encode_datetime(updated_at, field_name="updated_at")
        with self._transaction():
            snapshot = self._update_settings(
                encoded_payload=encoded_payload,
                encoded_updated_at=encoded_updated_at,
                expected_revision=expected_revision,
            )
            self._connection.execute("DELETE FROM schedule")
            for mutation in schedules:
                self._upsert_schedule(mutation, encoded_updated_at=encoded_updated_at)
            self._connection.execute(
                """
                INSERT INTO configuration_source(
                    singleton, source_revision, settings_revision, updated_at
                ) VALUES (1, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    source_revision = excluded.source_revision,
                    settings_revision = excluded.settings_revision,
                    updated_at = excluded.updated_at
                """,
                (source_revision, snapshot.revision, encoded_updated_at),
            )
            return snapshot

    def upsert_schedule(self, mutation: ScheduleMutation, *, updated_at: datetime) -> ScheduleRecord:
        if not isinstance(mutation, ScheduleMutation):
            message = "mutation must be a ScheduleMutation"
            raise TypeError(message)
        encoded_updated_at = _encode_datetime(updated_at, field_name="updated_at")
        with self._transaction():
            self._upsert_schedule(mutation, encoded_updated_at=encoded_updated_at)
        record = self.get_schedule(mutation.task_id)
        if record is None:
            message = "schedule upsert did not produce a row"
            raise CorruptStateError(message)
        return record

    def get_schedule(self, task_id: str) -> ScheduleRecord | None:
        _require_non_empty_text(task_id, field_name="task_id")
        row = self._connection.execute(
            "SELECT task_id, enabled, due_at, priority, updated_at FROM schedule WHERE task_id = ?",
            (task_id,),
        ).fetchone()
        return None if row is None else self._schedule_from_row(row)

    def list_schedules(self) -> tuple[ScheduleRecord, ...]:
        rows = self._connection.execute(
            "SELECT task_id, enabled, due_at, priority, updated_at FROM schedule ORDER BY task_id"
        ).fetchall()
        return tuple(self._schedule_from_row(row) for row in rows)

    def put_task_state(
        self,
        namespace: str,
        key: str,
        *,
        version: int,
        payload: JsonValue,
        updated_at: datetime,
    ) -> TaskStateRecord:
        mutation = UpsertTaskStateMutation(
            namespace=namespace,
            key=key,
            schema_version=version,
            payload=payload,
        )
        encoded_payload = _encode_json(mutation.payload)
        encoded_updated_at = _encode_datetime(updated_at, field_name="updated_at")
        with self._transaction():
            self._upsert_task_state(
                mutation,
                encoded_payload=encoded_payload,
                encoded_updated_at=encoded_updated_at,
            )
        record = self.get_task_state(namespace, key)
        if record is None:
            message = "task state upsert did not produce a row"
            raise CorruptStateError(message)
        return record

    def get_task_state(self, namespace: str, key: str) -> TaskStateRecord | None:
        _require_non_empty_text(namespace, field_name="namespace")
        _require_non_empty_text(key, field_name="key")
        row = self._connection.execute(
            """
            SELECT namespace, key, version, payload, updated_at
            FROM task_state
            WHERE namespace = ? AND key = ?
            """,
            (namespace, key),
        ).fetchone()
        return None if row is None else self._task_state_from_row(row)

    def start_run(  # noqa: PLR0913
        self,
        run_id: str,
        task_id: str,
        *,
        mode: RunMode,
        settings_revision: int,
        content_revision: str,
        client_ui_revision: str,
        started_at: datetime,
    ) -> RunRecord:
        _require_non_empty_text(run_id, field_name="run_id")
        _require_non_empty_text(task_id, field_name="task_id")
        if not isinstance(mode, RunMode):
            message = "mode must be a RunMode"
            raise TypeError(message)
        _require_positive_integer(settings_revision, field_name="settings_revision")
        _require_trimmed_non_empty_text(content_revision, field_name="content_revision")
        _require_trimmed_non_empty_text(client_ui_revision, field_name="client_ui_revision")
        encoded_started_at = _encode_datetime(started_at, field_name="started_at")
        try:
            with self._transaction():
                actual_revision = self._read_settings_revision()
                if actual_revision is not None and actual_revision != settings_revision:
                    raise RevisionConflictError(
                        expected_revision=settings_revision,
                        actual_revision=actual_revision,
                    )
                self._connection.execute(
                    """
                    INSERT INTO runs(
                        run_id,
                        task_id,
                        mode,
                        settings_revision,
                        content_revision,
                        client_ui_revision,
                        status,
                        started_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        task_id,
                        mode.value,
                        settings_revision,
                        content_revision,
                        client_ui_revision,
                        RunStatus.RUNNING.value,
                        encoded_started_at,
                    ),
                )
        except sqlite3.IntegrityError as error:
            message = f"run already exists: {run_id}"
            raise RunStateError(message) from error
        run = self.get_run(run_id)
        if run is None:
            message = "run insert did not produce a row"
            raise CorruptStateError(message)
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        _require_non_empty_text(run_id, field_name="run_id")
        row = self._connection.execute(
            """
            SELECT
                run_id,
                task_id,
                mode,
                settings_revision,
                content_revision,
                client_ui_revision,
                status,
                started_at,
                finished_at,
                result_payload,
                error
            FROM runs
            WHERE run_id = ?
            """,
            (run_id,),
        ).fetchone()
        return None if row is None else self._run_from_row(row)

    def list_runs(self, *, status: RunStatus | None = None) -> tuple[RunRecord, ...]:
        if status is not None and not isinstance(status, RunStatus):
            message = "status must be a RunStatus or None"
            raise TypeError(message)
        if status is None:
            rows = self._connection.execute(
                """
                SELECT
                    run_id, task_id, mode, settings_revision, content_revision,
                    client_ui_revision, status, started_at, finished_at, result_payload, error
                FROM runs
                ORDER BY started_at, run_id
                """
            ).fetchall()
        else:
            rows = self._connection.execute(
                """
                SELECT
                    run_id, task_id, mode, settings_revision, content_revision,
                    client_ui_revision, status, started_at, finished_at, result_payload, error
                FROM runs
                WHERE status = ?
                ORDER BY started_at, run_id
                """,
                (status.value,),
            ).fetchall()
        return tuple(self._run_from_row(row) for row in rows)

    def append_run_event(self, run_id: str, event: RunEvent) -> RunEventRecord:
        _require_non_empty_text(run_id, field_name="run_id")
        if not isinstance(event, RunEvent):
            message = "event must be a RunEvent"
            raise TypeError(message)
        encoded_payload = _encode_json(event.payload)
        encoded_occurred_at = _encode_datetime(event.occurred_at, field_name="occurred_at")
        with self._transaction():
            status = self._read_run_status(run_id)
            if status is None:
                message = f"unknown run: {run_id}"
                raise RunStateError(message)
            if status is not RunStatus.RUNNING:
                message = f"cannot append event to terminal run: {run_id}"
                raise RunStateError(message)
            sequence = self._next_event_sequence(run_id)
            self._insert_run_event(
                run_id,
                sequence=sequence,
                kind=event.kind,
                encoded_payload=encoded_payload,
                encoded_occurred_at=encoded_occurred_at,
            )
        return RunEventRecord(
            run_id=run_id,
            sequence=sequence,
            kind=event.kind,
            payload=_decode_json(encoded_payload),
            occurred_at=_decode_datetime(encoded_occurred_at, field_name="occurred_at"),
        )

    def list_run_events(self, run_id: str) -> tuple[RunEventRecord, ...]:
        _require_non_empty_text(run_id, field_name="run_id")
        rows = self._connection.execute(
            """
            SELECT run_id, sequence, kind, payload, occurred_at
            FROM run_events
            WHERE run_id = ?
            ORDER BY sequence
            """,
            (run_id,),
        ).fetchall()
        return tuple(self._run_event_from_row(row) for row in rows)

    def finalize_run(
        self,
        run_id: str,
        finalization: RunFinalization,
    ) -> RunRecord:
        """在单一事务中提交 run 终态及其全部派生事实。"""
        _require_non_empty_text(run_id, field_name="run_id")
        if not isinstance(finalization, RunFinalization):
            message = "finalization must be a RunFinalization"
            raise TypeError(message)
        encoded_finished_at = _encode_datetime(finalization.finished_at, field_name="finished_at")
        encoded_result_payload = _encode_json(finalization.result_payload)
        encoded_events = tuple(
            (
                event,
                _encode_json(event.payload),
                _encode_datetime(event.occurred_at, field_name="occurred_at"),
            )
            for event in finalization.events
        )
        encoded_messages = tuple((message, _encode_json(message.payload)) for message in finalization.outbox_messages)
        encoded_task_state_mutations: tuple[_EncodedTaskStateMutation, ...] = tuple(
            (
                mutation,
                _encode_json(mutation.payload) if isinstance(mutation, UpsertTaskStateMutation) else None,
            )
            for mutation in finalization.task_state_mutations
        )

        with self._transaction():
            running_row = self._connection.execute(
                "SELECT settings_revision FROM runs WHERE run_id = ? AND status = ?",
                (run_id, RunStatus.RUNNING.value),
            ).fetchone()
            run_settings_revision = None if running_row is None else _required_integer(running_row, "settings_revision")
            current_settings_revision = self._read_settings_revision()
            apply_mutations = run_settings_revision is not None and (
                current_settings_revision is None or current_settings_revision == run_settings_revision
            )
            cursor = self._connection.execute(
                """
                UPDATE runs
                SET status = ?, finished_at = ?, result_payload = ?, error = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    finalization.status.value,
                    encoded_finished_at,
                    encoded_result_payload,
                    finalization.error,
                    run_id,
                    RunStatus.RUNNING.value,
                ),
            )
            if cursor.rowcount != 1:
                current_status = self._read_run_status(run_id)
                if current_status is None:
                    message = f"unknown run: {run_id}"
                else:
                    message = f"cannot finalize run in {current_status.value} state: {run_id}"
                raise RunStateError(message)

            sequence = self._next_event_sequence(run_id)
            for event, encoded_payload, encoded_occurred_at in encoded_events:
                self._insert_run_event(
                    run_id,
                    sequence=sequence,
                    kind=event.kind,
                    encoded_payload=encoded_payload,
                    encoded_occurred_at=encoded_occurred_at,
                )
                sequence += 1

            has_mutations = bool(finalization.schedule_mutations or finalization.task_state_mutations)
            if apply_mutations:
                for mutation in finalization.schedule_mutations:
                    self._upsert_schedule(mutation, encoded_updated_at=encoded_finished_at)

                self._apply_task_state_mutations(
                    encoded_task_state_mutations,
                    encoded_updated_at=encoded_finished_at,
                )
            elif has_mutations and run_settings_revision is not None:
                skipped_payload = _encode_json(
                    {
                        "run_settings_revision": run_settings_revision,
                        "current_settings_revision": current_settings_revision,
                    }
                )
                self._insert_run_event(
                    run_id,
                    sequence=sequence,
                    kind=_RUN_MUTATIONS_SKIPPED_EVENT,
                    encoded_payload=skipped_payload,
                    encoded_occurred_at=encoded_finished_at,
                )
                sequence += 1

            for outbox_message, encoded_payload in encoded_messages:
                self._connection.execute(
                    """
                    INSERT INTO outbox(message_id, run_id, topic, message_key, payload, created_at)
                    VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        outbox_message.message_id,
                        run_id,
                        outbox_message.topic,
                        outbox_message.key,
                        encoded_payload,
                        encoded_finished_at,
                    ),
                )

            row = self._connection.execute(
                """
                SELECT
                    run_id,
                    task_id,
                    mode,
                    settings_revision,
                    content_revision,
                    client_ui_revision,
                    status,
                    started_at,
                    finished_at,
                    result_payload,
                    error
                FROM runs
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                message = "run finalization removed the run"
                raise CorruptStateError(message)
            return self._run_from_row(row)

    def list_outbox(self, *, pending_only: bool = False) -> tuple[OutboxRecord, ...]:
        if type(pending_only) is not bool:
            message = "pending_only must be a bool"
            raise TypeError(message)
        if pending_only:
            query = """
                SELECT message_id, run_id, topic, message_key, payload, created_at, published_at
                FROM outbox
                WHERE published_at IS NULL
                ORDER BY created_at, message_id
            """
        else:
            query = """
                SELECT message_id, run_id, topic, message_key, payload, created_at, published_at
                FROM outbox
                ORDER BY created_at, message_id
            """
        rows = self._connection.execute(query).fetchall()
        return tuple(self._outbox_from_row(row) for row in rows)

    def mark_outbox_published(self, message_id: str, published_at: datetime) -> OutboxRecord:
        _require_non_empty_text(message_id, field_name="message_id")
        encoded_published_at = _encode_datetime(published_at, field_name="published_at")

        with self._transaction():
            cursor = self._connection.execute(
                """
                UPDATE outbox
                SET published_at = ?
                WHERE message_id = ? AND published_at IS NULL
                """,
                (encoded_published_at, message_id),
            )
            if cursor.rowcount != 1:
                row = self._connection.execute(
                    "SELECT published_at FROM outbox WHERE message_id = ?",
                    (message_id,),
                ).fetchone()
                if row is None:
                    message = f"unknown outbox message: {message_id}"
                    raise OutboxStateError(message)
                message = f"outbox message already published: {message_id}"
                raise OutboxStateError(message)

            row = self._connection.execute(
                """
                SELECT message_id, run_id, topic, message_key, payload, created_at, published_at
                FROM outbox
                WHERE message_id = ?
                """,
                (message_id,),
            ).fetchone()
            if row is None:
                message = f"published outbox message disappeared: {message_id}"
                raise CorruptStateError(message)
            return self._outbox_from_row(row)

    def _configure_connection(self) -> None:
        self._connection.execute("PRAGMA foreign_keys = ON")
        self._connection.execute("PRAGMA busy_timeout = 5000")
        row = self._connection.execute("PRAGMA journal_mode = WAL").fetchone()
        if row is None or _required_text(row, "journal_mode").lower() != "wal":
            message = "SQLite did not enable WAL journal mode"
            raise CorruptStateError(message)
        self._connection.execute("PRAGMA synchronous = NORMAL")

    def _initialize_schema(self) -> None:
        version = self.schema_version
        tables = self.table_names()
        if version == 0:
            if tables:
                message = f"unversioned database already contains tables: {sorted(tables)}"
                raise SchemaVersionError(message)
            with self._transaction():
                for statement in _SCHEMA_STATEMENTS:
                    self._connection.execute(statement)
                self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        elif version != SCHEMA_VERSION:
            message = f"unsupported schema version: {version}; expected {SCHEMA_VERSION}"
            raise SchemaVersionError(message)
        self._validate_schema()

    def _validate_schema(self) -> None:
        actual_tables = self.table_names()
        expected_tables = frozenset(_EXPECTED_COLUMNS)
        if actual_tables != expected_tables:
            message = f"schema tables mismatch: expected {sorted(expected_tables)}, actual {sorted(actual_tables)}"
            raise SchemaVersionError(message)
        for table, expected_columns in _EXPECTED_COLUMNS.items():
            rows = self._connection.execute(_TABLE_INFO_QUERIES[table]).fetchall()
            actual_columns = tuple(_required_text(row, "name") for row in rows)
            if actual_columns != expected_columns:
                message = f"schema columns mismatch for {table}: expected {expected_columns}, actual {actual_columns}"
                raise SchemaVersionError(message)

    @contextmanager
    def _read_transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN")
        try:
            yield
            self._connection.commit()
        except BaseException:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self._connection.execute("BEGIN IMMEDIATE")
        try:
            yield
            self._connection.commit()
        except BaseException:
            if self._connection.in_transaction:
                self._connection.rollback()
            raise

    def _read_settings_revision(self) -> int | None:
        row = self._connection.execute("SELECT revision FROM settings WHERE singleton = 1").fetchone()
        return None if row is None else _required_integer(row, "revision")

    def _read_run_status(self, run_id: str) -> RunStatus | None:
        row = self._connection.execute("SELECT status FROM runs WHERE run_id = ?", (run_id,)).fetchone()
        if row is None:
            return None
        raw_status = _required_text(row, "status")
        try:
            return RunStatus(raw_status)
        except ValueError as error:
            message = f"unknown run status in database: {raw_status!r}"
            raise CorruptStateError(message) from error

    def _next_event_sequence(self, run_id: str) -> int:
        row = self._connection.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence FROM run_events WHERE run_id = ?",
            (run_id,),
        ).fetchone()
        if row is None:
            message = "event sequence query returned no row"
            raise CorruptStateError(message)
        return _required_integer(row, "next_sequence")

    def _insert_run_event(
        self,
        run_id: str,
        *,
        sequence: int,
        kind: str,
        encoded_payload: str,
        encoded_occurred_at: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO run_events(run_id, sequence, kind, payload, occurred_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (run_id, sequence, kind, encoded_payload, encoded_occurred_at),
        )

    def _upsert_schedule(self, mutation: ScheduleMutation, *, encoded_updated_at: str) -> None:
        encoded_due_at = None if mutation.due_at is None else _encode_datetime(mutation.due_at, field_name="due_at")
        self._connection.execute(
            """
            INSERT INTO schedule(task_id, enabled, due_at, priority, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                enabled = excluded.enabled,
                due_at = excluded.due_at,
                priority = excluded.priority,
                updated_at = excluded.updated_at
            """,
            (
                mutation.task_id,
                1 if mutation.enabled else 0,
                encoded_due_at,
                mutation.priority,
                encoded_updated_at,
            ),
        )

    def _upsert_task_state(
        self,
        mutation: UpsertTaskStateMutation,
        *,
        encoded_payload: str,
        encoded_updated_at: str,
    ) -> None:
        self._connection.execute(
            """
            INSERT INTO task_state(namespace, key, version, payload, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(namespace, key) DO UPDATE SET
                version = excluded.version,
                payload = excluded.payload,
                updated_at = excluded.updated_at
            """,
            (
                mutation.namespace,
                mutation.key,
                mutation.schema_version,
                encoded_payload,
                encoded_updated_at,
            ),
        )

    def _delete_task_state(self, mutation: DeleteTaskStateMutation) -> None:
        self._connection.execute(
            "DELETE FROM task_state WHERE namespace = ? AND key = ?",
            (mutation.namespace, mutation.key),
        )

    def _apply_task_state_mutations(
        self,
        mutations: tuple[_EncodedTaskStateMutation, ...],
        *,
        encoded_updated_at: str,
    ) -> None:
        for mutation, encoded_payload in mutations:
            if isinstance(mutation, UpsertTaskStateMutation):
                if encoded_payload is None:
                    message = "task state upsert is missing encoded payload"
                    raise CorruptStateError(message)
                self._upsert_task_state(
                    mutation,
                    encoded_payload=encoded_payload,
                    encoded_updated_at=encoded_updated_at,
                )
            elif isinstance(mutation, DeleteTaskStateMutation):
                self._delete_task_state(mutation)

    def _update_settings(
        self,
        *,
        encoded_payload: str,
        encoded_updated_at: str,
        expected_revision: int,
    ) -> SettingsSnapshot:
        if expected_revision == 0:
            try:
                self._connection.execute(
                    "INSERT INTO settings(singleton, revision, payload, updated_at) VALUES (1, 1, ?, ?)",
                    (encoded_payload, encoded_updated_at),
                )
            except sqlite3.IntegrityError as error:
                actual_revision = self._read_settings_revision()
                if actual_revision is None:
                    raise
                raise RevisionConflictError(
                    expected_revision=expected_revision,
                    actual_revision=actual_revision,
                ) from error
        else:
            cursor = self._connection.execute(
                """
                UPDATE settings
                SET revision = revision + 1, payload = ?, updated_at = ?
                WHERE singleton = 1 AND revision = ?
                """,
                (encoded_payload, encoded_updated_at, expected_revision),
            )
            if cursor.rowcount != 1:
                raise RevisionConflictError(
                    expected_revision=expected_revision,
                    actual_revision=self._read_settings_revision(),
                )

        row = self._connection.execute(
            "SELECT revision, payload, updated_at FROM settings WHERE singleton = 1"
        ).fetchone()
        if row is None:
            message = "settings write did not produce a row"
            raise CorruptStateError(message)
        return self._settings_from_row(row)

    @staticmethod
    def _settings_from_row(row: sqlite3.Row) -> SettingsSnapshot:
        return SettingsSnapshot(
            revision=_required_integer(row, "revision"),
            payload=_decode_json(_required_text(row, "payload")),
            updated_at=_decode_datetime(_required_text(row, "updated_at"), field_name="settings.updated_at"),
        )

    @staticmethod
    def _configuration_source_from_row(row: sqlite3.Row) -> ConfigurationSourceSnapshot:
        return ConfigurationSourceSnapshot(
            source_revision=_required_text(row, "source_revision"),
            settings_revision=_required_integer(row, "settings_revision"),
            updated_at=_decode_datetime(
                _required_text(row, "updated_at"),
                field_name="configuration_source.updated_at",
            ),
        )

    @staticmethod
    def _schedule_from_row(row: sqlite3.Row) -> ScheduleRecord:
        raw_enabled = _required_integer(row, "enabled")
        if raw_enabled not in {0, 1}:
            message = f"invalid schedule enabled value: {raw_enabled}"
            raise CorruptStateError(message)
        raw_due_at = _optional_text(row, "due_at")
        return ScheduleRecord(
            task_id=_required_text(row, "task_id"),
            enabled=bool(raw_enabled),
            due_at=None if raw_due_at is None else _decode_datetime(raw_due_at, field_name="schedule.due_at"),
            priority=_required_integer(row, "priority"),
            updated_at=_decode_datetime(_required_text(row, "updated_at"), field_name="schedule.updated_at"),
        )

    @staticmethod
    def _task_state_from_row(row: sqlite3.Row) -> TaskStateRecord:
        return TaskStateRecord(
            namespace=_required_text(row, "namespace"),
            key=_required_text(row, "key"),
            version=_required_integer(row, "version"),
            payload=_decode_json(_required_text(row, "payload")),
            updated_at=_decode_datetime(_required_text(row, "updated_at"), field_name="task_state.updated_at"),
        )

    @staticmethod
    def _run_from_row(row: sqlite3.Row) -> RunRecord:
        raw_status = _required_text(row, "status")
        try:
            status = RunStatus(raw_status)
        except ValueError as error:
            message = f"unknown run status in database: {raw_status!r}"
            raise CorruptStateError(message) from error
        raw_mode = _required_text(row, "mode")
        try:
            mode = RunMode(raw_mode)
        except ValueError as error:
            message = f"unknown run mode in database: {raw_mode!r}"
            raise CorruptStateError(message) from error
        raw_finished_at = _optional_text(row, "finished_at")
        raw_result_payload = _optional_text(row, "result_payload")
        return RunRecord(
            run_id=_required_text(row, "run_id"),
            task_id=_required_text(row, "task_id"),
            mode=mode,
            settings_revision=_required_integer(row, "settings_revision"),
            content_revision=_required_text(row, "content_revision"),
            client_ui_revision=_required_text(row, "client_ui_revision"),
            status=status,
            started_at=_decode_datetime(_required_text(row, "started_at"), field_name="runs.started_at"),
            finished_at=(
                None if raw_finished_at is None else _decode_datetime(raw_finished_at, field_name="runs.finished_at")
            ),
            result_payload=None if raw_result_payload is None else _decode_json(raw_result_payload),
            error=_optional_text(row, "error"),
        )

    @staticmethod
    def _run_event_from_row(row: sqlite3.Row) -> RunEventRecord:
        return RunEventRecord(
            run_id=_required_text(row, "run_id"),
            sequence=_required_integer(row, "sequence"),
            kind=_required_text(row, "kind"),
            payload=_decode_json(_required_text(row, "payload")),
            occurred_at=_decode_datetime(_required_text(row, "occurred_at"), field_name="run_events.occurred_at"),
        )

    @staticmethod
    def _outbox_from_row(row: sqlite3.Row) -> OutboxRecord:
        raw_published_at = _optional_text(row, "published_at")
        return OutboxRecord(
            message_id=_required_text(row, "message_id"),
            run_id=_required_text(row, "run_id"),
            topic=_required_text(row, "topic"),
            payload=_decode_json(_required_text(row, "payload")),
            key=_optional_text(row, "message_key"),
            created_at=_decode_datetime(_required_text(row, "created_at"), field_name="outbox.created_at"),
            published_at=(
                None
                if raw_published_at is None
                else _decode_datetime(raw_published_at, field_name="outbox.published_at")
            ),
        )
