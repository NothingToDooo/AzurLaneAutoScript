from dataclasses import dataclass
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

from .campaign_runtime_profile import RuntimeExecutorInstance, RuntimeMethod, RuntimeOperation

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable, Mapping


class EventStageRecovery(Protocol):
    """关卡选择循环中的活动页面恢复能力。"""

    def recover_campaign_selection(self, runtime: CampaignEngine) -> bool: ...

    def recover_chapter_selection(self, runtime: CampaignEngine) -> bool: ...

    def recover_stage_page(self, runtime: CampaignEngine) -> bool: ...


type EventStageRecoveryNext = Callable[[CampaignEngine], bool]
type EventStageRecoveryHandler = Callable[[CampaignEngine, EventStageRecoveryNext], bool]
type EventCombatResultNext = Callable[[CombatResultRuntime], bool]
type EventCombatResultHandler = Callable[[CombatResultRuntime, EventCombatResultNext], bool]


@dataclass(frozen=True, slots=True)
class CampaignEventStageRecoveryContributor:
    recover_campaign_selection: EventStageRecoveryHandler | None = None
    recover_chapter_selection: EventStageRecoveryHandler | None = None
    recover_stage_page: EventStageRecoveryHandler | None = None


@dataclass(frozen=True, slots=True)
class CampaignEventCombatResultContributor:
    handle_experience_result: EventCombatResultHandler | None = None


@dataclass(frozen=True, slots=True)
class CampaignEventUiContributor:
    """一个 runtime executor 对活动 UI typed services 的贡献。"""

    destination: EventDestination | None = None
    stage_recovery: CampaignEventStageRecoveryContributor | None = None
    combat_result: CampaignEventCombatResultContributor | None = None


@runtime_checkable
class CampaignEventUiContributorSource(Protocol):
    @property
    def event_ui_contributor(self) -> CampaignEventUiContributor: ...


class CampaignEventUiExecutor(RuntimeExecutorInstance):
    """同时提供 operation facet 与 typed event UI 能力的专用 executor。"""

    __slots__ = ("_event_ui_contributor",)

    def __init__(
        self,
        supported_kinds: Iterable[RuntimeExecutorKind],
        contributor: CampaignEventUiContributor,
        *,
        methods: Mapping[RuntimeExecutorKind, Mapping[RuntimeOperation, RuntimeMethod]] | None = None,
    ) -> None:
        kinds = frozenset(supported_kinds)
        if RuntimeExecutorKind.EVENT_UI not in kinds:
            message = "campaign event UI executor requires the event_ui kind"
            raise ContentValidationError(message)
        if not isinstance(contributor, CampaignEventUiContributor):
            message = "campaign event UI executor requires a typed contributor"
            raise TypeError(message)
        super().__init__(kinds, methods=methods)
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
    )
