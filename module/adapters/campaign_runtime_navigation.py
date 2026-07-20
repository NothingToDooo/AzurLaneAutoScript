from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import cast

from module.base.button import Button
from module.campaign.assets import SWITCH_20241219_COMBAT, SWITCH_20241219_STORY
from module.campaign.campaign_ui import ModeSwitch
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue

from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
)

_DREAMWAKER_BALL = Button(
    area=(571, 283, 696, 387),
    color=(),
    button=(597, 274, 671, 343),
    name="DREAMWAKER_BALL",
)
_CONFLUENCE_BALL = Button(
    area=(589, 279, 685, 374),
    color=(),
    button=(589, 279, 685, 374),
    name="CONFLUENCE_BALL",
)
_BALL_ASSETS = {
    "DREAMWAKER_BALL": _DREAMWAKER_BALL,
    "CONFLUENCE_BALL": _CONFLUENCE_BALL,
}


class CampaignRouteTarget(StrEnum):
    ALL = "all"
    EVENT = "event"
    SP = "sp"
    SWITCH_20241219 = "switch_20241219"


class CampaignRouteDestination(StrEnum):
    CAMPAIGN = "campaign"
    EVENT = "event"
    SP = "sp"


class CampaignRouteMode(StrEnum):
    REQUESTED = "requested"
    NORMAL = "normal"
    HARD = "hard"
    EX = "ex"
    UNCHANGED = "unchanged"
    COMBAT = "combat"


class CampaignModePolicyKind(StrEnum):
    INHERITED = "inherited"
    NOOP = "noop"
    BRIDGE_20241219 = "bridge_20241219"
    HARD_CONFIG_OVERRIDE = "hard_config_override"


class CampaignBallOperation(StrEnum):
    SET_BALL = "set_ball"
    ENSURE_MODE = "ensure_mode"


def _mapping(value: RuntimeTuningValue, name: str) -> Mapping[str, RuntimeTuningValue]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        message = f"navigation option {name} must be an object"
        raise CampaignRuntimeProfileError(message)
    return cast("Mapping[str, RuntimeTuningValue]", value)


def _sequence(value: RuntimeTuningValue, name: str) -> tuple[RuntimeTuningValue, ...]:
    if not isinstance(value, tuple):
        message = f"navigation option {name} must be a list"
        raise CampaignRuntimeProfileError(message)
    return cast("tuple[RuntimeTuningValue, ...]", value)


def _strings(value: RuntimeTuningValue, name: str) -> tuple[str, ...]:
    values = _sequence(value, name)
    if any(not isinstance(item, str) or not item for item in values):
        message = f"navigation option {name} must contain non-empty strings"
        raise CampaignRuntimeProfileError(message)
    return cast("tuple[str, ...]", values)


def _optional_strings(
    values: Mapping[str, RuntimeTuningValue],
    name: str,
) -> frozenset[str] | None:
    value = values.get(name)
    return None if value is None else frozenset(_strings(value, name))


def _string(value: RuntimeTuningValue, name: str) -> str:
    if not isinstance(value, str) or not value:
        message = f"navigation option {name} must be a non-empty string"
        raise CampaignRuntimeProfileError(message)
    return value


def _optional_string(
    values: Mapping[str, RuntimeTuningValue],
    name: str,
) -> str | None:
    value = values.get(name)
    return None if value is None else _string(value, name)


def _number(value: RuntimeTuningValue, name: str) -> float:
    if type(value) not in (int, float):
        message = f"navigation option {name} must be a number"
        raise CampaignRuntimeProfileError(message)
    return float(cast("int | float", value))


def _integer_mapping(value: RuntimeTuningValue, name: str) -> Mapping[str, int]:
    values = _mapping(value, name)
    if any(type(item) is not int or item < 0 for item in values.values()):
        message = f"navigation option {name} must map names to non-negative integers"
        raise CampaignRuntimeProfileError(message)
    return MappingProxyType(dict(cast("Mapping[str, int]", values)))


def _string_mapping(value: RuntimeTuningValue, name: str) -> Mapping[str, str]:
    values = _mapping(value, name)
    if any(not isinstance(item, str) or not item for item in values.values()):
        message = f"navigation option {name} must map names to non-empty strings"
        raise CampaignRuntimeProfileError(message)
    return MappingProxyType(dict(cast("Mapping[str, str]", values)))


