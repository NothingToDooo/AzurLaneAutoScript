from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING, Final, cast

from module.application import DeleteTaskState, TaskId, UpsertTaskState
from module.runtime.errors import TaskStateDocumentError
from module.runtime.task_state import TaskStateDocument

if TYPE_CHECKING:
    from module.application import StateEffect
    from module.runtime.settings import FrozenJsonValue


WORLD_PROGRESS_STATE_KEY: Final = "world_progress"
WORLD_PROGRESS_SCHEMA_VERSION: Final = 1


class WorldOperation(StrEnum):
    ASH_ASSIST = "opsi_ash_assist"
    ASH_BEACON = "opsi_ash_beacon"
    EXPLORE = "opsi_explore"
    SHOP = "opsi_shop"
    VOUCHER = "opsi_voucher"
    DAILY = "opsi_daily"
    OBSCURE = "opsi_obscure"
    MONTH_BOSS = "opsi_month_boss"
    ABYSSAL = "opsi_abyssal"
    ARCHIVE = "opsi_archive"
    STRONGHOLD = "opsi_stronghold"
    MEOWFFICER_FARMING = "opsi_meowfficer_farming"
    HAZARD1_LEVELING = "opsi_hazard1_leveling"
    CROSS_MONTH = "opsi_cross_month"


class WorldCheckpointMode(StrEnum):
    BOUNDED = "bounded"
    ONE_SHOT = "one_shot"


class WorldProgressCycle(StrEnum):
    SERVER_UPDATE = "server_update"
    MONTH_RESET = "month_reset"
    ARCHIVE_REFRESH = "archive_refresh"


@dataclass(frozen=True, slots=True)
class WorldCheckpointPolicy:
    mode: WorldCheckpointMode
    cycle: WorldProgressCycle | None

    def __post_init__(self) -> None:
        if not isinstance(self.mode, WorldCheckpointMode):
            message = "mode must be a WorldCheckpointMode"
            raise TypeError(message)
        if self.mode is WorldCheckpointMode.ONE_SHOT:
            if self.cycle is not None:
                message = "one-shot world task must not define a progress cycle"
                raise ValueError(message)
        elif not isinstance(self.cycle, WorldProgressCycle):
            message = "bounded world task requires a WorldProgressCycle"
            raise TypeError(message)


class WorldBossPhase(StrEnum):
    NORMAL = "normal"
    HARD = "hard"


class WorldMissionEvidenceKind(StrEnum):
    PINNED_ZONE = "pinned_zone"
    CURRENT_ZONE = "current_zone"
    ARCHIVE_ZONE = "archive_zone"
    LOGGER_PURCHASE = "logger_purchase"


@dataclass(frozen=True, slots=True)
class WorldZoneCursor:
    zone_id: int

    def __post_init__(self) -> None:
        if type(self.zone_id) is not int:
            message = "zone_id must be an integer"
            raise TypeError(message)
        if self.zone_id <= 0:
            message = "zone_id must be positive"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class WorldMissionCursor:
    evidence_kind: WorldMissionEvidenceKind
    zone_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.evidence_kind, WorldMissionEvidenceKind):
            message = "evidence_kind must be a WorldMissionEvidenceKind"
            raise TypeError(message)
        needs_zone = self.evidence_kind in {
            WorldMissionEvidenceKind.PINNED_ZONE,
            WorldMissionEvidenceKind.CURRENT_ZONE,
        }
        if needs_zone:
            if type(self.zone_id) is not int:
                message = f"{self.evidence_kind.value} evidence requires an integer zone_id"
                raise TypeError(message)
            if self.zone_id <= 0:
                message = "zone_id must be positive"
                raise ValueError(message)
        elif self.zone_id is not None:
            message = f"{self.evidence_kind.value} evidence must not contain zone_id"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class WorldBossCursor:
    phase: WorldBossPhase

    def __post_init__(self) -> None:
        if not isinstance(self.phase, WorldBossPhase):
            message = "phase must be a WorldBossPhase"
            raise TypeError(message)


