from typing import TYPE_CHECKING, override

from module.map.camera import FullScanOptions
from module.map.fleet import Fleet
from module.map.map_grids import SelectedGrids
from module.map.map_observer import STANDARD_CAMPAIGN_MAP_OBSERVER, CampaignMapObserver
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from module.map.map_observer import MapScannerRuntime
    from module.map.type_alias import GridMode


class _RecordingScanner:
    def __init__(self) -> None:
        self.calls: list[tuple[object, ...]] = []

    def full_scan(
        self,
        runtime: MapScannerRuntime,
        options: FullScanOptions | None = None,
        queue: SelectedGrids[GridInfo] | None = None,
        must_scan: SelectedGrids[GridInfo] | None = None,
        mode: GridMode = "normal",
    ) -> None:
        self.calls.append(("full_scan", runtime, options, queue, must_scan, mode))

    def full_scan_movable(
        self,
        runtime: MapScannerRuntime,
        *,
        enemy_cleared: bool = True,
    ) -> None:
        self.calls.append(("full_scan_movable", runtime, enemy_cleared))


class _ScannerFleet(Fleet):
    def __init__(self, scanner: _RecordingScanner) -> None:
        self._map_observer = CampaignMapObserver(
            combat=STANDARD_CAMPAIGN_MAP_OBSERVER.combat,
            scanner=scanner,
        )


class _MovableConfig:
    MAP_HAS_MOVABLE_ENEMY = True
    MAP_HAS_MOVABLE_NORMAL_ENEMY = False


class _NestedFullScanFleet(Fleet):
    config: _MovableConfig

    def __init__(self) -> None:
        self.config = _MovableConfig()
        self.movable_before = SelectedGrids([GridInfo()])
        self.calls: list[tuple[object, ...]] = []

    @override
    def full_scan(
        self,
        options: FullScanOptions | None = None,
        queue: SelectedGrids[GridInfo] | None = None,
        must_scan: SelectedGrids[GridInfo] | None = None,
        mode: GridMode = "normal",
    ) -> None:
        self.calls.append(("public_full_scan", options, queue, must_scan, mode))

    @override
    def track_movable(self, *, enemy_cleared: bool = True, siren: bool = True) -> None:
        self.calls.append(("track_movable", enemy_cleared, siren))


def test_fleet_canonical_scan_methods_forward_exact_arguments_to_injected_scanner() -> None:
    scanner = _RecordingScanner()
    fleet = _ScannerFleet(scanner)
    options = FullScanOptions(battle_count=4)
    queue = SelectedGrids([GridInfo()])
    must_scan = SelectedGrids([GridInfo()])

    fleet.full_scan(options, queue, must_scan, "movable")
    fleet.full_scan_movable(enemy_cleared=False)

    assert scanner.calls == [
        ("full_scan", fleet, options, queue, must_scan, "movable"),
        ("full_scan_movable", fleet, False),
    ]


def test_standard_movable_scan_reenters_the_public_full_scan_dispatch() -> None:
    fleet = _NestedFullScanFleet()

    STANDARD_CAMPAIGN_MAP_OBSERVER.scanner.full_scan_movable(
        fleet,
        enemy_cleared=False,
    )

    assert fleet.calls == [
        ("public_full_scan", None, fleet.movable_before, fleet.movable_before, "movable"),
        ("track_movable", False, True),
    ]
