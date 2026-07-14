from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType

from module.base.button import Button
from module.coalition import assets as coalition_assets
from module.content.activity_catalog import CoalitionActivity
from module.content.activity_profile import (
    CoalitionDefinition,
    CoalitionFleetMode,
    CoalitionProfileId,
    CoalitionStageDefinition,
    CoalitionStageId,
)


class CoalitionModeDriver(StrEnum):
    STANDARD = "standard"
    RED_TEXT = "red_text"
    NONE = "none"


class CoalitionEntryStrategy(StrEnum):
    DIRECT = "direct"
    AREA_THEN_DIFFICULTY = "area_then_difficulty"


class CoalitionPtOcrStrategy(StrEnum):
    PLAIN = "plain"
    AFTER_COLON = "after_colon"
    AFTER_X = "after_x"


class CoalitionOilReadLocation(StrEnum):
    COALITION = "coalition"
    CAMPAIGN_MENU = "campaign_menu"


class CoalitionPageMode(StrEnum):
    STORY = "story"
    BATTLE = "battle"


@dataclass(frozen=True, slots=True)
class CoalitionModeSwitchAssets:
    story: Button
    battle: Button

    def __post_init__(self) -> None:
        if not isinstance(self.story, Button) or not isinstance(self.battle, Button):
            message = "coalition mode switch assets must be Button values"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CoalitionFleetSwitchAssets:
    single: Button
    multi: Button

    def __post_init__(self) -> None:
        if not isinstance(self.single, Button) or not isinstance(self.multi, Button):
            message = "coalition fleet switch assets must be Button values"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CoalitionPreparationAssets:
    enter: Button
    exit: Button
    difficulty_exit: Button | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.enter, Button) or not isinstance(self.exit, Button):
            message = "coalition preparation enter and exit assets must be Button values"
            raise TypeError(message)
        if self.difficulty_exit is not None and not isinstance(self.difficulty_exit, Button):
            message = "coalition difficulty exit asset must be a Button or None"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CoalitionStageAssets:
    stage_id: CoalitionStageId
    entrance: Button
    difficulty: Button | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.stage_id, CoalitionStageId):
            message = "stage_id must be a CoalitionStageId"
            raise TypeError(message)
        if not isinstance(self.entrance, Button):
            message = "coalition stage entrance must be a Button"
            raise TypeError(message)
        if self.difficulty is not None and not isinstance(self.difficulty, Button):
            message = "coalition stage difficulty must be a Button or None"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CoalitionPtOcrProfile:
    region: Button
    strategy: CoalitionPtOcrStrategy
    letter: tuple[int, int, int]
    threshold: int
    alphabet: str | None = None
    language: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.region, Button):
            message = "coalition PT OCR region must be a Button"
            raise TypeError(message)
        if not isinstance(self.strategy, CoalitionPtOcrStrategy):
            message = "coalition PT OCR strategy must be a CoalitionPtOcrStrategy"
            raise TypeError(message)
        if (
            not isinstance(self.letter, tuple)
            or len(self.letter) != 3
            or any(type(component) is not int or not 0 <= component <= 255 for component in self.letter)
        ):
            message = "coalition PT OCR letter must be an RGB tuple"
            raise ValueError(message)
        if type(self.threshold) is not int or not 0 <= self.threshold <= 255:
            message = "coalition PT OCR threshold must be an integer from 0 to 255"
            raise ValueError(message)
        for field_name, value in (("alphabet", self.alphabet), ("language", self.language)):
            if value is not None and (not isinstance(value, str) or not value):
                message = f"coalition PT OCR {field_name} must be a non-empty string or None"
                raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CoalitionClientProfile:
    profile_id: CoalitionProfileId
    mode_driver: CoalitionModeDriver
    entry_strategy: CoalitionEntryStrategy
    pt_ocr: CoalitionPtOcrProfile
    oil_read_location: CoalitionOilReadLocation
    mode_switch: CoalitionModeSwitchAssets | None
    fleet_switch: CoalitionFleetSwitchAssets
    preparation: CoalitionPreparationAssets
    stages: tuple[CoalitionStageAssets, ...]

    def __post_init__(self) -> None:
        self._validate_kinds()
        self._validate_mode_switch()
        self._validate_stage_assets()
        self._validate_entry_assets()

    def _validate_kinds(self) -> None:
        if not isinstance(self.profile_id, CoalitionProfileId):
            message = "profile_id must be a CoalitionProfileId"
            raise TypeError(message)
        if not isinstance(self.mode_driver, CoalitionModeDriver):
            message = "mode_driver must be a CoalitionModeDriver"
            raise TypeError(message)
        if not isinstance(self.entry_strategy, CoalitionEntryStrategy):
            message = "entry_strategy must be a CoalitionEntryStrategy"
            raise TypeError(message)
        if not isinstance(self.pt_ocr, CoalitionPtOcrProfile):
            message = "pt_ocr must be a CoalitionPtOcrProfile"
            raise TypeError(message)
        if not isinstance(self.oil_read_location, CoalitionOilReadLocation):
            message = "oil_read_location must be a CoalitionOilReadLocation"
            raise TypeError(message)

    def _validate_mode_switch(self) -> None:
        if self.mode_driver is CoalitionModeDriver.NONE:
            if self.mode_switch is not None:
                message = "mode_switch must be None when the mode driver is none"
                raise ValueError(message)
        elif not isinstance(self.mode_switch, CoalitionModeSwitchAssets):
            message = "mode_switch is required when a mode driver is configured"
            raise TypeError(message)

    def _validate_stage_assets(self) -> None:
        if not isinstance(self.fleet_switch, CoalitionFleetSwitchAssets):
            message = "fleet_switch must be CoalitionFleetSwitchAssets"
            raise TypeError(message)
        if not isinstance(self.preparation, CoalitionPreparationAssets):
            message = "preparation must be CoalitionPreparationAssets"
            raise TypeError(message)
        if not isinstance(self.stages, tuple) or not self.stages:
            message = "stages must be a non-empty tuple"
            raise TypeError(message)
        if any(not isinstance(stage, CoalitionStageAssets) for stage in self.stages):
            message = "stages must contain CoalitionStageAssets values"
            raise TypeError(message)
        stage_ids = tuple(stage.stage_id for stage in self.stages)
        if len(set(stage_ids)) != len(stage_ids):
            message = f"duplicate coalition client stage in profile {self.profile_id.value}"
            raise ValueError(message)

    def _validate_entry_assets(self) -> None:
        if self.entry_strategy is CoalitionEntryStrategy.DIRECT:
            if any(stage.difficulty is not None for stage in self.stages):
                message = "direct coalition entry must not define difficulty assets"
                raise ValueError(message)
            if self.preparation.difficulty_exit is not None:
                message = "direct coalition entry must not define a difficulty exit"
                raise ValueError(message)
        else:
            if any(stage.difficulty is None for stage in self.stages):
                message = "area-then-difficulty entry requires a difficulty asset for every stage"
                raise ValueError(message)
            if self.preparation.difficulty_exit is None:
                message = "area-then-difficulty entry requires a difficulty exit"
                raise ValueError(message)

    def stage_assets(self, stage_id: CoalitionStageId) -> CoalitionStageAssets:
        if not isinstance(stage_id, CoalitionStageId):
            message = "stage_id must be a CoalitionStageId"
            raise TypeError(message)
        for assets in self.stages:
            if assets.stage_id == stage_id:
                return assets
        message = f"coalition profile {self.profile_id.value} has no assets for stage {stage_id.value}"
        raise LookupError(message)

    def validate_definition(self, definition: CoalitionDefinition) -> None:
        if not isinstance(definition, CoalitionDefinition):
            message = "definition must be a CoalitionDefinition"
            raise TypeError(message)
        if definition.profile_id != self.profile_id:
            message = (
                f"coalition definition profile {definition.profile_id.value} does not match "
                f"client profile {self.profile_id.value}"
            )
            raise ValueError(message)
        content_stage_ids = {stage.stage_id for stage in definition.stages}
        client_stage_ids = {stage.stage_id for stage in self.stages}
        if content_stage_ids != client_stage_ids:
            missing = sorted(stage.value for stage in content_stage_ids - client_stage_ids)
            extra = sorted(stage.value for stage in client_stage_ids - content_stage_ids)
            message = f"coalition profile {self.profile_id.value} stage mismatch: missing={missing}, extra={extra}"
            raise ValueError(message)


