from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, override, runtime_checkable

from module.map.map_fleet_preparation import (
    STANDARD_FLEET_PREPARATION_SERVICE,
    FleetPreparationRuntime,
    FleetPreparationService,
)

from .campaign_runtime_profile import CampaignRuntimeProfileError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

type FleetPreparationNext = Callable[[FleetPreparationRuntime], bool]
type FleetPreparationHandler = Callable[
    [FleetPreparationRuntime, FleetPreparationNext],
    bool,
]


@dataclass(frozen=True, slots=True)
class CampaignFleetPreparationContributor:
    handler: FleetPreparationHandler

    def __post_init__(self) -> None:
        if not callable(self.handler):
            message = "campaign fleet preparation contributor requires a handler"
            raise TypeError(message)


@runtime_checkable
class CampaignFleetPreparationContributorSource(Protocol):
    @property
    def fleet_preparation_contributor(self) -> CampaignFleetPreparationContributor: ...


@dataclass(frozen=True, slots=True)
class _ComposedFleetPreparationService(FleetPreparationService):
    handler: FleetPreparationNext

    def __post_init__(self) -> None:
        if not callable(self.handler):
            message = "campaign fleet preparation service requires a handler"
            raise TypeError(message)

    @override
    def prepare(self, runtime: FleetPreparationRuntime) -> bool:
        result = self.handler(runtime)
        if type(result) is not bool:
            message = "campaign fleet preparation handler must return bool"
            raise CampaignRuntimeProfileError(message)
        return result


def _overlay_fleet_preparation(
    handler: FleetPreparationHandler,
    next_handler: FleetPreparationNext,
) -> FleetPreparationNext:
    def prepare(runtime: FleetPreparationRuntime) -> bool:
        return handler(runtime, next_handler)

    return prepare


def build_campaign_fleet_preparation_service(
    instances: Iterable[object],
) -> FleetPreparationService:
    """按 profile 顺序组合准备规则；后声明的 contributor 先处理。"""

    handler = STANDARD_FLEET_PREPARATION_SERVICE.prepare
    for instance in instances:
        if not isinstance(instance, CampaignFleetPreparationContributorSource):
            continue
        contributor = instance.fleet_preparation_contributor
        if not isinstance(contributor, CampaignFleetPreparationContributor):
            message = "campaign fleet preparation source must provide a typed contributor"
            raise CampaignRuntimeProfileError(message)
        handler = _overlay_fleet_preparation(contributor.handler, handler)
    return _ComposedFleetPreparationService(handler)
