from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

from module.adapters.campaign_map_observer import (
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
    FullScanRequest,
    build_campaign_map_observer,
)
from module.map.camera import FullScanOptions
from module.map.map_base import CampaignMap
from module.map.map_grids import SelectedGrids
from module.map.map_observer import STANDARD_CAMPAIGN_MAP_OBSERVER, CampaignMapObserver
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from module.adapters.campaign_map_observer import (
        CameraRepositioningHandler,
        CameraRepositioningNext,
        FullScanHandler,
        FullScanMovableHandler,
        FullScanMovableNext,
        FullScanNext,
    )
    from module.map.map_observer import MapObserverRuntime, MapScannerRuntime
    from module.map.type_alias import GridMode


class _Runtime:
    def __init__(self, spawn_data: list[dict[str, int]], *, battle_count: int) -> None:
        self.map = CampaignMap("observer-test")
        self.map.spawn_data = spawn_data
        self.battle_count = battle_count


class _ScannerRuntime:
    def __init__(self) -> None:
        self.map = CampaignMap("scanner-test")
        self.calls: list[tuple[object, ...]] = []

    def _standard_full_scan(
        self,
        options: FullScanOptions | None = None,
        queue: SelectedGrids[GridInfo] | None = None,
        must_scan: SelectedGrids[GridInfo] | None = None,
        mode: GridMode = "normal",
    ) -> None:
        self.calls.append(("standard_scan", options, queue, must_scan, mode))

    def _standard_full_scan_movable(self, *, enemy_cleared: bool = True) -> None:
        self.calls.append(("standard_movable", enemy_cleared))


def test_standard_map_observer_matches_only_the_current_boss_spawn() -> None:
    destination = GridInfo()
    runtime = _Runtime(
        [
            {"battle": 1, "enemy": 1},
            {"battle": 2, "boss": 1},
        ],
        battle_count=2,
    )

    assert STANDARD_CAMPAIGN_MAP_OBSERVER.combat.camera_repositioned_after_combat(runtime, destination)

    runtime.battle_count = 1
    assert not STANDARD_CAMPAIGN_MAP_OBSERVER.combat.camera_repositioned_after_combat(runtime, destination)


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

    assert not observer.combat.camera_repositioned_after_combat(runtime, destination)
    assert calls == [
        ("second", runtime, destination),
        ("first", runtime, destination),
    ]


def test_map_observer_is_frozen_and_composes_scanners_later_first() -> None:
    runtime = _ScannerRuntime()
    scan_calls: list[tuple[str, MapScannerRuntime, FullScanRequest]] = []
    movable_calls: list[tuple[str, MapScannerRuntime, bool]] = []

    def scan_handler(label: str) -> FullScanHandler:
        def execute(
            observed_runtime: MapScannerRuntime,
            request: FullScanRequest,
            next_handler: FullScanNext,
        ) -> None:
            scan_calls.append((label, observed_runtime, request))
            next_handler(observed_runtime, request)

        return execute

    def movable_handler(label: str) -> FullScanMovableHandler:
        def execute(
            runtime: MapScannerRuntime,
            next_handler: FullScanMovableNext,
            *,
            enemy_cleared: bool = True,
        ) -> None:
            movable_calls.append((label, runtime, enemy_cleared))
            next_handler(runtime, enemy_cleared=enemy_cleared)

        return execute

    observer = build_campaign_map_observer(
        (
            CampaignMapObserverExecutor(
                CampaignMapObserverContributor(
                    full_scan=scan_handler("first"),
                    full_scan_movable=movable_handler("first"),
                )
            ),
            CampaignMapObserverExecutor(
                CampaignMapObserverContributor(
                    full_scan=scan_handler("second"),
                    full_scan_movable=movable_handler("second"),
                )
            ),
        )
    )
    options = FullScanOptions(battle_count=3)
    queue = SelectedGrids([GridInfo()])
    must_scan = SelectedGrids([GridInfo()])

    observer.scanner.full_scan(
        runtime,
        options=options,
        queue=queue,
        must_scan=must_scan,
        mode="movable",
    )
    observer.scanner.full_scan_movable(runtime, enemy_cleared=False)

    assert [label for label, _, _ in scan_calls] == ["second", "first"]
    assert scan_calls[0][1] is runtime
    assert scan_calls[0][2] is scan_calls[1][2]
    assert scan_calls[0][2] == FullScanRequest(options, queue, must_scan, "movable")
    assert [label for label, _, _ in movable_calls] == ["second", "first"]
    assert movable_calls[0][1] is runtime
    assert [enemy_cleared for _, _, enemy_cleared in movable_calls] == [False, False]
    assert runtime.calls == [
        ("standard_scan", options, queue, must_scan, "movable"),
        ("standard_movable", False),
    ]
    field_name = "combat"
    with pytest.raises(FrozenInstanceError):
        setattr(observer, field_name, STANDARD_CAMPAIGN_MAP_OBSERVER.combat)
    assert isinstance(observer, CampaignMapObserver)