@dataclass(frozen=True, slots=True)
class CoalitionClientSession:
    activity: CoalitionActivity
    profile: CoalitionClientProfile
    stage: CoalitionStageDefinition
    fleet: CoalitionFleetMode

    def __post_init__(self) -> None:
        if not isinstance(self.activity, CoalitionActivity):
            message = "activity must be a CoalitionActivity"
            raise TypeError(message)
        if not isinstance(self.profile, CoalitionClientProfile):
            message = "profile must be a CoalitionClientProfile"
            raise TypeError(message)
        if not isinstance(self.stage, CoalitionStageDefinition):
            message = "stage must be a CoalitionStageDefinition"
            raise TypeError(message)
        if not isinstance(self.fleet, CoalitionFleetMode):
            message = "fleet must be a CoalitionFleetMode"
            raise TypeError(message)
        self.profile.validate_definition(self.activity.definition)
        selected_stage = self.activity.definition.get_stage(self.stage.stage_id)
        if selected_stage != self.stage:
            message = "stage must belong to the selected coalition activity"
            raise ValueError(message)
        if not self.stage.fleet_rule.allows(self.fleet):
            message = "fleet must satisfy the selected coalition stage rule"
            raise ValueError(message)
        self.profile.stage_assets(self.stage.stage_id)


