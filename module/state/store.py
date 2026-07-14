import json
import math
import sqlite3
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Never, cast

if TYPE_CHECKING:
    from collections.abc import Iterator
    from types import TracebackType
    from typing import Self

from module.sqlite_wal import configure_sqlite_wal
from module.state.errors import (
    CorruptStateError,
    OutboxStateError,
    RevisionConflictError,
    RunStateError,
    SchemaVersionError,
)
from module.state.models import (
    ConfigurationPublication,
    ConfigurationSourceSnapshot,
    ConfigurationUpdate,
    DeleteTaskStateMutation,
    JsonValue,
    OutboxClaimRequest,
    OutboxFailureUpdate,
    OutboxManualRetry,
    OutboxRecord,
    RunEvent,
    RunEventRecord,
    RunFinalization,
    RunMode,
    RunRecord,
    RunStartCommand,
    RunStatus,
    ScheduleMutation,
    ScheduleRecord,
    SettingsSnapshot,
    TaskResolutionSnapshot,
    TaskStateMutation,
    TaskStateRecord,
    UpsertTaskStateMutation,
)

SCHEMA_VERSION = 4
_RUN_MUTATIONS_SKIPPED_EVENT = "run.mutations.skipped"

type _EncodedTaskStateMutation = tuple[TaskStateMutation, str | None]

_OUTBOX_SCHEMA_STATEMENT = """
    CREATE TABLE outbox (
        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id TEXT NOT NULL UNIQUE,
        run_id TEXT NOT NULL REFERENCES runs(run_id) ON DELETE CASCADE,
        topic TEXT NOT NULL,
        message_key TEXT,
        payload TEXT NOT NULL CHECK (json_valid(payload)),
        created_at TEXT NOT NULL,
        available_at TEXT NOT NULL,
        attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
        last_attempt_at TEXT,
        last_error_type TEXT CHECK (
            last_error_type IS NULL OR (length(last_error_type) > 0 AND last_error_type = trim(last_error_type))
        ),
        claim_token TEXT,
        claim_until TEXT,
        published_at TEXT,
        discarded_at TEXT,
        CHECK (published_at IS NULL OR discarded_at IS NULL),
        CHECK ((claim_token IS NULL) = (claim_until IS NULL)),
        CHECK ((published_at IS NULL AND discarded_at IS NULL) OR claim_token IS NULL),
        CHECK (
            (attempt_count = 0 AND last_attempt_at IS NULL AND last_error_type IS NULL)
            OR (attempt_count > 0 AND last_attempt_at IS NOT NULL)
        ),
        CHECK (discarded_at IS NULL OR last_error_type IS NOT NULL)
    ) STRICT
"""
_OUTBOX_READY_INDEX_STATEMENT = """
    CREATE INDEX outbox_ready
    ON outbox(available_at, claim_until, sequence)
    WHERE published_at IS NULL AND discarded_at IS NULL
"""

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
        source_schedules TEXT NOT NULL CHECK (json_valid(source_schedules)),
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
    _OUTBOX_SCHEMA_STATEMENT,
    _OUTBOX_READY_INDEX_STATEMENT,
)

