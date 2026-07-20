from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, override, runtime_checkable

from module.content.runtime_profile import RuntimeExecutorKind
from module.map.map_observer import (
    STANDARD_CAMPAIGN_MAP_OBSERVER,
    CampaignMapObserver,
    MapObserverRuntime,
)

from .campaign_runtime_profile import RuntimeExecutorInstance

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from module.map_detection.grid_info import GridInfo

type CameraRepositioningNext = Callable[[MapObserverRuntime, GridInfo], bool]
type CameraRepositioningHandler = Callable[
    [MapObserverRuntime, GridInfo, CameraRepositioningNext],
    bool,
]


@dataclass(frozen=True, slots=True)
class CampaignMapObserverContributor:
    camera_repositioning: CameraRepositioningHandler | None = None


@runtime_checkable
class CampaignMapObserverContributorSource(Protocol):
    @property
    def map_observer_contributor(self) -> CampaignMapObserverContributor: ...


class CampaignMapObserverExecutor(RuntimeExecutorInstance):
    """提供 typed 地图观察能力，不暴露 string-dispatched observation method。"""

    __slots__ = ("_map_observer_contributor",)

    def __init__(self, contributor: CampaignMapObserverContributor) -> None:
        if not isinstance(contributor, CampaignMapObserverContributor):
            message = "campaign map observer executor requires a typed contributor"
            raise TypeError(message)
        super().__init__({RuntimeExecutorKind.MAP_OBSERVATION})
        self._map_observer_contributor = contributor

    @property
    def map_observer_contributor(self) -> CampaignMapObserverContributor:
        return self._map_observer_contributor


@dataclass(frozen=True, slots=True)
class _ComposedCampaignMapObserver(CampaignMapObserver):
    camera_repositioning_handler: CameraRepositioningNext

    @override
    def camera_repositioned_after_combat(
        self,
        runtime: MapObserverRuntime,
        destination: GridInfo,
    ) -> bool:
        return self.camera_repositioning_handler(runtime, destination)


def _overlay_camera_repositioning(
    handler: CameraRepositioningHandler,
    next_handler: CameraRepositioningNext,
) -> CameraRepositioningNext:
    def execute(runtime: MapObserverRuntime, destination: GridInfo) -> bool:
        return handler(runtime, destination, next_handler)

    return execute


def build_campaign_map_observer(instances: Iterable[object]) -> CampaignMapObserver:
    """按 profile 顺序组合地图观察规则；后声明的 contributor 先获得处理权。"""

    camera_repositioning = STANDARD_CAMPAIGN_MAP_OBSERVER.camera_repositioned_after_combat
    for instance in instances:
        if not isinstance(instance, CampaignMapObserverContributorSource):
            continue
        handler = instance.map_observer_contributor.camera_repositioning
        if handler is not None:
            camera_repositioning = _overlay_camera_repositioning(handler, camera_repositioning)
    return _ComposedCampaignMapObserver(camera_repositioning)
