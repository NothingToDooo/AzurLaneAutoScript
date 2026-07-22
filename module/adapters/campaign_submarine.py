from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId
from module.logger import logger
from module.map.support_fleet import SupportFleetAttemptState, SupportFleetStateSource

from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
)

if TYPE_CHECKING:
    from module.combat.combat import CombatEnd


class SubmarineSupportPopupRuntime(Protocol):
    def handle_popup_confirm(self, name: str) -> bool: ...


class SubmarineFreshCombatRuntime(Protocol):
    FUNCTION_NAME_BASE: str

    def combat(
        self,
        *,
        balance_hp: bool,
        emotion_reduce: bool,
        expected_end: CombatEnd | None,
    ) -> object: ...


type SubmarineSupportPopupHandler = Callable[[SubmarineSupportPopupRuntime], bool]
type SubmarineFreshCombatHandler = Callable[[SubmarineFreshCombatRuntime], None]


@dataclass(frozen=True, slots=True)
class CampaignSubmarineSupportPopupContributor:
    handler: SubmarineSupportPopupHandler

    def __post_init__(self) -> None:
        if not callable(self.handler):
            message = "campaign submarine popup contributor requires a handler"
            raise TypeError(message)


@runtime_checkable
class CampaignSubmarineSupportPopupContributorSource(Protocol):
    @property
    def submarine_support_popup_contributor(self) -> CampaignSubmarineSupportPopupContributor: ...


@dataclass(frozen=True, slots=True)
class CampaignSubmarineFreshCombatContributor:
    handler: SubmarineFreshCombatHandler

    def __post_init__(self) -> None:
        if not callable(self.handler):
            message = "campaign submarine fresh combat contributor requires a handler"
            raise TypeError(message)


@runtime_checkable
class CampaignSubmarineFreshCombatContributorSource(Protocol):
    @property
    def submarine_fresh_combat_contributor(self) -> CampaignSubmarineFreshCombatContributor: ...


def _ignore_submarine_support_popup(runtime: SubmarineSupportPopupRuntime) -> bool:
    del runtime
    return False


def _ignore_submarine_fresh_combat(runtime: SubmarineFreshCombatRuntime) -> None:
    del runtime


@dataclass(frozen=True, slots=True)
class CampaignSubmarineSupportPopupService:
    handler: SubmarineSupportPopupHandler = _ignore_submarine_support_popup

    def __post_init__(self) -> None:
        if not callable(self.handler):
            message = "campaign submarine popup service requires a handler"
            raise TypeError(message)

    def handle(self, runtime: SubmarineSupportPopupRuntime) -> bool:
        result = self.handler(runtime)
        if type(result) is not bool:
            message = "campaign submarine popup handler must return bool"
            raise CampaignRuntimeProfileError(message)
        return result


@dataclass(frozen=True, slots=True)
class CampaignSubmarineFreshCombatService:
    handler: SubmarineFreshCombatHandler = _ignore_submarine_fresh_combat

    def __post_init__(self) -> None:
        if not callable(self.handler):
            message = "campaign submarine fresh combat service requires a handler"
            raise TypeError(message)

    def start(self, runtime: SubmarineFreshCombatRuntime) -> None:
        result = self.handler(runtime)
        if result is not None:
            message = "campaign submarine fresh combat handler must return None"
            raise CampaignRuntimeProfileError(message)


@dataclass(frozen=True, slots=True)
class CampaignSubmarineServices:
    popup: CampaignSubmarineSupportPopupService = CampaignSubmarineSupportPopupService()
    fresh_combat: CampaignSubmarineFreshCombatService = CampaignSubmarineFreshCombatService()

    def __post_init__(self) -> None:
        if not isinstance(self.popup, CampaignSubmarineSupportPopupService):
            message = "campaign submarine services require a typed popup service"
            raise TypeError(message)
        if not isinstance(self.fresh_combat, CampaignSubmarineFreshCombatService):
            message = "campaign submarine services require a typed fresh combat service"
            raise TypeError(message)


STANDARD_CAMPAIGN_SUBMARINE_SERVICES = CampaignSubmarineServices()


class SubmarineSupportPopupExecutor(RuntimeExecutorInstance):
    __slots__ = ("_contributor",)

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        _ = context.options(RuntimeExecutorKind.MAP_MECHANIC)
        self._contributor = CampaignSubmarineSupportPopupContributor(self._handle_popup)
        super().__init__({RuntimeExecutorKind.MAP_MECHANIC})

    @staticmethod
    def _handle_popup(runtime: SubmarineSupportPopupRuntime) -> bool:
        return runtime.handle_popup_confirm("SUBMARINE_SUPPORT")

    @property
    def submarine_support_popup_contributor(self) -> CampaignSubmarineSupportPopupContributor:
        return self._contributor


