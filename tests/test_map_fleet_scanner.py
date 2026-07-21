from typing import TYPE_CHECKING, override

from module.map.fleet import Fleet
from module.map.map_base import CampaignMap
from module.map.map_grids import SelectedGrids
from module.map.map_observer import STANDARD_CAMPAIGN_MAP_OBSERVER, CampaignMapObserver
from module.map.map_scanner import (
    CampaignFullScanEngine,
    MapScannerRules,
    MapScanRequest,
    MovableEnemyRules,
    MovableEnemySnapshot,
    MovableEnemyTracker,
    MovableScanRequest,
    StandardCampaignMapScanner,
)
from module.map.map_spawn_gap import MapSpawnProgress
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    import pytest

    from module.map.map_scanner import FullScanContext, MapScannerRuntime, MovableTrackerContext


class _RecordingScanner:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def full_scan(
        self,
        runtime: MapScannerRuntime,
        request: MapScanRequest,
    ) -> None:
        self.calls.append(("full_scan", runtime, request))

    def full_scan_movable(
        self,
        runtime: MapScannerRuntime,
        request: MovableScanRequest,
    ) -> None:
        self.calls.append(("full_scan_movable", runtime, request))


class _ScannerFleet(Fleet):
    def __init__(self, scanner: _RecordingScanner) -> None:
        self._map_observer = CampaignMapObserver(
            combat=STANDARD_CAMPAIGN_MAP_OBSERVER.combat,
            scanner=scanner,
            enemy_searching=STANDARD_CAMPAIGN_MAP_OBSERVER.enemy_searching,
            viewport=STANDARD_CAMPAIGN_MAP_OBSERVER.viewport,
            fleet_locator=STANDARD_CAMPAIGN_MAP_OBSERVER.fleet_locator,
            preparation=STANDARD_CAMPAIGN_MAP_OBSERVER.preparation,
        )


class _RecordingMovableTracker(MovableEnemyTracker):
    def __init__(self) -> None:
        self.calls: list[tuple[MovableTrackerContext, MovableScanRequest, bool]] = []

    @override
    def track(
        self,
        runtime: MovableTrackerContext,
        request: MovableScanRequest,
        *,
        siren: bool,
    ) -> None:
        self.calls.append((runtime, request, siren))


class _NestedFullScanFleet(Fleet):
    def __init__(self) -> None:
        self.map = CampaignMap("nested-full-scan-test")
        self.map.map_data = "MS"
        self.map[(0, 0)].is_siren = True
        self.scan_requests: list[MapScanRequest] = []

    @override
    def full_scan(self, request: MapScanRequest | None = None) -> None:
        assert request is not None
        self.scan_requests.append(request)


class _StandardFullScanFleet(Fleet):
    def __init__(self) -> None:
        self.map = CampaignMap("standard-full-scan-test")
        self.map.map_data = "ME MS"
        self.map_scanner_rules = MapScannerRules(decoy_enemy=True, fleet_2_enabled=True)
        self.fleet_current_index = 1
        self.fleet_1_location = (0, 0)
        self.fleet_2_location = ()
        self.map[(0, 0)].is_fleet = True
        self.map[(0, 0)].is_current_fleet = True
        self.map[(0, 0)].is_enemy = True
        self.map[(1, 0)].is_fleet = True
        self.map[(1, 0)].is_siren = True


def _movable_request(*, enemy_cleared: bool = True) -> MovableScanRequest:
    return MovableScanRequest(
        snapshot=MovableEnemySnapshot(sirens=((0, 0),)),
        progress=MapSpawnProgress(battle_count=3),
        rules=MovableEnemyRules(
            siren=True,
            normal_enemy=False,
            enemy_template=False,
            wall=False,
            portal=False,
            ambush=False,
            siren_step=2,
        ),
        enemy_cleared=enemy_cleared,
    )


def test_fleet_full_scan_and_observer_movable_scan_forward_exact_requests() -> None:
    scanner = _RecordingScanner()
    fleet = _ScannerFleet(scanner)
    scan_request = MapScanRequest(
        queue=SelectedGrids([GridInfo()]),
        must_scan=SelectedGrids([GridInfo()]),
        progress=MapSpawnProgress(battle_count=4, mode="movable"),
    )
    movable_request = _movable_request(enemy_cleared=False)

    fleet.full_scan(scan_request)
    scanner.full_scan_movable(fleet, movable_request)

    assert scanner.calls == [
        ("full_scan", fleet, scan_request),
        ("full_scan_movable", fleet, movable_request),
    ]


def test_standard_movable_scan_reenters_the_public_full_scan_dispatch() -> None:
    fleet = _NestedFullScanFleet()
    tracker = _RecordingMovableTracker()
    scanner = StandardCampaignMapScanner(tracker=tracker)
    request = _movable_request(enemy_cleared=False)

    scanner.full_scan_movable(fleet, request)

    assert len(fleet.scan_requests) == 1
    scan_request = fleet.scan_requests[0]
    assert scan_request.progress == MapSpawnProgress(battle_count=3, mode="movable")
    assert scan_request.queue is scan_request.must_scan
    assert scan_request.queue is not None
    assert [grid.location for grid in scan_request.queue] == [(0, 0)]
    assert tracker.calls == [(fleet, request, True)]


def test_standard_full_scan_uses_effective_decoy_request_and_refreshes_fleet_projection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fleet = _StandardFullScanFleet()
    engine = CampaignFullScanEngine()
    calls: list[tuple[FullScanContext, MapScanRequest]] = []

    def record_scan(runtime: FullScanContext, observed_request: MapScanRequest) -> None:
        calls.append((runtime, observed_request))

    monkeypatch.setattr(engine, "scan", record_scan)
    scanner = StandardCampaignMapScanner(engine=engine)
    request = MapScanRequest(
        progress=MapSpawnProgress(
            battle_count=2,
            mystery_count=3,
            siren_count=4,
            carrier_count=5,
        )
    )

    scanner.full_scan(fleet, request)

    assert request.progress.mode == "normal"
    assert calls == [(fleet, request.with_mode("decoy"))]
    assert fleet.fleet_2_location == (1, 0)
    assert fleet.map[(0, 0)].is_enemy is False
    assert fleet.map[(1, 0)].is_siren is False
