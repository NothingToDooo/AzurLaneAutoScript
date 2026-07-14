from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from module.state.errors import RunStateError

type JsonValue = bool | int | float | str | list[JsonValue] | dict[str, JsonValue] | None


class RunStatus(StrEnum):
    """持久化运行状态；除 RUNNING 外均为终态。"""

    RUNNING = "running"
    SUCCEEDED = "succeeded"
    DEFERRED = "deferred"
    RETRYABLE = "retryable"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"
    FAULTED = "faulted"


class RunMode(StrEnum):
    """run 的闭集启动入口。"""

    SCHEDULED_JOB = "scheduled_job"
    ASSIST_SESSION = "assist_session"
    DIRECT_COMMAND = "direct_command"


TERMINAL_RUN_STATUSES: frozenset[RunStatus] = frozenset(
    status for status in RunStatus if status is not RunStatus.RUNNING
)


def _require_non_empty_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value.strip():
        message = f"{field_name} must not be empty or whitespace"
        raise ValueError(message)


def _require_aware_datetime(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)


def _require_trimmed_non_empty_text(value: str, *, field_name: str) -> None:
    _require_non_empty_text(value, field_name=field_name)
    if value != value.strip():
        message = f"{field_name} must not contain leading or trailing whitespace"
        raise ValueError(message)


def _require_identifier(value: str, *, field_name: str) -> None:
    _require_non_empty_text(value, field_name=field_name)
    if any(character.isspace() for character in value):
        message = f"{field_name} must not contain whitespace"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class SettingsSnapshot:
    revision: int
    payload: JsonValue
    updated_at: datetime

    def __post_init__(self) -> None:
        if type(self.revision) is not int or self.revision <= 0:
            message = "revision must be a positive integer"
            raise ValueError(message)
        _require_aware_datetime(self.updated_at, field_name="updated_at")


@dataclass(frozen=True, slots=True)
class ConfigurationSourceSnapshot:
    """编译配置摘要与其实际发布到的 settings revision。"""

    source_revision: str
    settings_revision: int
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_trimmed_non_empty_text(self.source_revision, field_name="source_revision")
        if type(self.settings_revision) is not int or self.settings_revision <= 0:
            message = "settings_revision must be a positive integer"
            raise ValueError(message)
        _require_aware_datetime(self.updated_at, field_name="updated_at")


@dataclass(frozen=True, slots=True)
class ScheduleMutation:
    """coordinator 写入 schedule 表的完整持久化记录。"""

    task_id: str
    enabled: bool
    due_at: datetime | None
    priority: int

    def __post_init__(self) -> None:
        _require_non_empty_text(self.task_id, field_name="task_id")
        if type(self.enabled) is not bool:
            message = "enabled must be a bool"
            raise TypeError(message)
        if self.due_at is not None:
            _require_aware_datetime(self.due_at, field_name="due_at")
        if type(self.priority) is not int:
            message = "priority must be an integer"
            raise TypeError(message)
        if self.priority < 0:
            message = "priority must not be negative"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class ScheduleRecord:
    task_id: str
    enabled: bool
    due_at: datetime | None
    priority: int
    updated_at: datetime

    def __post_init__(self) -> None:
        ScheduleMutation(
            task_id=self.task_id,
            enabled=self.enabled,
            due_at=self.due_at,
            priority=self.priority,
        )
        _require_aware_datetime(self.updated_at, field_name="updated_at")


@dataclass(frozen=True, slots=True)
class TaskStateRecord:
    namespace: str
    key: str
    version: int
    payload: JsonValue
    updated_at: datetime

    def __post_init__(self) -> None:
        _require_non_empty_text(self.namespace, field_name="namespace")
        _require_non_empty_text(self.key, field_name="key")
        if type(self.version) is not int or self.version <= 0:
            message = "version must be a positive integer"
            raise ValueError(message)
        _require_aware_datetime(self.updated_at, field_name="updated_at")


