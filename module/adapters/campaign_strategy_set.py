from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, override, runtime_checkable

from module.handler.strategy_set import (
    STANDARD_STRATEGY_SET_SERVICE,
    StrategySetRequest,
    StrategySetRuntime,
    StrategySetService,
)

from .campaign_runtime_profile import CampaignRuntimeProfileError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

type CampaignStrategySetObserver = Callable[
    [StrategySetRuntime, StrategySetRequest],
    None,
]


@dataclass(frozen=True, slots=True)
class CampaignStrategySetObserverContributor:
    observer: CampaignStrategySetObserver

    def __post_init__(self) -> None:
        if not callable(self.observer):
            message = "campaign strategy set observer contributor requires an observer"
            raise TypeError(message)


@runtime_checkable
class CampaignStrategySetObserverContributorSource(Protocol):
    @property
    def strategy_set_observer_contributor(self) -> CampaignStrategySetObserverContributor: ...


@dataclass(frozen=True, slots=True)
class _ObservedStrategySetService(StrategySetService):
    observers: tuple[CampaignStrategySetObserver, ...]

    def __post_init__(self) -> None:
        if any(not callable(observer) for observer in self.observers):
            message = "campaign strategy set service requires callable observers"
            raise TypeError(message)

    @override
    def execute(
        self,
        runtime: StrategySetRuntime,
        request: StrategySetRequest,
    ) -> None:
        STANDARD_STRATEGY_SET_SERVICE.execute(runtime, request)
        for observer in self.observers:
            observer(runtime, request)


def build_campaign_strategy_set_service(
    instances: Iterable[object],
) -> StrategySetService:
    observers: list[CampaignStrategySetObserver] = []
    for instance in instances:
        if not isinstance(instance, CampaignStrategySetObserverContributorSource):
            continue
        contributor = instance.strategy_set_observer_contributor
        if not isinstance(contributor, CampaignStrategySetObserverContributor):
            message = "campaign strategy set source must provide a typed observer contributor"
            raise CampaignRuntimeProfileError(message)
        observers.append(contributor.observer)
    return _ObservedStrategySetService(tuple(observers))