class UnknownCoalitionProfileError(LookupError):
    pass


class CoalitionClientProfileRegistry:
    __slots__ = ("_profiles",)

    def __init__(self, profiles: Iterable[CoalitionClientProfile]) -> None:
        if not isinstance(profiles, Iterable):
            message = "profiles must be iterable"
            raise TypeError(message)
        indexed: dict[CoalitionProfileId, CoalitionClientProfile] = {}
        for profile in profiles:
            if not isinstance(profile, CoalitionClientProfile):
                message = "profiles must contain CoalitionClientProfile values"
                raise TypeError(message)
            if profile.profile_id in indexed:
                message = f"duplicate coalition client profile: {profile.profile_id.value}"
                raise ValueError(message)
            indexed[profile.profile_id] = profile
        self._profiles = MappingProxyType(indexed)

    @property
    def profile_ids(self) -> frozenset[CoalitionProfileId]:
        return frozenset(self._profiles)

    def resolve_profile(self, profile_id: CoalitionProfileId) -> CoalitionClientProfile:
        if not isinstance(profile_id, CoalitionProfileId):
            message = "profile_id must be a CoalitionProfileId"
            raise TypeError(message)
        try:
            return self._profiles[profile_id]
        except KeyError:
            message = f"unknown coalition client profile: {profile_id.value}"
            raise UnknownCoalitionProfileError(message) from None

    def resolve(
        self,
        activity: CoalitionActivity,
        stage_id: CoalitionStageId,
        fleet: CoalitionFleetMode,
    ) -> CoalitionClientSession:
        if not isinstance(activity, CoalitionActivity):
            message = "activity must be a CoalitionActivity"
            raise TypeError(message)
        if not isinstance(stage_id, CoalitionStageId):
            message = "stage_id must be a CoalitionStageId"
            raise TypeError(message)
        if not isinstance(fleet, CoalitionFleetMode):
            message = "fleet must be a CoalitionFleetMode"
            raise TypeError(message)
        profile = self.resolve_profile(activity.definition.profile_id)
        profile.validate_definition(activity.definition)
        stage = activity.definition.get_stage(stage_id)
        if stage is None:
            message = f"coalition activity {activity.content_id.value} has no stage {stage_id.value}"
            raise LookupError(message)
        return CoalitionClientSession(activity, profile, stage, fleet)


def _stage(stage_id: str, entrance: Button, difficulty: Button | None = None) -> CoalitionStageAssets:
    return CoalitionStageAssets(CoalitionStageId(stage_id), entrance, difficulty)


