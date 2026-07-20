from typing import TYPE_CHECKING

from module.adapters.campaign_map_observer import (
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
    build_campaign_map_observer,
)
from module.map.map_base import CampaignMap
from module.map.map_observer import STANDARD_CAMPAIGN_MAP_OBSERVER
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from module.adapters.campaign_map_observer import (
        CameraRepositioningHandler,
        CameraRepositioningNext,
    )
    from module.map.map_observer import MapObserverRuntime


class _Runtime:
    def __init__(self, spawn_data: list[dict[str, int]], *, battle_count: int) -> None:
        self.map = CampaignMap("observer-test")
        self.map.spawn_data = spawn_data
        self.battle_count = battle_count


def test_standard_map_observer_matches_only_the_current_boss_spawn() -> None:
    destination = GridInfo()
    runtime = _Runtime(
        [
            {"battle": 1, "enemy": 1},
            {"battle": 2, "boss": 1},
        ],
        battle_count=2,
    )

    assert STANDARD_CAMPAIGN_MAP_OBSERVER.camera_repositioned_after_combat(runtime, destination)

    runtime.battle_count = 1
    assert not STANDARD_CAMPAIGN_MAP_OBSERVER.camera_repositioned_after_combat(runtime, destination)


def test_map_observer_composition_is_later_first_and_preserves_destination_identity() -> None:
    destination = GridInfo()
    runtime = _Runtime([], battle_count=0)
    calls: list[tuple[str, MapObserverRuntime, GridInfo]] = []

    def handler(label: str) -> CameraRepositioningHandler:
        def execute(
            observed_runtime: MapObserverRuntime,
            observed_destination: GridInfo,
            next_handler: CameraRepositioningNext,
        ) -> bool:
            calls.append((label, observed_runtime, observed_destination))
            return next_handler(observed_runtime, observed_destination)

        return execute

    observer = build_campaign_map_observer(
        (
            CampaignMapObserverExecutor(CampaignMapObserverContributor(camera_repositioning=handler("first"))),
            CampaignMapObserverExecutor(CampaignMapObserverContributor(camera_repositioning=handler("second"))),
        )
    )

    assert not observer.camera_repositioned_after_combat(runtime, destination)
    assert calls == [
        ("second", runtime, destination),
        ("first", runtime, destination),
    ]