class SubmarineFreshCombatExecutor(RuntimeExecutorInstance):
    __slots__ = ("_contributor",)

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        _ = context.options(RuntimeExecutorKind.MAP_MECHANIC)
        self._contributor = CampaignSubmarineFreshCombatContributor(self._start_combat)
        super().__init__({RuntimeExecutorKind.MAP_MECHANIC})

    @staticmethod
    def _start_combat(runtime: SubmarineFreshCombatRuntime) -> None:
        logger.hr(f"{runtime.FUNCTION_NAME_BASE}SUBMARINE", level=2)
        runtime.combat(
            balance_hp=False,
            emotion_reduce=False,
            expected_end="no_searching",
        )

    @property
    def submarine_fresh_combat_contributor(self) -> CampaignSubmarineFreshCombatContributor:
        return self._contributor


def _single_contributor[ContributorT](
    contributors: list[ContributorT],
    *,
    name: str,
) -> ContributorT | None:
    if len(contributors) > 1:
        message = f"campaign submarine services accept at most one {name} contributor"
        raise CampaignRuntimeProfileError(message)
    return None if not contributors else contributors[0]


def _required_support_fleet_state(instances: tuple[object, ...]) -> SupportFleetAttemptState:
    sources = [instance for instance in instances if isinstance(instance, SupportFleetStateSource)]
    if len(sources) != 1:
        message = "campaign submarine contributors require exactly one support fleet state source"
        raise CampaignRuntimeProfileError(message)
    state = sources[0].support_fleet_state
    if not isinstance(state, SupportFleetAttemptState):
        message = "campaign submarine support fleet source must provide SupportFleetAttemptState"
        raise CampaignRuntimeProfileError(message)
    return state


def _popup_contributors(
    instances: tuple[object, ...],
) -> list[CampaignSubmarineSupportPopupContributor]:
    contributors: list[CampaignSubmarineSupportPopupContributor] = []
    for instance in instances:
        if not isinstance(instance, CampaignSubmarineSupportPopupContributorSource):
            continue
        contributor = instance.submarine_support_popup_contributor
        if not isinstance(contributor, CampaignSubmarineSupportPopupContributor):
            message = "campaign submarine popup source must provide a typed contributor"
            raise CampaignRuntimeProfileError(message)
        contributors.append(contributor)
    return contributors


def _fresh_combat_contributors(
    instances: tuple[object, ...],
) -> list[CampaignSubmarineFreshCombatContributor]:
    contributors: list[CampaignSubmarineFreshCombatContributor] = []
    for instance in instances:
        if not isinstance(instance, CampaignSubmarineFreshCombatContributorSource):
            continue
        contributor = instance.submarine_fresh_combat_contributor
        if not isinstance(contributor, CampaignSubmarineFreshCombatContributor):
            message = "campaign submarine fresh combat source must provide a typed contributor"
            raise CampaignRuntimeProfileError(message)
        contributors.append(contributor)
    return contributors


def build_campaign_submarine_services(instances: Iterable[object]) -> CampaignSubmarineServices:
    selected = tuple(instances)
    popup_contributor = _single_contributor(
        _popup_contributors(selected),
        name="popup",
    )
    fresh_contributor = _single_contributor(
        _fresh_combat_contributors(selected),
        name="fresh combat",
    )
    if popup_contributor is None and fresh_contributor is None:
        return STANDARD_CAMPAIGN_SUBMARINE_SERVICES

    state = _required_support_fleet_state(selected)

    def handle_popup(runtime: SubmarineSupportPopupRuntime) -> bool:
        if popup_contributor is None or not state.available:
            return False
        return popup_contributor.handler(runtime)

    def start_fresh_combat(runtime: SubmarineFreshCombatRuntime) -> None:
        if fresh_contributor is None:
            return
        if not state.sealed:
            message = "campaign submarine fresh combat requires sealed support fleet state"
            raise CampaignRuntimeProfileError(message)
        if state.available:
            fresh_contributor.handler(runtime)

    return CampaignSubmarineServices(
        popup=CampaignSubmarineSupportPopupService(handle_popup),
        fresh_combat=CampaignSubmarineFreshCombatService(start_fresh_combat),
    )


def _build_submarine_support_popup(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return SubmarineSupportPopupExecutor(context)


def _build_submarine_fresh_combat(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return SubmarineFreshCombatExecutor(context)


def submarine_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    schema = {RuntimeExecutorKind.MAP_MECHANIC: RuntimeExecutorOptionsSchema()}
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("map_mechanic/submarine_support_popup"),
            schema,
            _build_submarine_support_popup,
        ),
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("map_mechanic/submarine_fresh_combat"),
            schema,
            _build_submarine_fresh_combat,
        ),
    )