FROSTFALL_COALITION_PROFILE = CoalitionClientProfile(
    profile_id=CoalitionProfileId("frostfall"),
    mode_driver=CoalitionModeDriver.STANDARD,
    entry_strategy=CoalitionEntryStrategy.DIRECT,
    pt_ocr=CoalitionPtOcrProfile(
        coalition_assets.FROSTFALL_OCR_PT,
        CoalitionPtOcrStrategy.PLAIN,
        letter=(198, 158, 82),
        threshold=128,
    ),
    oil_read_location=CoalitionOilReadLocation.COALITION,
    mode_switch=CoalitionModeSwitchAssets(
        coalition_assets.FROSTFALL_MODE_STORY,
        coalition_assets.FROSTFALL_MODE_BATTLE,
    ),
    fleet_switch=CoalitionFleetSwitchAssets(
        coalition_assets.FROSTFALL_SWITCH_SINGLE,
        coalition_assets.FROSTFALL_SWITCH_MULTI,
    ),
    preparation=CoalitionPreparationAssets(
        coalition_assets.FROSTFALL_FLEET_PREPARATION,
        coalition_assets.NEONCITY_PREPARATION_EXIT,
    ),
    stages=(
        _stage("tc1", coalition_assets.FROSTFALL_TC1),
        _stage("tc2", coalition_assets.FROSTFALL_TC2),
        _stage("tc3", coalition_assets.FROSTFALL_TC3),
        _stage("sp", coalition_assets.FROSTFALL_SP),
        _stage("ex", coalition_assets.FROSTFALL_EX),
    ),
)

ACADEMY_COALITION_PROFILE = CoalitionClientProfile(
    profile_id=CoalitionProfileId("academy"),
    mode_driver=CoalitionModeDriver.STANDARD,
    entry_strategy=CoalitionEntryStrategy.DIRECT,
    pt_ocr=CoalitionPtOcrProfile(
        coalition_assets.ACADEMY_PT_OCR,
        CoalitionPtOcrStrategy.AFTER_COLON,
        letter=(255, 255, 255),
        threshold=128,
        alphabet="0123456789IDSB:",
    ),
    oil_read_location=CoalitionOilReadLocation.COALITION,
    mode_switch=CoalitionModeSwitchAssets(
        coalition_assets.ACADEMY_MODE_BATTLE,
        coalition_assets.ACADEMY_MODE_STORY,
    ),
    fleet_switch=CoalitionFleetSwitchAssets(
        coalition_assets.ACADEMY_SWITCH_SINGLE,
        coalition_assets.ACADEMY_SWITCH_MULTI,
    ),
    preparation=CoalitionPreparationAssets(
        coalition_assets.ACEDEMY_FLEET_PREPARATION,
        coalition_assets.NEONCITY_PREPARATION_EXIT,
    ),
    stages=(
        _stage("easy", coalition_assets.ACADEMY_EASY),
        _stage("normal", coalition_assets.ACADEMY_NORMAL),
        _stage("hard", coalition_assets.ACADEMY_HARD),
        _stage("sp", coalition_assets.ACADEMY_SP),
        _stage("ex", coalition_assets.ACADEMY_EX),
    ),
)

NEONCITY_COALITION_PROFILE = CoalitionClientProfile(
    profile_id=CoalitionProfileId("neoncity"),
    mode_driver=CoalitionModeDriver.RED_TEXT,
    entry_strategy=CoalitionEntryStrategy.DIRECT,
    pt_ocr=CoalitionPtOcrProfile(
        coalition_assets.NEONCITY_PT_OCR,
        CoalitionPtOcrStrategy.PLAIN,
        letter=(208, 208, 208),
        threshold=128,
        language="cnocr",
    ),
    oil_read_location=CoalitionOilReadLocation.COALITION,
    mode_switch=CoalitionModeSwitchAssets(
        coalition_assets.NEONCITY_MODE_STORY,
        coalition_assets.NEONCITY_MODE_BATTLE,
    ),
    fleet_switch=CoalitionFleetSwitchAssets(
        coalition_assets.NEONCITY_SWITCH_SINGLE,
        coalition_assets.NEONCITY_SWITCH_MULTI,
    ),
    preparation=CoalitionPreparationAssets(
        coalition_assets.NEONCITY_FLEET_PREPARATION,
        coalition_assets.NEONCITY_PREPARATION_EXIT,
    ),
    stages=(
        _stage("easy", coalition_assets.NEONCITY_EASY),
        _stage("normal", coalition_assets.NEONCITY_NORMAL),
        _stage("hard", coalition_assets.NEONCITY_HARD),
        _stage("sp", coalition_assets.NEONCITY_SP),
        _stage("ex", coalition_assets.NEONCITY_EX),
    ),
)