@dataclass(frozen=True, slots=True)
class TaskResolutionSnapshot:
    """同一个 SQLite read transaction 中读取的 settings、schedule 与当前 task state。"""

    task_id: str
    settings: SettingsSnapshot | None
    state_records: tuple[TaskStateRecord, ...]
    schedule_records: tuple[ScheduleRecord, ...] = ()

    def __post_init__(self) -> None:
        _require_identifier(self.task_id, field_name="task_id")
        if self.settings is not None and not isinstance(self.settings, SettingsSnapshot):
            message = "settings must be a SettingsSnapshot or None"
            raise TypeError(message)
        if not isinstance(self.state_records, tuple):
            message = "state_records must be a tuple"
            raise TypeError(message)
        if any(not isinstance(record, TaskStateRecord) for record in self.state_records):
            message = "state_records must contain TaskStateRecord values"
            raise TypeError(message)
        if any(record.namespace != self.task_id for record in self.state_records):
            message = "state_records namespace must match task_id"
            raise ValueError(message)
        keys = tuple(record.key for record in self.state_records)
        if len(keys) != len(set(keys)):
            message = "state_records must not contain duplicate keys"
            raise ValueError(message)
        if not isinstance(self.schedule_records, tuple):
            message = "schedule_records must be a tuple"
            raise TypeError(message)
        if any(not isinstance(record, ScheduleRecord) for record in self.schedule_records):
            message = "schedule_records must contain ScheduleRecord values"
            raise TypeError(message)
        schedule_task_ids = tuple(record.task_id for record in self.schedule_records)
        if len(schedule_task_ids) != len(set(schedule_task_ids)):
            message = "schedule_records must not contain duplicate task ids"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class UpsertTaskStateMutation:
    namespace: str
    key: str
    schema_version: int
    payload: JsonValue

    def __post_init__(self) -> None:
        _require_identifier(self.namespace, field_name="namespace")
        _require_identifier(self.key, field_name="key")
        if type(self.schema_version) is not int:
            message = "schema_version must be an integer"
            raise TypeError(message)
        if self.schema_version <= 0:
            message = "schema_version must be positive"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class DeleteTaskStateMutation:
    namespace: str
    key: str

    def __post_init__(self) -> None:
        _require_identifier(self.namespace, field_name="namespace")
        _require_identifier(self.key, field_name="key")


type TaskStateMutation = UpsertTaskStateMutation | DeleteTaskStateMutation


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    task_id: str
    mode: RunMode
    settings_revision: int
    content_revision: str
    client_ui_revision: str
    status: RunStatus
    started_at: datetime
    finished_at: datetime | None
    result_payload: JsonValue
    error: str | None

    def __post_init__(self) -> None:
        _require_non_empty_text(self.run_id, field_name="run_id")
        _require_non_empty_text(self.task_id, field_name="task_id")
        if not isinstance(self.mode, RunMode):
            message = "mode must be a RunMode"
            raise TypeError(message)
        if type(self.settings_revision) is not int or self.settings_revision <= 0:
            message = "settings_revision must be a positive integer"
            raise ValueError(message)
        _require_trimmed_non_empty_text(self.content_revision, field_name="content_revision")
        _require_trimmed_non_empty_text(self.client_ui_revision, field_name="client_ui_revision")
        if not isinstance(self.status, RunStatus):
            message = "status must be a RunStatus"
            raise TypeError(message)
        _require_aware_datetime(self.started_at, field_name="started_at")
        if self.status is RunStatus.RUNNING:
            if self.finished_at is not None or self.result_payload is not None or self.error is not None:
                message = "running run must not contain terminal fields"
                raise RunStateError(message)
        elif self.finished_at is None:
            message = "terminal run must have finished_at"
            raise RunStateError(message)
        else:
            _require_aware_datetime(self.finished_at, field_name="finished_at")
        if self.error is not None:
            _require_non_empty_text(self.error, field_name="error")


@dataclass(frozen=True, slots=True)
class RunEvent:
    kind: str
    payload: JsonValue
    occurred_at: datetime

    def __post_init__(self) -> None:
        _require_non_empty_text(self.kind, field_name="kind")
        _require_aware_datetime(self.occurred_at, field_name="occurred_at")


@dataclass(frozen=True, slots=True)
class RunEventRecord:
    run_id: str
    sequence: int
    kind: str
    payload: JsonValue
    occurred_at: datetime

    def __post_init__(self) -> None:
        _require_non_empty_text(self.run_id, field_name="run_id")
        if type(self.sequence) is not int or self.sequence <= 0:
            message = "sequence must be a positive integer"
            raise ValueError(message)
        RunEvent(kind=self.kind, payload=self.payload, occurred_at=self.occurred_at)