type WorldProgressCursor = WorldZoneCursor | WorldMissionCursor | WorldBossCursor


_CURSOR_TYPE_BY_OPERATION: Final[Mapping[WorldOperation, type[WorldProgressCursor]]] = MappingProxyType(
    {
        WorldOperation.EXPLORE: WorldZoneCursor,
        WorldOperation.DAILY: WorldMissionCursor,
        WorldOperation.OBSCURE: WorldZoneCursor,
        WorldOperation.MONTH_BOSS: WorldBossCursor,
        WorldOperation.ABYSSAL: WorldZoneCursor,
        WorldOperation.ARCHIVE: WorldMissionCursor,
        WorldOperation.STRONGHOLD: WorldZoneCursor,
        WorldOperation.MEOWFFICER_FARMING: WorldZoneCursor,
        WorldOperation.HAZARD1_LEVELING: WorldZoneCursor,
    }
)


def _validate_text(value: str, *, field_name: str) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if not value or value != value.strip():
        message = f"{field_name} must be trimmed and non-empty"
        raise ValueError(message)


def _validate_aware_datetime(value: datetime, *, field_name: str) -> None:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    if value.utcoffset() is None:
        message = f"{field_name} must be timezone-aware"
        raise ValueError(message)


def expected_world_cursor_type(operation: WorldOperation) -> type[WorldProgressCursor] | None:
    if not isinstance(operation, WorldOperation):
        message = "operation must be a WorldOperation"
        raise TypeError(message)
    return _CURSOR_TYPE_BY_OPERATION.get(operation)


def validate_world_cursor(operation: WorldOperation, cursor: WorldProgressCursor | None) -> None:
    expected = expected_world_cursor_type(operation)
    if expected is None:
        if cursor is not None:
            message = f"{operation.value} progress does not accept a cursor"
            raise ValueError(message)
        return
    if not isinstance(cursor, expected):
        message = f"{operation.value} progress requires a {expected.__name__}"
        raise TypeError(message)


@dataclass(frozen=True, slots=True)
class WorldProgress:
    task_id: TaskId
    operation: WorldOperation
    completed_units: int
    cycle_anchor: datetime
    settings_revision: int
    content_revision: str
    cursor: WorldProgressCursor | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, TaskId):
            message = "task_id must be a TaskId"
            raise TypeError(message)
        if not isinstance(self.operation, WorldOperation):
            message = "operation must be a WorldOperation"
            raise TypeError(message)
        if self.task_id.value != self.operation.value:
            message = "task_id must match operation"
            raise ValueError(message)
        if type(self.completed_units) is not int:
            message = "completed_units must be an integer"
            raise TypeError(message)
        if self.completed_units < 0:
            message = "completed_units must be non-negative"
            raise ValueError(message)
        _validate_aware_datetime(self.cycle_anchor, field_name="cycle_anchor")
        if type(self.settings_revision) is not int:
            message = "settings_revision must be an integer"
            raise TypeError(message)
        if self.settings_revision <= 0:
            message = "settings_revision must be positive"
            raise ValueError(message)
        _validate_text(self.content_revision, field_name="content_revision")
        validate_world_cursor(self.operation, self.cursor)
        if self.completed_units == 0 and self.cursor is None:
            message = "zero-unit progress requires a resumable cursor"
            raise ValueError(message)

    def to_payload(self) -> dict[str, object]:
        return {
            "task_id": self.task_id.value,
            "operation": self.operation.value,
            "completed_units": self.completed_units,
            "cycle_anchor": self.cycle_anchor.astimezone(UTC).isoformat(timespec="microseconds"),
            "settings_revision": self.settings_revision,
            "content_revision": self.content_revision,
            "cursor": _cursor_payload(self.cursor),
        }


