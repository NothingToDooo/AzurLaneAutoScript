import re
from dataclasses import dataclass
from enum import StrEnum

from module.content.errors import ContentValidationError

_PROFILE_ID_PATTERN = re.compile(r"[a-z][a-z0-9_]*", flags=re.ASCII)
_STAGE_ID_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*", flags=re.ASCII)


def _validate_identifier(value: str, *, field_name: str, pattern: re.Pattern[str]) -> None:
    if not isinstance(value, str):
        message = f"{field_name} must be a string"
        raise TypeError(message)
    if pattern.fullmatch(value) is None:
        message = f"{field_name} must be a canonical identifier"
        raise ContentValidationError(message)


@dataclass(frozen=True, slots=True)
class EventStoryProfileId:
    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, field_name="event story profile id", pattern=_PROFILE_ID_PATTERN)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class RaidProfileId:
    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, field_name="raid profile id", pattern=_PROFILE_ID_PATTERN)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CoalitionProfileId:
    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, field_name="coalition profile id", pattern=_PROFILE_ID_PATTERN)

    def __str__(self) -> str:
        return self.value


class ActivityKind(StrEnum):
    EVENT_STORY = "event_story"
    RAID = "raid"
    COALITION = "coalition"


class RaidMode(StrEnum):
    EASY = "easy"
    NORMAL = "normal"
    HARD = "hard"
    EX = "ex"


class CoalitionFleetMode(StrEnum):
    SINGLE = "single"
    MULTI = "multi"


class CoalitionFleetRule(StrEnum):
    SELECTABLE = "selectable"
    SINGLE = "single"
    MULTI = "multi"

    def allows(self, fleet: CoalitionFleetMode) -> bool:
        if not isinstance(fleet, CoalitionFleetMode):
            message = "fleet must be a CoalitionFleetMode"
            raise TypeError(message)
        return self is CoalitionFleetRule.SELECTABLE or self.value == fleet.value


@dataclass(frozen=True, slots=True)
class CoalitionStageId:
    value: str

    def __post_init__(self) -> None:
        _validate_identifier(self.value, field_name="coalition stage id", pattern=_STAGE_ID_PATTERN)

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class EventStoryDefinition:
    profile_id: EventStoryProfileId | None

    def __post_init__(self) -> None:
        if self.profile_id is not None and not isinstance(self.profile_id, EventStoryProfileId):
            message = "profile_id must be an EventStoryProfileId or None"
            raise TypeError(message)

    @property
    def kind(self) -> ActivityKind:
        return ActivityKind.EVENT_STORY

    @property
    def available(self) -> bool:
        return self.profile_id is not None


@dataclass(frozen=True, slots=True)
class RaidDefinition:
    profile_id: RaidProfileId
    modes: tuple[RaidMode, ...]
    daily_modes: tuple[RaidMode, ...]
    ticket_modes: tuple[RaidMode, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, RaidProfileId):
            message = "profile_id must be a RaidProfileId"
            raise TypeError(message)
        modes = self._validate_modes(self.modes, field_name="modes", allow_empty=False)
        daily_modes = self._validate_modes(self.daily_modes, field_name="daily_modes", allow_empty=True)
        ticket_modes = self._validate_modes(self.ticket_modes, field_name="ticket_modes", allow_empty=True)
        if not set(daily_modes).issubset(modes):
            message = "daily_modes must be a subset of modes"
            raise ContentValidationError(message)
        if not set(ticket_modes).issubset(modes):
            message = "ticket_modes must be a subset of modes"
            raise ContentValidationError(message)
        object.__setattr__(self, "modes", modes)
        object.__setattr__(self, "daily_modes", daily_modes)
        object.__setattr__(self, "ticket_modes", ticket_modes)

    @staticmethod
    def _validate_modes(
        values: tuple[RaidMode, ...],
        *,
        field_name: str,
        allow_empty: bool,
    ) -> tuple[RaidMode, ...]:
        if not isinstance(values, tuple):
            message = f"{field_name} must be a tuple"
            raise TypeError(message)
        if not allow_empty and not values:
            message = f"{field_name} must not be empty"
            raise ContentValidationError(message)
        if any(not isinstance(value, RaidMode) for value in values):
            message = f"{field_name} must contain RaidMode values"
            raise TypeError(message)
        if len(set(values)) != len(values):
            message = f"{field_name} must not contain duplicates"
            raise ContentValidationError(message)
        return values

    @property
    def kind(self) -> ActivityKind:
        return ActivityKind.RAID

    @property
    def supports_daily(self) -> bool:
        return bool(self.daily_modes)


@dataclass(frozen=True, slots=True)
class CoalitionStageDefinition:
    stage_id: CoalitionStageId
    battle_count: int
    fleet_rule: CoalitionFleetRule

    def __post_init__(self) -> None:
        if not isinstance(self.stage_id, CoalitionStageId):
            message = "stage_id must be a CoalitionStageId"
            raise TypeError(message)
        if type(self.battle_count) is not int:
            message = "battle_count must be an integer"
            raise TypeError(message)
        if self.battle_count <= 0:
            message = "battle_count must be positive"
            raise ContentValidationError(message)
        if not isinstance(self.fleet_rule, CoalitionFleetRule):
            message = "fleet_rule must be a CoalitionFleetRule"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CoalitionDefinition:
    profile_id: CoalitionProfileId
    stages: tuple[CoalitionStageDefinition, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.profile_id, CoalitionProfileId):
            message = "profile_id must be a CoalitionProfileId"
            raise TypeError(message)
        if not isinstance(self.stages, tuple):
            message = "stages must be a tuple"
            raise TypeError(message)
        if not self.stages:
            message = "stages must not be empty"
            raise ContentValidationError(message)
        if any(not isinstance(stage, CoalitionStageDefinition) for stage in self.stages):
            message = "stages must contain CoalitionStageDefinition values"
            raise TypeError(message)
        stage_ids = tuple(stage.stage_id for stage in self.stages)
        if len(set(stage_ids)) != len(stage_ids):
            message = "stages must not contain duplicate ids"
            raise ContentValidationError(message)

    @property
    def kind(self) -> ActivityKind:
        return ActivityKind.COALITION

    def get_stage(self, stage_id: CoalitionStageId) -> CoalitionStageDefinition | None:
        if not isinstance(stage_id, CoalitionStageId):
            message = "stage_id must be a CoalitionStageId"
            raise TypeError(message)
        return next((stage for stage in self.stages if stage.stage_id == stage_id), None)


type ActivityDefinition = EventStoryDefinition | RaidDefinition | CoalitionDefinition