@dataclass(frozen=True, slots=True)
class OutboxMessage:
    message_id: str
    topic: str
    payload: JsonValue
    key: str | None = None

    def __post_init__(self) -> None:
        _require_non_empty_text(self.message_id, field_name="message_id")
        _require_non_empty_text(self.topic, field_name="topic")
        if self.key is not None:
            _require_non_empty_text(self.key, field_name="key")


def _validate_finalization_collections(
    schedule_mutations: tuple[ScheduleMutation, ...],
    task_state_mutations: tuple[TaskStateMutation, ...],
    events: tuple[RunEvent, ...],
    outbox_messages: tuple[OutboxMessage, ...],
) -> None:
    if any(not isinstance(mutation, ScheduleMutation) for mutation in schedule_mutations):
        message = "schedule_mutations must contain ScheduleMutation instances"
        raise TypeError(message)
    if any(
        not isinstance(mutation, UpsertTaskStateMutation | DeleteTaskStateMutation) for mutation in task_state_mutations
    ):
        message = "task_state_mutations must contain TaskStateMutation instances"
        raise TypeError(message)
    if any(not isinstance(event, RunEvent) for event in events):
        message = "events must contain RunEvent instances"
        raise TypeError(message)
    if any(not isinstance(outbox_message, OutboxMessage) for outbox_message in outbox_messages):
        message = "outbox_messages must contain OutboxMessage instances"
        raise TypeError(message)

    task_ids = tuple(mutation.task_id for mutation in schedule_mutations)
    if len(task_ids) != len(set(task_ids)):
        message = "schedule_mutations must not contain duplicate task_id values"
        raise ValueError(message)
    state_addresses = tuple((mutation.namespace, mutation.key) for mutation in task_state_mutations)
    if len(state_addresses) != len(set(state_addresses)):
        message = "task_state_mutations must not contain duplicate namespace/key values"
        raise ValueError(message)
    message_ids = tuple(outbox_message.message_id for outbox_message in outbox_messages)
    if len(message_ids) != len(set(message_ids)):
        message = "outbox_messages must not contain duplicate message_id values"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class RunFinalization:
    """一次 run 终态提交所需的完整持久化 DTO。"""

    status: RunStatus
    finished_at: datetime
    result_payload: JsonValue = None
    error: str | None = None
    schedule_mutations: tuple[ScheduleMutation, ...] = ()
    task_state_mutations: tuple[TaskStateMutation, ...] = ()
    events: tuple[RunEvent, ...] = ()
    outbox_messages: tuple[OutboxMessage, ...] = ()

    def __post_init__(self) -> None:
        if not isinstance(self.status, RunStatus):
            message = "status must be a RunStatus"
            raise TypeError(message)
        if self.status not in TERMINAL_RUN_STATUSES:
            message = "run finalization requires a terminal status"
            raise RunStateError(message)
        _require_aware_datetime(self.finished_at, field_name="finished_at")
        if self.error is not None:
            _require_non_empty_text(self.error, field_name="error")

        schedule_mutations = tuple(self.schedule_mutations)
        task_state_mutations = tuple(self.task_state_mutations)
        events = tuple(self.events)
        outbox_messages = tuple(self.outbox_messages)
        _validate_finalization_collections(
            schedule_mutations,
            task_state_mutations,
            events,
            outbox_messages,
        )

        object.__setattr__(self, "schedule_mutations", schedule_mutations)
        object.__setattr__(self, "task_state_mutations", task_state_mutations)
        object.__setattr__(self, "events", events)
        object.__setattr__(self, "outbox_messages", outbox_messages)


@dataclass(frozen=True, slots=True)
class OutboxRecord:
    message_id: str
    run_id: str
    topic: str
    payload: JsonValue
    key: str | None
    created_at: datetime
    published_at: datetime | None

    def __post_init__(self) -> None:
        OutboxMessage(message_id=self.message_id, topic=self.topic, payload=self.payload, key=self.key)
        _require_non_empty_text(self.run_id, field_name="run_id")
        _require_aware_datetime(self.created_at, field_name="created_at")
        if self.published_at is not None:
            _require_aware_datetime(self.published_at, field_name="published_at")
