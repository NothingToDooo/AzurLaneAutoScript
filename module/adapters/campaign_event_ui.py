from dataclasses import dataclass
from functools import partial
from typing import TYPE_CHECKING, Protocol, override, runtime_checkable

from module.campaign.campaign_engine import CampaignEngine
from module.campaign.event_destination import STANDARD_EVENT_DESTINATION, EventDestination
from module.combat.combat_result_ui import (
    STANDARD_COMBAT_RESULT_UI,
    CombatResultRuntime,
    CombatResultUi,
)
from module.content.errors import ContentValidationError
from module.content.runtime_profile import RuntimeExecutorKind
from module.handler.map_transition_ui import (
    STANDARD_MAP_TRANSITION_ANIMATION,
    STANDARD_MAP_TRANSITION_UI,
    MapTransitionAnimation,
    MapTransitionCombatRuntime,
    MapTransitionRuntime,
    MapTransitionUi,
    WaitableMapTransitionAnimation,
)

from .campaign_runtime_profile import CampaignRuntimeProfileError, RuntimeExecutorInstance

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


class EventStageRecovery(Protocol):
    """关卡选择循环中的活动页面恢复能力。"""

    def recover_campaign_selection(self, runtime: CampaignEngine) -> bool: ...

    def recover_chapter_selection(self, runtime: CampaignEngine) -> bool: ...

    def recover_stage_page(self, runtime: CampaignEngine) -> bool: ...


type EventStageRecoveryNext = Callable[[CampaignEngine], bool]
type EventStageRecoveryHandler = Callable[[CampaignEngine, EventStageRecoveryNext], bool]
type EventCombatResultNext = Callable[[CombatResultRuntime], bool]
type EventCombatResultHandler = Callable[[CombatResultRuntime, EventCombatResultNext], bool]
type MapTransitionNext = Callable[[MapTransitionRuntime], bool]
type MapTransitionHandler = Callable[[MapTransitionRuntime, MapTransitionNext], bool]


@dataclass(frozen=True, slots=True)
class CampaignEventStageRecoveryContributor:
    recover_campaign_selection: EventStageRecoveryHandler | None = None
    recover_chapter_selection: EventStageRecoveryHandler | None = None
    recover_stage_page: EventStageRecoveryHandler | None = None


@dataclass(frozen=True, slots=True)
class CampaignEventCombatResultContributor:
    handle_experience_result: EventCombatResultHandler | None = None


@dataclass(frozen=True, slots=True)
class CampaignMapTransitionContributor:
    handle_stage_return: MapTransitionHandler | None = None
    stage_page_ready: MapTransitionHandler | None = None
    animation: MapTransitionAnimation | None = None
    event_animation_end_battle: int | None = None


@dataclass(frozen=True, slots=True)
class CampaignEventUiContributor:
    """一个 runtime executor 对活动 UI typed services 的贡献。"""

    destination: EventDestination | None = None
    stage_recovery: CampaignEventStageRecoveryContributor | None = None
    combat_result: CampaignEventCombatResultContributor | None = None
    map_transition: CampaignMapTransitionContributor | None = None


@runtime_checkable
class CampaignEventUiContributorSource(Protocol):
    @property
    def event_ui_contributor(self) -> CampaignEventUiContributor: ...


class CampaignEventUiExecutor(RuntimeExecutorInstance):
    """提供 typed event UI，并允许同一 owner 暴露其他 typed facet。"""

    __slots__ = ("_event_ui_contributor",)

    def __init__(
        self,
        supported_kinds: Iterable[RuntimeExecutorKind],
        contributor: CampaignEventUiContributor,
    ) -> None:
        kinds = frozenset(supported_kinds)
        if RuntimeExecutorKind.EVENT_UI not in kinds:
            message = "campaign event UI executor requires the event_ui kind"
            raise ContentValidationError(message)
        if not isinstance(contributor, CampaignEventUiContributor):
            message = "campaign event UI executor requires a typed contributor"
            raise TypeError(message)
        super().__init__(kinds)
        self._event_ui_contributor = contributor

    @property
    def event_ui_contributor(self) -> CampaignEventUiContributor:
        return self._event_ui_contributor