@dataclass(frozen=True, slots=True)
class CampaignNameRule:
    names: frozenset[str] | None
    contains: str | None
    prefix: str | None
    split_on_hyphen: bool
    require_digit_suffix: bool
    chapter: str | None
    stage: str | None

    @classmethod
    def from_options(
        cls,
        values: Mapping[str, RuntimeTuningValue],
        name: str,
    ) -> CampaignNameRule:
        split = values.get("split")
        if split not in {None, "-"}:
            message = f"navigation option {name}.split must be '-'"
            raise CampaignRuntimeProfileError(message)
        suffix = values.get("suffix")
        if suffix not in {None, "digit"}:
            message = f"navigation option {name}.suffix must be 'digit'"
            raise CampaignRuntimeProfileError(message)
        chapter = _optional_string(values, "chapter")
        stage = _optional_string(values, "stage")
        if split is None and (chapter is None or stage is None):
            message = f"navigation option {name} must define chapter and stage"
            raise CampaignRuntimeProfileError(message)
        return cls(
            _optional_strings(values, "names"),
            _optional_string(values, "contains"),
            _optional_string(values, "prefix"),
            split == "-",
            suffix == "digit",
            chapter,
            stage,
        )

    def matches(self, name: str) -> bool:
        if self.names is not None and name not in self.names:
            return False
        if self.contains is not None and self.contains not in name:
            return False
        if self.prefix is not None and not name.startswith(self.prefix):
            return False
        return not self.require_digit_suffix or name[-1:].isdigit()

    def separate(self, name: str) -> tuple[str, str] | None:
        if not self.matches(name):
            return None
        if self.split_on_hyphen:
            if "-" not in name:
                return None
            return cast("tuple[str, str]", tuple(name.split("-", maxsplit=1)))
        if self.chapter is None or self.stage is None:
            message = "compiled campaign name rule is incomplete"
            raise AssertionError(message)
        chapter = name[:-1] if self.chapter == "prefix" else self.chapter
        stage = name[-1] if self.stage == "last" else self.stage
        return chapter, stage


@dataclass(frozen=True, slots=True)
class CampaignEntranceSearch:
    input_name: str
    contains: str

    @classmethod
    def from_options(cls, value: RuntimeTuningValue) -> CampaignEntranceSearch | None:
        values = _mapping(value, "entrance_search")
        if not values:
            return None
        field = _string(values.get("field"), "entrance_search.field")
        if field != "stage_entrance":
            message = f"unsupported navigation entrance search field: {field}"
            raise CampaignRuntimeProfileError(message)
        return cls(
            _string(values.get("input"), "entrance_search.input"),
            _string(values.get("contains"), "entrance_search.contains").lower(),
        )


@dataclass(frozen=True, slots=True)
class CampaignModePolicy:
    kind: CampaignModePolicyKind
    hard_config_override: bool

    @classmethod
    def from_options(cls, value: RuntimeTuningValue) -> CampaignModePolicy:
        if isinstance(value, str):
            try:
                kind = CampaignModePolicyKind(value)
            except ValueError:
                message = f"unsupported navigation mode policy: {value}"
                raise CampaignRuntimeProfileError(message) from None
            if kind not in {CampaignModePolicyKind.INHERITED, CampaignModePolicyKind.NOOP}:
                message = f"navigation mode policy {value} requires an object"
                raise CampaignRuntimeProfileError(message)
            return cls(kind, hard_config_override=True)
        values = _mapping(value, "mode_policy")
        kind_value = _string(values.get("kind"), "mode_policy.kind")
        try:
            kind = CampaignModePolicyKind(kind_value)
        except ValueError:
            message = f"unsupported navigation mode policy kind: {kind_value}"
            raise CampaignRuntimeProfileError(message) from None
        if kind not in {
            CampaignModePolicyKind.BRIDGE_20241219,
            CampaignModePolicyKind.HARD_CONFIG_OVERRIDE,
        }:
            message = f"navigation mode policy kind {kind_value} cannot use object options"
            raise CampaignRuntimeProfileError(message)
        override = values.get("hard_config_override", True)
        if type(override) is not bool:
            message = "navigation hard_config_override must be a boolean"
            raise CampaignRuntimeProfileError(message)
        return cls(kind, override)