def _cursor_payload(cursor: WorldProgressCursor | None) -> dict[str, object] | None:
    if cursor is None:
        return None
    if isinstance(cursor, WorldZoneCursor):
        return {"kind": "zone", "zone_id": cursor.zone_id}
    if isinstance(cursor, WorldMissionCursor):
        return {
            "kind": "mission",
            "evidence_kind": cursor.evidence_kind.value,
            "zone_id": cursor.zone_id,
        }
    if isinstance(cursor, WorldBossCursor):
        return {"kind": "boss", "phase": cursor.phase.value}
    message = f"unsupported world progress cursor: {type(cursor).__name__}"
    raise TypeError(message)


def _object(value: FrozenJsonValue, *, path: str) -> Mapping[str, FrozenJsonValue]:
    if not isinstance(value, Mapping):
        message = f"{path} must be an object"
        raise TaskStateDocumentError(message)
    return cast("Mapping[str, FrozenJsonValue]", value)


def _exact_fields(value: Mapping[str, FrozenJsonValue], expected: set[str], *, path: str) -> None:
    actual = set(value)
    if actual == expected:
        return
    missing = sorted(expected - actual)
    unknown = sorted(actual - expected)
    message = f"{path} fields mismatch: missing={missing}, unknown={unknown}"
    raise TaskStateDocumentError(message)


def _text(value: FrozenJsonValue, *, path: str) -> str:
    if not isinstance(value, str):
        message = f"{path} must be a string"
        raise TaskStateDocumentError(message)
    if not value or value != value.strip():
        message = f"{path} must be trimmed and non-empty"
        raise TaskStateDocumentError(message)
    return value


def _integer(value: FrozenJsonValue, *, path: str, minimum: int = 0) -> int:
    if type(value) is not int:
        message = f"{path} must be an integer"
        raise TaskStateDocumentError(message)
    result = value
    if result < minimum:
        message = f"{path} must be at least {minimum}"
        raise TaskStateDocumentError(message)
    return result


def _datetime(value: FrozenJsonValue, *, path: str) -> datetime:
    raw = _text(value, path=path)
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as error:
        message = f"{path} must be an ISO datetime"
        raise TaskStateDocumentError(message) from error
    if parsed.utcoffset() is None:
        message = f"{path} must be timezone-aware"
        raise TaskStateDocumentError(message)
    return parsed.astimezone(UTC)


def _cursor_from_payload(value: FrozenJsonValue, *, path: str) -> WorldProgressCursor | None:
    if value is None:
        return None
    payload = _object(value, path=path)
    kind = _text(payload.get("kind"), path=f"{path}.kind")
    if kind == "zone":
        _exact_fields(payload, {"kind", "zone_id"}, path=path)
        try:
            return WorldZoneCursor(_integer(payload["zone_id"], path=f"{path}.zone_id", minimum=1))
        except (TypeError, ValueError) as error:
            raise TaskStateDocumentError(str(error)) from error
    if kind == "mission":
        _exact_fields(payload, {"kind", "evidence_kind", "zone_id"}, path=path)
        raw_evidence_kind = _text(payload["evidence_kind"], path=f"{path}.evidence_kind")
        try:
            evidence_kind = WorldMissionEvidenceKind(raw_evidence_kind)
        except ValueError as error:
            message = f"{path}.evidence_kind has unknown value: {raw_evidence_kind!r}"
            raise TaskStateDocumentError(message) from error
        raw_zone_id = payload["zone_id"]
        zone_id = None if raw_zone_id is None else _integer(raw_zone_id, path=f"{path}.zone_id", minimum=1)
        try:
            return WorldMissionCursor(evidence_kind, zone_id)
        except (TypeError, ValueError) as error:
            raise TaskStateDocumentError(str(error)) from error
    if kind == "boss":
        _exact_fields(payload, {"kind", "phase"}, path=path)
        raw_phase = _text(payload["phase"], path=f"{path}.phase")
        try:
            return WorldBossCursor(WorldBossPhase(raw_phase))
        except ValueError as error:
            message = f"{path}.phase has unknown value: {raw_phase!r}"
            raise TaskStateDocumentError(message) from error
    message = f"{path}.kind has unknown value: {kind!r}"
    raise TaskStateDocumentError(message)