@dataclass(frozen=True, slots=True)
class CampaignEventUiServices:
    """每个 runtime 只编译一次的活动 UI 能力集合。"""

    destination: EventDestination
    stage_recovery: EventStageRecovery
    combat_result: CombatResultUi
    map_transition: MapTransitionUi


class _StandardEventStageRecovery(EventStageRecovery):
    @override
    def recover_campaign_selection(self, runtime: CampaignEngine) -> bool:
        return bool(CampaignEngine.handle_campaign_ui_additional(runtime))

    @override
    def recover_chapter_selection(self, runtime: CampaignEngine) -> bool:
        del runtime
        return bool(CampaignEngine.handle_chapter_additional())

    @override
    def recover_stage_page(self, runtime: CampaignEngine) -> bool:
        return bool(CampaignEngine.handle_get_chapter_additional(runtime))


@dataclass(frozen=True, slots=True)
class _ComposedEventStageRecovery(EventStageRecovery):
    recover_campaign_selection_handler: EventStageRecoveryNext
    recover_chapter_selection_handler: EventStageRecoveryNext
    recover_stage_page_handler: EventStageRecoveryNext

    @override
    def recover_campaign_selection(self, runtime: CampaignEngine) -> bool:
        return self.recover_campaign_selection_handler(runtime)

    @override
    def recover_chapter_selection(self, runtime: CampaignEngine) -> bool:
        return self.recover_chapter_selection_handler(runtime)

    @override
    def recover_stage_page(self, runtime: CampaignEngine) -> bool:
        return self.recover_stage_page_handler(runtime)


@dataclass(frozen=True, slots=True)
class _ComposedCombatResultUi(CombatResultUi):
    handle_experience_result_handler: EventCombatResultNext

    @override
    def handle_experience_result(self, runtime: CombatResultRuntime) -> bool:
        return self.handle_experience_result_handler(runtime)


@dataclass(frozen=True, slots=True)
class _ComposedMapTransitionUi(MapTransitionUi):
    handle_stage_return_handler: MapTransitionNext
    stage_page_ready_handler: MapTransitionNext
    animation: MapTransitionAnimation
    event_animation_end_battle: int | None
    combat_end_waiter: WaitableMapTransitionAnimation | None

    @override
    def handle_stage_return(self, runtime: MapTransitionRuntime) -> bool:
        return self.handle_stage_return_handler(runtime)

    @override
    def stage_page_ready(self, runtime: MapTransitionRuntime) -> bool:
        return self.stage_page_ready_handler(runtime)

    @override
    def event_animation_visible(self, runtime: MapTransitionRuntime) -> bool:
        return self.animation.is_visible(runtime)

    @override
    def combat_end_override(self, runtime: MapTransitionCombatRuntime) -> Callable[[], bool] | None:
        waiter = self.combat_end_waiter
        if self.event_animation_end_battle != runtime.battle_count or waiter is None:
            return None
        return partial(waiter.wait_until_closed, runtime)


def _overlay_recovery(
    handler: EventStageRecoveryHandler,
    next_handler: EventStageRecoveryNext,
) -> EventStageRecoveryNext:
    def execute(runtime: CampaignEngine) -> bool:
        return handler(runtime, next_handler)

    return execute


def _overlay_combat_result(
    handler: EventCombatResultHandler,
    next_handler: EventCombatResultNext,
) -> EventCombatResultNext:
    def execute(runtime: CombatResultRuntime) -> bool:
        return handler(runtime, next_handler)

    return execute


def _overlay_transition(
    handler: MapTransitionHandler,
    next_handler: MapTransitionNext,
) -> MapTransitionNext:
    def execute(runtime: MapTransitionRuntime) -> bool:
        return handler(runtime, next_handler)

    return execute