@dataclass(frozen=True, slots=True)
class CampaignRoute:
    destination: CampaignRouteDestination
    mode: CampaignRouteMode
    match_all: bool
    match_numeric: bool
    chapters: frozenset[str] | None
    prefix: str | None
    requires_chapter_switch: bool
    reselect_after_hard: bool
    hard_if_campaign_name_is_hard: bool
    aside: str | None
    aside_by_stage: tuple[tuple[frozenset[str], str], ...]

    @classmethod
    def from_options(
        cls,
        values: Mapping[str, RuntimeTuningValue],
        name: str,
    ) -> CampaignRoute:
        destination_value = _string(values.get("destination"), f"{name}.destination")
        mode_value = _string(values.get("mode"), f"{name}.mode")
        try:
            destination = CampaignRouteDestination(destination_value)
            mode = CampaignRouteMode(mode_value)
        except ValueError as error:
            message = f"unsupported navigation route value in {name}: {error}"
            raise CampaignRuntimeProfileError(message) from None
        match = values.get("match")
        if match not in {None, "*", "numeric"}:
            message = f"unsupported navigation route match: {match!r}"
            raise CampaignRuntimeProfileError(message)
        guard = values.get("guard")
        if guard not in {None, "MAP_CHAPTER_SWITCH_20241219"}:
            message = f"unsupported navigation route guard: {guard!r}"
            raise CampaignRuntimeProfileError(message)
        reselect = values.get("reselect_after_hard", False)
        if type(reselect) is not bool:
            message = f"navigation option {name}.reselect_after_hard must be a boolean"
            raise CampaignRuntimeProfileError(message)
        hard_if = values.get("hard_if")
        if hard_if not in {None, "campaign_name_is_hard"}:
            message = f"unsupported navigation route hard_if: {hard_if!r}"
            raise CampaignRuntimeProfileError(message)
        aside_by_stage_value = values.get("aside_by_stage")
        aside_by_stage = ()
        if aside_by_stage_value is not None:
            aside_by_stage = tuple(
                (frozenset(stages.split(",")), aside)
                for stages, aside in _string_mapping(aside_by_stage_value, f"{name}.aside_by_stage").items()
            )
        return cls(
            destination,
            mode,
            match == "*",
            match == "numeric",
            _optional_strings(values, "chapters"),
            _optional_string(values, "prefix"),
            guard == "MAP_CHAPTER_SWITCH_20241219",
            reselect,
            hard_if == "campaign_name_is_hard",
            _optional_string(values, "aside"),
            aside_by_stage,
        )


@dataclass(frozen=True, slots=True)
class ChapterRouteNavigationPlan:
    chapter_indices: Mapping[str, int]
    name_rules: tuple[CampaignNameRule, ...]
    entrance_aliases: Mapping[str, str]
    entrance_search: CampaignEntranceSearch | None
    ocr_aliases: Mapping[str, str]
    routes: tuple[CampaignRoute, ...]
    route_target: CampaignRouteTarget | None
    mode_policy: CampaignModePolicy
    stage_match_similarity: float | None


@dataclass(frozen=True, slots=True)
class CampaignBallStatusRule:
    chapters: frozenset[str] | None
    stages: frozenset[str]


@dataclass(frozen=True, slots=True)
class BallChapterNavigationPlan:
    chapter_indices: Mapping[str, int]
    event_modes: Mapping[str, str]
    sp_destination: CampaignRouteDestination
    ball: Button
    ball_chapters: frozenset[str]
    normal_chapters: frozenset[str]
    hard_chapters: frozenset[str]
    blue_rules: tuple[CampaignBallStatusRule, ...]
    operation_order: tuple[CampaignBallOperation, CampaignBallOperation]
    detected_colors: Mapping[str, str]
    click_wait_seconds: float


@dataclass(frozen=True, slots=True)
class Event20240912NavigationPlan:
    mode_switch: ModeSwitch


type CampaignNavigationPlan = ChapterRouteNavigationPlan | BallChapterNavigationPlan | Event20240912NavigationPlan


class CampaignNavigationPlanExecutor(RuntimeExecutorInstance):
    """profile manager 生命周期内持有一份已验证的最终 navigation plan。"""

    __slots__ = ("plan",)

    def __init__(self, plan: CampaignNavigationPlan) -> None:
        self.plan = plan
        super().__init__({RuntimeExecutorKind.NAVIGATION})


def _rules(value: RuntimeTuningValue, name: str) -> tuple[Mapping[str, RuntimeTuningValue], ...]:
    return tuple(_mapping(item, f"{name}[{index}]") for index, item in enumerate(_sequence(value, name)))


def _route_target(value: RuntimeTuningValue) -> CampaignRouteTarget | None:
    if value is None:
        return None
    raw = _string(value, "route_target")
    try:
        return CampaignRouteTarget(raw)
    except ValueError:
        message = f"unsupported navigation route target: {raw}"
        raise CampaignRuntimeProfileError(message) from None


def _build_chapter_route_plan(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.NAVIGATION)
    similarity = options["stage_match_similarity"]
    plan = ChapterRouteNavigationPlan(
        _integer_mapping(options["chapter_indices"], "chapter_indices"),
        tuple(
            CampaignNameRule.from_options(rule, f"name_rules[{index}]")
            for index, rule in enumerate(_rules(options["name_rules"], "name_rules"))
        ),
        _string_mapping(options["entrance_aliases"], "entrance_aliases"),
        CampaignEntranceSearch.from_options(options["entrance_search"]),
        _string_mapping(options["ocr_aliases"], "ocr_aliases"),
        tuple(
            CampaignRoute.from_options(route, f"routes[{index}]")
            for index, route in enumerate(_rules(options["routes"], "routes"))
        ),
        _route_target(options["route_target"]),
        CampaignModePolicy.from_options(options["mode_policy"]),
        None if similarity is None else _number(similarity, "stage_match_similarity"),
    )
    if plan.route_target is None and plan.routes:
        message = "navigation routes require a typed route_target"
        raise CampaignRuntimeProfileError(message)
    if plan.route_target is not None and not plan.routes:
        message = "navigation route_target requires at least one route"
        raise CampaignRuntimeProfileError(message)
    return CampaignNavigationPlanExecutor(plan)