def world_progress_from_payload(payload: FrozenJsonValue) -> WorldProgress:
    root = f"$.{WORLD_PROGRESS_STATE_KEY}"
    value = _object(payload, path=root)
    _exact_fields(
        value,
        {
            "task_id",
            "operation",
            "completed_units",
            "cycle_anchor",
            "settings_revision",
            "content_revision",
            "cursor",
        },
        path=root,
    )
    raw_operation = _text(value["operation"], path=f"{root}.operation")
    try:
        operation = WorldOperation(raw_operation)
    except ValueError as error:
        message = f"{root}.operation has unknown value: {raw_operation!r}"
        raise TaskStateDocumentError(message) from error
    raw_task_id = _text(value["task_id"], path=f"{root}.task_id")
    try:
        progress = WorldProgress(
            task_id=TaskId(raw_task_id),
            operation=operation,
            completed_units=_integer(value["completed_units"], path=f"{root}.completed_units"),
            cycle_anchor=_datetime(value["cycle_anchor"], path=f"{root}.cycle_anchor"),
            settings_revision=_integer(value["settings_revision"], path=f"{root}.settings_revision", minimum=1),
            content_revision=_text(value["content_revision"], path=f"{root}.content_revision"),
            cursor=_cursor_from_payload(value["cursor"], path=f"{root}.cursor"),
        )
    except (TypeError, ValueError) as error:
        raise TaskStateDocumentError(str(error)) from error
    return progress


def hydrate_world_progress(operation: WorldOperation, document: TaskStateDocument) -> WorldProgress | None:
    if not isinstance(operation, WorldOperation):
        message = "operation must be a WorldOperation"
        raise TypeError(message)
    if not isinstance(document, TaskStateDocument):
        message = "document must be a TaskStateDocument"
        raise TypeError(message)
    if document.namespace != operation.value:
        message = "task state namespace must match world operation"
        raise TaskStateDocumentError(message)
    unknown = sorted(set(document.entries) - {WORLD_PROGRESS_STATE_KEY})
    if unknown:
        message = f"unknown Operation Siren task state keys: {unknown}"
        raise TaskStateDocumentError(message)
    entry = document.get(WORLD_PROGRESS_STATE_KEY)
    if entry is None:
        return None
    if entry.schema_version != WORLD_PROGRESS_SCHEMA_VERSION:
        message = (
            f"unsupported {WORLD_PROGRESS_STATE_KEY} schema version: "
            f"{entry.schema_version}; expected {WORLD_PROGRESS_SCHEMA_VERSION}"
        )
        raise TaskStateDocumentError(message)
    progress = world_progress_from_payload(entry.payload)
    if progress.operation is not operation or progress.task_id.value != operation.value:
        message = "world progress identity does not match task state namespace"
        raise TaskStateDocumentError(message)
    return progress


def upsert_world_progress(progress: WorldProgress) -> StateEffect:
    if not isinstance(progress, WorldProgress):
        message = "progress must be a WorldProgress"
        raise TypeError(message)
    return UpsertTaskState(
        progress.task_id.value,
        WORLD_PROGRESS_STATE_KEY,
        WORLD_PROGRESS_SCHEMA_VERSION,
        progress.to_payload(),
    )


def delete_world_progress(operation: WorldOperation) -> StateEffect:
    if not isinstance(operation, WorldOperation):
        message = "operation must be a WorldOperation"
        raise TypeError(message)
    return DeleteTaskState(operation.value, WORLD_PROGRESS_STATE_KEY)