class _MapTransitionComposition:
    __slots__ = (
        "_animation",
        "_event_animation_end_battle",
        "_handle_stage_return",
        "_stage_page_ready",
    )

    def __init__(self) -> None:
        self._handle_stage_return = STANDARD_MAP_TRANSITION_UI.handle_stage_return
        self._stage_page_ready = STANDARD_MAP_TRANSITION_UI.stage_page_ready
        self._animation = STANDARD_MAP_TRANSITION_ANIMATION
        self._event_animation_end_battle: int | None = None

    def add(self, contributor: CampaignMapTransitionContributor | None) -> None:
        if contributor is None:
            return
        if contributor.handle_stage_return is not None:
            self._handle_stage_return = _overlay_transition(
                contributor.handle_stage_return,
                self._handle_stage_return,
            )
        if contributor.stage_page_ready is not None:
            self._stage_page_ready = _overlay_transition(
                contributor.stage_page_ready,
                self._stage_page_ready,
            )
        if contributor.animation is not None:
            self._animation = contributor.animation
        if contributor.event_animation_end_battle is not None:
            self._event_animation_end_battle = contributor.event_animation_end_battle

    def build(self) -> MapTransitionUi:
        waiter = None
        battle = self._event_animation_end_battle
        if battle is not None:
            animation = self._animation
            if not isinstance(animation, WaitableMapTransitionAnimation):
                message = "event animation expected-end policy requires a typed animation wait provider"
                raise CampaignRuntimeProfileError(message)
            waiter = animation
        return _ComposedMapTransitionUi(
            handle_stage_return_handler=self._handle_stage_return,
            stage_page_ready_handler=self._stage_page_ready,
            animation=self._animation,
            event_animation_end_battle=battle,
            combat_end_waiter=waiter,
        )


def build_campaign_event_ui_services(
    instances: Iterable[object],
) -> CampaignEventUiServices:
    """按 profile 顺序组合能力；destination 后者覆盖，其余能力后者先处理并可续传。"""

    destination = STANDARD_EVENT_DESTINATION
    standard_recovery = _StandardEventStageRecovery()
    recover_campaign_selection = standard_recovery.recover_campaign_selection
    recover_chapter_selection = standard_recovery.recover_chapter_selection
    recover_stage_page = standard_recovery.recover_stage_page
    handle_experience_result = STANDARD_COMBAT_RESULT_UI.handle_experience_result
    map_transition = _MapTransitionComposition()
    for instance in instances:
        if not isinstance(instance, CampaignEventUiContributorSource):
            continue
        contributor = instance.event_ui_contributor
        if contributor.destination is not None:
            destination = contributor.destination
        combat_result = contributor.combat_result
        if combat_result is not None and combat_result.handle_experience_result is not None:
            handle_experience_result = _overlay_combat_result(
                combat_result.handle_experience_result,
                handle_experience_result,
            )
        map_transition.add(contributor.map_transition)
        recovery = contributor.stage_recovery
        if recovery is None:
            continue
        if recovery.recover_campaign_selection is not None:
            recover_campaign_selection = _overlay_recovery(
                recovery.recover_campaign_selection,
                recover_campaign_selection,
            )
        if recovery.recover_chapter_selection is not None:
            recover_chapter_selection = _overlay_recovery(
                recovery.recover_chapter_selection,
                recover_chapter_selection,
            )
        if recovery.recover_stage_page is not None:
            recover_stage_page = _overlay_recovery(
                recovery.recover_stage_page,
                recover_stage_page,
            )
    return CampaignEventUiServices(
        destination=destination,
        stage_recovery=_ComposedEventStageRecovery(
            recover_campaign_selection_handler=recover_campaign_selection,
            recover_chapter_selection_handler=recover_chapter_selection,
            recover_stage_page_handler=recover_stage_page,
        ),
        combat_result=_ComposedCombatResultUi(
            handle_experience_result_handler=handle_experience_result,
        ),
        map_transition=map_transition.build(),
    )