def _ball_status_rules(value: RuntimeTuningValue) -> tuple[CampaignBallStatusRule, ...]:
    return tuple(
        CampaignBallStatusRule(
            _optional_strings(rule, "chapters"),
            frozenset(_strings(rule["stages"], f"ball.blue_rules[{index}].stages")),
        )
        for index, rule in enumerate(_rules(value, "ball.blue_rules"))
    )


def _build_ball_chapter_route(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.NAVIGATION)
    sp_destination_value = _string(options["sp_destination"], "sp_destination")
    if sp_destination_value not in {CampaignRouteDestination.EVENT, CampaignRouteDestination.SP}:
        message = f"unsupported ball SP destination: {sp_destination_value}"
        raise CampaignRuntimeProfileError(message)
    ball = _mapping(options["ball"], "ball")
    asset = _string(ball["asset"], "ball.asset")
    try:
        ball_button = _BALL_ASSETS[asset]
    except KeyError:
        message = f"unsupported campaign ball asset: {asset}"
        raise CampaignRuntimeProfileError(message) from None
    operation_values = _strings(ball["operation_order"], "ball.operation_order")
    try:
        operation_order = tuple(CampaignBallOperation(value) for value in operation_values)
    except ValueError as error:
        message = f"unsupported campaign ball operation: {error}"
        raise CampaignRuntimeProfileError(message) from None
    if set(operation_order) != set(CampaignBallOperation) or len(operation_order) != 2:
        message = "ball operation_order must contain set_ball and ensure_mode exactly once"
        raise CampaignRuntimeProfileError(message)
    click_wait_seconds = _number(ball["click_wait_seconds"], "ball.click_wait_seconds")
    if click_wait_seconds < 0:
        message = "ball click_wait_seconds must be non-negative"
        raise CampaignRuntimeProfileError(message)
    plan = BallChapterNavigationPlan(
        _integer_mapping(options["chapter_indices"], "chapter_indices"),
        _string_mapping(options["event_modes"], "event_modes"),
        CampaignRouteDestination(sp_destination_value),
        ball_button,
        frozenset(_strings(ball["chapters"], "ball.chapters")),
        frozenset(_strings(ball["normal_chapters"], "ball.normal_chapters")),
        frozenset(_strings(ball["hard_chapters"], "ball.hard_chapters")),
        _ball_status_rules(ball["blue_rules"]),
        operation_order,
        _string_mapping(ball["detected_colors"], "ball.detected_colors"),
        click_wait_seconds,
    )
    return CampaignNavigationPlanExecutor(plan)


def _build_event_20240912_navigation(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    options = context.options(RuntimeExecutorKind.NAVIGATION)
    if options["mode_switch"] != "event_20240912":
        message = "event 20240912 navigation requires its typed mode switch"
        raise CampaignRuntimeProfileError(message)
    mode_switch = ModeSwitch("Mode_switch_20240912", is_selector=True)
    mode_switch.add_state("combat", SWITCH_20241219_COMBAT, offset=(444, 4))
    mode_switch.add_state("story", SWITCH_20241219_STORY, offset=(444, 4))
    return CampaignNavigationPlanExecutor(Event20240912NavigationPlan(mode_switch))


def navigation_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("navigation/chapter_route_plan"),
            {
                RuntimeExecutorKind.NAVIGATION: RuntimeExecutorOptionsSchema(
                    required=frozenset(
                        {
                            "chapter_indices",
                            "name_rules",
                            "entrance_aliases",
                            "entrance_search",
                            "ocr_aliases",
                            "routes",
                            "route_target",
                            "mode_policy",
                            "stage_match_similarity",
                        }
                    )
                )
            },
            _build_chapter_route_plan,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("navigation/ball_chapter_route"),
            {
                RuntimeExecutorKind.NAVIGATION: RuntimeExecutorOptionsSchema(
                    required=frozenset(
                        {
                            "chapter_indices",
                            "event_modes",
                            "sp_destination",
                            "ball",
                        }
                    )
                )
            },
            _build_ball_chapter_route,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("event_20240912_cn/campaign_base/campaign_base"),
            {
                RuntimeExecutorKind.NAVIGATION: RuntimeExecutorOptionsSchema(
                    required=frozenset({"mode_switch"}),
                )
            },
            _build_event_20240912_navigation,
        ),
    )