_EXPECTED_COLUMNS = {
    "settings": ("singleton", "revision", "payload", "updated_at"),
    "configuration_source": (
        "singleton",
        "source_revision",
        "settings_revision",
        "source_schedules",
        "updated_at",
    ),
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
    "outbox": (
        "sequence",
        "message_id",
        "run_id",
        "topic",
        "message_key",
        "payload",
        "created_at",
        "available_at",
        "attempt_count",
        "last_attempt_at",
        "last_error_type",
        "claim_token",
        "claim_until",
        "published_at",
        "discarded_at",
    ),
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
_V3_OUTBOX_COLUMNS = ("message_id", "run_id", "topic", "message_key", "payload", "created_at", "published_at")


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


def _encode_source_schedules(schedules: tuple[ScheduleMutation, ...]) -> str:
    if not isinstance(schedules, tuple) or any(not isinstance(item, ScheduleMutation) for item in schedules):
        message = "source schedules must be a tuple of ScheduleMutation values"
        raise TypeError(message)
    payload: JsonValue = [
        {
            "task_id": item.task_id,
            "enabled": item.enabled,
            "due_at": None
            if item.due_at is None
            else _encode_datetime(item.due_at, field_name=f"source_schedules.{item.task_id}.due_at"),
            "priority": item.priority,
        }
        for item in sorted(schedules, key=lambda value: value.task_id)
    ]
    return _encode_json(payload)


def _decode_source_schedules(raw: str) -> tuple[ScheduleMutation, ...]:
    payload = _decode_json(raw)
    if not isinstance(payload, list):
        message = "configuration source schedules must contain a JSON array"
        raise CorruptStateError(message)

    schedules: list[ScheduleMutation] = []
    expected = {"task_id", "enabled", "due_at", "priority"}
    for index, item in enumerate(payload):
        if not isinstance(item, dict) or set(item) != expected:
            message = f"invalid configuration source schedule at index {index}"
            raise CorruptStateError(message)
        task_id = item["task_id"]
        enabled = item["enabled"]
        raw_due_at = item["due_at"]
        priority = item["priority"]
        if not isinstance(task_id, str) or type(enabled) is not bool or type(priority) is not int:
            message = f"invalid configuration source schedule fields at index {index}"
            raise CorruptStateError(message)
        if raw_due_at is not None and not isinstance(raw_due_at, str):
            message = f"invalid configuration source schedule due_at at index {index}"
            raise CorruptStateError(message)
        try:
            schedules.append(
                ScheduleMutation(
                    task_id=task_id,
                    enabled=enabled,
                    due_at=None
                    if raw_due_at is None
                    else _decode_datetime(
                        raw_due_at,
                        field_name=f"configuration_source.source_schedules[{index}].due_at",
                    ),
                    priority=priority,
                )
            )
        except (TypeError, ValueError) as error:
            message = f"invalid configuration source schedule at index {index}: {error}"
            raise CorruptStateError(message) from error

    task_ids = tuple(item.task_id for item in schedules)
    if len(task_ids) != len(set(task_ids)):
        message = "configuration source schedules contain duplicate task ids"
        raise CorruptStateError(message)
    return tuple(schedules)


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
                SELECT source_revision, settings_revision, source_schedules, updated_at
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
        command: ConfigurationPublication,
    ) -> SettingsSnapshot:
        """以一次 CAS 事务发布完整 settings 与完整 schedule snapshot。"""
        if not isinstance(command, ConfigurationPublication):
            message = "command must be a ConfigurationPublication"
            raise TypeError(message)
        encoded_payload = _encode_json(command.payload)
        encoded_updated_at = _encode_datetime(command.updated_at, field_name="updated_at")
        encoded_source_schedules = _encode_source_schedules(command.schedules)
        with self._transaction():
            snapshot = self._update_settings(
                encoded_payload=encoded_payload,
                encoded_updated_at=encoded_updated_at,
                expected_revision=command.expected_revision,
            )
            self._connection.execute("DELETE FROM schedule")
            for mutation in command.schedules:
                self._upsert_schedule(mutation, encoded_updated_at=encoded_updated_at)
            self._connection.execute(
                """
                INSERT INTO configuration_source(
                    singleton, source_revision, settings_revision, source_schedules, updated_at
                ) VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    source_revision = excluded.source_revision,
                    settings_revision = excluded.settings_revision,
                    source_schedules = excluded.source_schedules,
                    updated_at = excluded.updated_at
                """,
                (command.source_revision, snapshot.revision, encoded_source_schedules, encoded_updated_at),
            )
            return snapshot

    def publish_configuration_update(self, command: ConfigurationUpdate) -> SettingsSnapshot:
        """发布新 source snapshot，仅把 source 中实际变化的调度字段合并到运行态。"""
        if not isinstance(command, ConfigurationUpdate):
            message = "command must be a ConfigurationUpdate"
            raise TypeError(message)
        publication = command.publication
        encoded_payload = _encode_json(publication.payload)
        encoded_updated_at = _encode_datetime(publication.updated_at, field_name="updated_at")
        encoded_source_schedules = _encode_source_schedules(publication.schedules)
        current_source = {item.task_id: item for item in publication.schedules}

        with self._transaction():
            current_settings_revision = self._read_settings_revision()
            if current_settings_revision != publication.expected_revision:
                raise RevisionConflictError(
                    expected_revision=publication.expected_revision,
                    actual_revision=current_settings_revision,
                )
            source_row = self._connection.execute(
                """
                SELECT source_revision, settings_revision, source_schedules, updated_at
                FROM configuration_source
                WHERE singleton = 1
                """
            ).fetchone()
            if source_row is None:
                message = "configuration update requires a persisted source baseline"
                raise CorruptStateError(message)
            persisted_source = self._configuration_source_from_row(source_row)
            if persisted_source.settings_revision != current_settings_revision:
                message = (
                    "configuration source revision does not reference the current settings revision: "
                    f"source={persisted_source.settings_revision}, settings={current_settings_revision}"
                )
                raise CorruptStateError(message)
            previous_source = {item.task_id: item for item in persisted_source.source_schedules}
            snapshot = self._update_settings(
                encoded_payload=encoded_payload,
                encoded_updated_at=encoded_updated_at,
                expected_revision=publication.expected_revision,
            )
            for removed_task_id in previous_source.keys() - current_source.keys():
                self._connection.execute("DELETE FROM schedule WHERE task_id = ?", (removed_task_id,))
            for task_id, source_schedule in current_source.items():
                previous = previous_source.get(task_id)
                row = self._connection.execute(
                    "SELECT task_id, enabled, due_at, priority, updated_at FROM schedule WHERE task_id = ?",
                    (task_id,),
                ).fetchone()
                if previous is None or row is None:
                    self._upsert_schedule(source_schedule, encoded_updated_at=encoded_updated_at)
                    continue

                runtime_schedule = self._schedule_from_row(row)
                merged = ScheduleMutation(
                    task_id=task_id,
                    enabled=(
                        source_schedule.enabled
                        if source_schedule.enabled != previous.enabled
                        else runtime_schedule.enabled
                    ),
                    due_at=(
                        source_schedule.due_at if source_schedule.due_at != previous.due_at else runtime_schedule.due_at
                    ),
                    priority=source_schedule.priority,
                )
                if (
                    merged.enabled != runtime_schedule.enabled
                    or merged.due_at != runtime_schedule.due_at
                    or merged.priority != runtime_schedule.priority
                ):
                    self._upsert_schedule(merged, encoded_updated_at=encoded_updated_at)

            self._connection.execute(
                """
                INSERT INTO configuration_source(
                    singleton, source_revision, settings_revision, source_schedules, updated_at
                ) VALUES (1, ?, ?, ?, ?)
                ON CONFLICT(singleton) DO UPDATE SET
                    source_revision = excluded.source_revision,
                    settings_revision = excluded.settings_revision,
                    source_schedules = excluded.source_schedules,
                    updated_at = excluded.updated_at
                """,
                (publication.source_revision, snapshot.revision, encoded_source_schedules, encoded_updated_at),
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

    def start_run(self, command: RunStartCommand) -> RunRecord:
        if not isinstance(command, RunStartCommand):
            message = "command must be a RunStartCommand"
            raise TypeError(message)
        encoded_started_at = _encode_datetime(command.started_at, field_name="started_at")
        try:
            with self._transaction():
                actual_revision = self._read_settings_revision()
                if actual_revision is not None and actual_revision != command.settings_revision:
                    raise RevisionConflictError(
                        expected_revision=command.settings_revision,
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
                        command.run_id,
                        command.task_id,
                        command.mode.value,
                        command.settings_revision,
                        command.content_revision,
                        command.client_ui_revision,
                        RunStatus.RUNNING.value,
                        encoded_started_at,
                    ),
                )
        except sqlite3.IntegrityError as error:
            message = f"run already exists: {command.run_id}"
            raise RunStateError(message) from error
        run = self.get_run(command.run_id)
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
                    INSERT INTO outbox(
                        message_id, run_id, topic, message_key, payload, created_at, available_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        outbox_message.message_id,
                        run_id,
                        outbox_message.topic,
                        outbox_message.key,
                        encoded_payload,
                        encoded_finished_at,
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
                SELECT
                    sequence,
                    message_id,
                    run_id,
                    topic,
                    message_key,
                    payload,
                    created_at,
                    available_at,
                    attempt_count,
                    last_attempt_at,
                    last_error_type,
                    claim_token,
                    claim_until,
                    published_at,
                    discarded_at
                FROM outbox
                WHERE published_at IS NULL AND discarded_at IS NULL
                ORDER BY sequence
            """
        else:
            query = """
                SELECT
                    sequence,
                    message_id,
                    run_id,
                    topic,
                    message_key,
                    payload,
                    created_at,
                    available_at,
                    attempt_count,
                    last_attempt_at,
                    last_error_type,
                    claim_token,
                    claim_until,
                    published_at,
                    discarded_at
                FROM outbox
                ORDER BY sequence
            """
        rows = self._connection.execute(query).fetchall()
        return tuple(self._outbox_from_row(row) for row in rows)

    def claim_ready_outbox(self, request: OutboxClaimRequest) -> tuple[OutboxRecord, ...]:
        if not isinstance(request, OutboxClaimRequest):
            message = "request must be an OutboxClaimRequest"
            raise TypeError(message)
        encoded_claimed_at = _encode_datetime(request.claimed_at, field_name="claimed_at")
        encoded_claim_until = _encode_datetime(request.claim_until, field_name="claim_until")

        with self._transaction():
            token_row = self._connection.execute(
                "SELECT 1 FROM outbox WHERE claim_token = ? LIMIT 1",
                (request.claim_token,),
            ).fetchone()
            if token_row is not None:
                message = f"outbox claim token is already active: {request.claim_token}"
                raise OutboxStateError(message)

            cursor = self._connection.execute(
                """
                UPDATE outbox
                SET claim_token = ?, claim_until = ?
                WHERE sequence IN (
                    SELECT sequence
                    FROM outbox
                    WHERE
                        published_at IS NULL
                        AND discarded_at IS NULL
                        AND available_at <= ?
                        AND (claim_until IS NULL OR claim_until <= ?)
                    ORDER BY sequence
                    LIMIT ?
                )
                """,
                (
                    request.claim_token,
                    encoded_claim_until,
                    encoded_claimed_at,
                    encoded_claimed_at,
                    request.limit,
                ),
            )
            if cursor.rowcount == 0:
                return ()

            if cursor.rowcount > request.limit:
                message = "outbox claim did not update the selected batch"
                raise CorruptStateError(message)

            claimed_rows = self._connection.execute(
                """
                SELECT
                    sequence,
                    message_id,
                    run_id,
                    topic,
                    message_key,
                    payload,
                    created_at,
                    available_at,
                    attempt_count,
                    last_attempt_at,
                    last_error_type,
                    claim_token,
                    claim_until,
                    published_at,
                    discarded_at
                FROM outbox
                WHERE claim_token = ?
                ORDER BY sequence
                """,
                (request.claim_token,),
            ).fetchall()
            if len(claimed_rows) != cursor.rowcount:
                message = "outbox claim could not reload the selected batch"
                raise CorruptStateError(message)
            return tuple(self._outbox_from_row(row) for row in claimed_rows)

    def mark_outbox_published(
        self,
        message_id: str,
        published_at: datetime,
        *,
        claim_token: str,
        expected_attempt_count: int,
    ) -> OutboxRecord:
        _require_non_empty_text(message_id, field_name="message_id")
        _require_non_empty_text(claim_token, field_name="claim_token")
        _require_non_negative_integer(expected_attempt_count, field_name="expected_attempt_count")
        encoded_published_at = _encode_datetime(published_at, field_name="published_at")

        with self._transaction():
            cursor = self._connection.execute(
                """
                UPDATE outbox
                SET
                    attempt_count = attempt_count + 1,
                    last_attempt_at = ?,
                    claim_token = NULL,
                    claim_until = NULL,
                    published_at = ?
                WHERE
                    message_id = ?
                    AND claim_token = ?
                    AND attempt_count = ?
                    AND published_at IS NULL
                    AND discarded_at IS NULL
                """,
                (
                    encoded_published_at,
                    encoded_published_at,
                    message_id,
                    claim_token,
                    expected_attempt_count,
                ),
            )
            if cursor.rowcount != 1:
                self._raise_outbox_transition_error(
                    message_id,
                    claim_token=claim_token,
                    expected_attempt_count=expected_attempt_count,
                )

            record = self._read_outbox(message_id)
            if record is None:
                message = f"published outbox message disappeared: {message_id}"
                raise CorruptStateError(message)
            return record

    def record_outbox_failure(self, update: OutboxFailureUpdate) -> OutboxRecord:
        if not isinstance(update, OutboxFailureUpdate):
            message = "update must be an OutboxFailureUpdate"
            raise TypeError(message)
        encoded_failed_at = _encode_datetime(update.failed_at, field_name="failed_at")
        encoded_available_at = (
            encoded_failed_at
            if update.available_at is None
            else _encode_datetime(update.available_at, field_name="available_at")
        )
        encoded_discarded_at = encoded_failed_at if update.available_at is None else None

        with self._transaction():
            cursor = self._connection.execute(
                """
                UPDATE outbox
                SET
                    attempt_count = attempt_count + 1,
                    available_at = ?,
                    last_attempt_at = ?,
                    last_error_type = ?,
                    claim_token = NULL,
                    claim_until = NULL,
                    discarded_at = ?
                WHERE
                    message_id = ?
                    AND claim_token = ?
                    AND attempt_count = ?
                    AND published_at IS NULL
                    AND discarded_at IS NULL
                """,
                (
                    encoded_available_at,
                    encoded_failed_at,
                    update.error_type,
                    encoded_discarded_at,
                    update.message_id,
                    update.claim_token,
                    update.expected_attempt_count,
                ),
            )
            if cursor.rowcount != 1:
                self._raise_outbox_transition_error(
                    update.message_id,
                    claim_token=update.claim_token,
                    expected_attempt_count=update.expected_attempt_count,
                )

            record = self._read_outbox(update.message_id)
            if record is None:
                message = f"failed outbox message disappeared: {update.message_id}"
                raise CorruptStateError(message)
            return record

    def retry_discarded_outbox(self, request: OutboxManualRetry) -> OutboxRecord:
        """重新开放 dead-letter；保留既有 attempt_count 与 last_error_type。"""
        if not isinstance(request, OutboxManualRetry):
            message = "request must be an OutboxManualRetry"
            raise TypeError(message)
        encoded_available_at = _encode_datetime(request.available_at, field_name="available_at")

        with self._transaction():
            cursor = self._connection.execute(
                """
                UPDATE outbox
                SET
                    available_at = ?,
                    claim_token = NULL,
                    claim_until = NULL,
                    discarded_at = NULL
                WHERE message_id = ? AND published_at IS NULL AND discarded_at IS NOT NULL
                """,
                (encoded_available_at, request.message_id),
            )
            if cursor.rowcount != 1:
                row = self._connection.execute(
                    "SELECT published_at, discarded_at FROM outbox WHERE message_id = ?",
                    (request.message_id,),
                ).fetchone()
                if row is None:
                    message = f"unknown outbox message: {request.message_id}"
                elif _optional_text(row, "published_at") is not None:
                    message = f"cannot retry published outbox message: {request.message_id}"
                else:
                    message = f"outbox message is not discarded: {request.message_id}"
                raise OutboxStateError(message)

            record = self._read_outbox(request.message_id)
            if record is None:
                message = f"retried outbox message disappeared: {request.message_id}"
                raise CorruptStateError(message)
            return record

    def _read_outbox(self, message_id: str) -> OutboxRecord | None:
        row = self._connection.execute(
            """
            SELECT
                sequence,
                message_id,
                run_id,
                topic,
                message_key,
                payload,
                created_at,
                available_at,
                attempt_count,
                last_attempt_at,
                last_error_type,
                claim_token,
                claim_until,
                published_at,
                discarded_at
            FROM outbox
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        return None if row is None else self._outbox_from_row(row)

    def _raise_outbox_transition_error(
        self,
        message_id: str,
        *,
        claim_token: str,
        expected_attempt_count: int,
    ) -> Never:
        row = self._connection.execute(
            """
            SELECT attempt_count, claim_token, published_at, discarded_at
            FROM outbox
            WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        if row is None:
            message = f"unknown outbox message: {message_id}"
        elif _optional_text(row, "published_at") is not None:
            message = f"outbox message already published: {message_id}"
        elif _optional_text(row, "discarded_at") is not None:
            message = f"outbox message already discarded: {message_id}"
        elif _optional_text(row, "claim_token") != claim_token:
            message = f"outbox claim changed: {message_id}"
        else:
            actual_attempt_count = _required_integer(row, "attempt_count")
            message = (
                f"outbox attempt count changed: {message_id}; "
                f"expected={expected_attempt_count}, actual={actual_attempt_count}"
            )
        raise OutboxStateError(message)

    def _configure_connection(self) -> None:
        self._connection.execute("PRAGMA foreign_keys = ON")
        if configure_sqlite_wal(self._connection) != "wal":
            message = "SQLite did not enable WAL journal mode"
            raise CorruptStateError(message)
        self._connection.execute("PRAGMA synchronous = NORMAL")

    def _initialize_schema(self) -> None:
        if self.schema_version == SCHEMA_VERSION:
            # 稳态只读校验，避免每个 runtime/maintenance opener 都争抢写锁。
            self._validate_schema()
            return
        # schema 判定与变更必须共享同一个写事务：否则并发 opener 会基于过期
        # user_version 重复迁移，校验失败也可能把半正确的 schema 永久标成新版。
        with self._transaction():
            version = self.schema_version
            tables = self.table_names()
            if version == 0:
                if tables:
                    message = f"unversioned database already contains tables: {sorted(tables)}"
                    raise SchemaVersionError(message)
                for statement in _SCHEMA_STATEMENTS:
                    self._connection.execute(statement)
            elif version == 3:
                self._migrate_v3_to_v4(tables)
            elif version != SCHEMA_VERSION:
                message = f"unsupported schema version: {version}; expected {SCHEMA_VERSION}"
                raise SchemaVersionError(message)

            self._validate_schema()
            if version != SCHEMA_VERSION:
                # 版本号最后写入；此前任何迁移或全表校验失败都会完整回滚。
                self._connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")

    def _migrate_v3_to_v4(self, tables: frozenset[str]) -> None:
        expected_tables = frozenset(_EXPECTED_COLUMNS)
        if tables != expected_tables:
            message = f"schema v3 tables mismatch: expected {sorted(expected_tables)}, actual {sorted(tables)}"
            raise SchemaVersionError(message)
        rows = self._connection.execute("PRAGMA table_info(outbox)").fetchall()
        actual_columns = tuple(_required_text(row, "name") for row in rows)
        if actual_columns != _V3_OUTBOX_COLUMNS:
            message = f"schema v3 outbox columns mismatch: expected {_V3_OUTBOX_COLUMNS}, actual {actual_columns}"
            raise SchemaVersionError(message)

        if not self._connection.in_transaction:
            message = "schema migration requires an active write transaction"
            raise RuntimeError(message)
        self._connection.execute("ALTER TABLE outbox RENAME TO outbox_v3")
        self._connection.execute(_OUTBOX_SCHEMA_STATEMENT)
        self._connection.execute(
            """
            INSERT INTO outbox(
                message_id,
                run_id,
                topic,
                message_key,
                payload,
                created_at,
                available_at,
                published_at
            )
            SELECT
                message_id,
                run_id,
                topic,
                message_key,
                payload,
                created_at,
                created_at,
                published_at
            FROM outbox_v3
            ORDER BY created_at, message_id
            """
        )
        self._connection.execute("DROP TABLE outbox_v3")
        self._connection.execute(_OUTBOX_READY_INDEX_STATEMENT)

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
            source_schedules=_decode_source_schedules(_required_text(row, "source_schedules")),
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
        raw_last_attempt_at = _optional_text(row, "last_attempt_at")
        raw_claim_until = _optional_text(row, "claim_until")
        raw_published_at = _optional_text(row, "published_at")
        raw_discarded_at = _optional_text(row, "discarded_at")
        return OutboxRecord(
            sequence=_required_integer(row, "sequence"),
            message_id=_required_text(row, "message_id"),
            run_id=_required_text(row, "run_id"),
            topic=_required_text(row, "topic"),
            payload=_decode_json(_required_text(row, "payload")),
            key=_optional_text(row, "message_key"),
            created_at=_decode_datetime(_required_text(row, "created_at"), field_name="outbox.created_at"),
            available_at=_decode_datetime(
                _required_text(row, "available_at"),
                field_name="outbox.available_at",
            ),
            attempt_count=_required_integer(row, "attempt_count"),
            last_attempt_at=(
                None
                if raw_last_attempt_at is None
                else _decode_datetime(raw_last_attempt_at, field_name="outbox.last_attempt_at")
            ),
            last_error_type=_optional_text(row, "last_error_type"),
            claim_token=_optional_text(row, "claim_token"),
            claim_until=(
                None if raw_claim_until is None else _decode_datetime(raw_claim_until, field_name="outbox.claim_until")
            ),
            published_at=(
                None
                if raw_published_at is None
                else _decode_datetime(raw_published_at, field_name="outbox.published_at")
            ),
            discarded_at=(
                None
                if raw_discarded_at is None
                else _decode_datetime(raw_discarded_at, field_name="outbox.discarded_at")
            ),
        )