DAL_COALITION_PROFILE = CoalitionClientProfile(
    profile_id=CoalitionProfileId("dal"),
    mode_driver=CoalitionModeDriver.NONE,
    entry_strategy=CoalitionEntryStrategy.AREA_THEN_DIFFICULTY,
    pt_ocr=CoalitionPtOcrProfile(
        coalition_assets.DAL_PT_OCR,
        CoalitionPtOcrStrategy.AFTER_X,
        letter=(255, 213, 69),
        threshold=128,
        alphabet="0123456789IDSBX",
    ),
    oil_read_location=CoalitionOilReadLocation.COALITION,
    mode_switch=None,
    fleet_switch=CoalitionFleetSwitchAssets(
        coalition_assets.DAL_SWITCH_SINGLE,
        coalition_assets.DAL_SWITCH_MULTI,
    ),
    preparation=CoalitionPreparationAssets(
        coalition_assets.DAL_FLEET_PREPARATION,
        coalition_assets.NEONCITY_PREPARATION_EXIT,
        difficulty_exit=coalition_assets.DAL_DIFFICULTY_EXIT,
    ),
    stages=tuple(
        _stage(f"area{area}-{difficulty}", entrance, button)
        for area, entrance in enumerate(
            (
                coalition_assets.DAL_AREA1,
                coalition_assets.DAL_AREA2,
                coalition_assets.DAL_AREA3,
                coalition_assets.DAL_AREA4,
                coalition_assets.DAL_AREA5,
                coalition_assets.DAL_AREA6,
            ),
            start=1,
        )
        for difficulty, button in (
            ("normal", coalition_assets.DAL_NORMAL),
            ("hard", coalition_assets.DAL_HARD),
        )
    ),
)

FASHION_COALITION_PROFILE = CoalitionClientProfile(
    profile_id=CoalitionProfileId("fashion"),
    mode_driver=CoalitionModeDriver.STANDARD,
    entry_strategy=CoalitionEntryStrategy.DIRECT,
    pt_ocr=CoalitionPtOcrProfile(
        coalition_assets.FASHION_PT_OCR,
        CoalitionPtOcrStrategy.PLAIN,
        letter=(41, 40, 40),
        threshold=128,
    ),
    oil_read_location=CoalitionOilReadLocation.CAMPAIGN_MENU,
    mode_switch=CoalitionModeSwitchAssets(
        coalition_assets.FASHION_MODE_STORY,
        coalition_assets.FASHION_MODE_BATTLE,
    ),
    fleet_switch=CoalitionFleetSwitchAssets(
        coalition_assets.FASHION_SWITCH_SINGLE,
        coalition_assets.FASHION_SWITCH_MULTI,
    ),
    preparation=CoalitionPreparationAssets(
        # FASHION 的准备页模板与 NEONCITY 相同，只由 profile 复用资产。
        coalition_assets.NEONCITY_FLEET_PREPARATION,
        coalition_assets.NEONCITY_PREPARATION_EXIT,
    ),
    stages=(
        _stage("easy", coalition_assets.FASHION_EASY),
        _stage("normal", coalition_assets.FASHION_NORMAL),
        _stage("hard", coalition_assets.FASHION_HARD),
        _stage("sp", coalition_assets.FASHION_SP),
        _stage("ex", coalition_assets.FASHION_EX),
    ),
)

COALITION_CLIENT_PROFILES = CoalitionClientProfileRegistry(
    (
        FROSTFALL_COALITION_PROFILE,
        ACADEMY_COALITION_PROFILE,
        NEONCITY_COALITION_PROFILE,
        DAL_COALITION_PROFILE,
        FASHION_COALITION_PROFILE,
    )
)
