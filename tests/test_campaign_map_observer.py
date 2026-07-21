from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING, cast

import pytest

from module.adapters.campaign_map_observer import (
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
    build_campaign_map_observer,
)
from module.handler.assets import MAP_ENEMY_SEARCHING
from module.map.map_base import CampaignMap
from module.map.map_grids import SelectedGrids
from module.map.map_observer import STANDARD_CAMPAIGN_MAP_OBSERVER, CampaignMapObserver
from module.map.map_scanner import (
    MapScanRequest,
    MovableEnemyRules,
    MovableEnemySnapshot,
    MovableScanRequest,
)
from module.map.map_spawn_gap import MapSpawnProgress
from module.map_detection.grid_info import GridInfo

if TYPE_CHECKING:
    from module.adapters.campaign_map_observer import (
        CameraRepositioningHandler,
        CameraRepositioningNext,
        EnemySearchingHandler,
        EnemySearchingNext,
        FullScanHandler,
        FullScanMovableHandler,
        FullScanMovableNext,
        FullScanNext,
    )
    from module.base.type_alias import ImageArray
    from module.map.map_observer import MapObserverRuntime
    from module.map.map_scanner import MapScannerRuntime


class _Runtime:
    def __init__(self, spawn_data: list[dict[str, int]], *, battle_count: int) -> None:
        self.map = CampaignMap("observer-test")
        self.map.spawn_data = spawn_data
        self.battle_count = battle_count


class _ScannerRuntime:
    def __init__(self) -> None:
        self.map = CampaignMap("scanner-test")


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
    runtime = cast("MapScannerRuntime", _ScannerRuntime())
    scan_calls: list[tuple[str, MapScannerRuntime, MapScanRequest]] = []
    movable_calls: list[tuple[str, MapScannerRuntime, MovableScanRequest]] = []

    def scan_handler(label: str, *, terminal: bool = False) -> FullScanHandler:
        def execute(
            observed_runtime: MapScannerRuntime,
            request: MapScanRequest,
            next_handler: FullScanNext,
        ) -> None:
            scan_calls.append((label, observed_runtime, request))
            if not terminal:
                next_handler(observed_runtime, request)

        return execute

    def movable_handler(label: str, *, terminal: bool = False) -> FullScanMovableHandler:
        def execute(
            runtime: MapScannerRuntime,
            request: MovableScanRequest,
            next_handler: FullScanMovableNext,
        ) -> None:
            movable_calls.append((label, runtime, request))
            if not terminal:
                next_handler(runtime, request)

        return execute

    observer = build_campaign_map_observer(
        (
            CampaignMapObserverExecutor(
                CampaignMapObserverContributor(
                    full_scan=scan_handler("first", terminal=True),
                    full_scan_movable=movable_handler("first", terminal=True),
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
    queue = SelectedGrids([GridInfo()])
    must_scan = SelectedGrids([GridInfo()])
    scan_request = MapScanRequest(
        queue=queue,
        must_scan=must_scan,
        progress=MapSpawnProgress(battle_count=3, mode="movable"),
    )
    movable_request = MovableScanRequest(
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
        enemy_cleared=False,
    )

    observer.scanner.full_scan(runtime, scan_request)
    observer.scanner.full_scan_movable(runtime, movable_request)

    assert [label for label, _, _ in scan_calls] == ["second", "first"]
    assert scan_calls[0][1] is runtime
    assert scan_calls[0][2] is scan_request
    assert scan_calls[1][2] is scan_request
    assert [label for label, _, _ in movable_calls] == ["second", "first"]
    assert movable_calls[0][1] is runtime
    assert movable_calls[0][2] is movable_request
    assert movable_calls[1][2] is movable_request
    field_name = "combat"
    with pytest.raises(FrozenInstanceError):
        setattr(observer, field_name, STANDARD_CAMPAIGN_MAP_OBSERVER.combat)
    assert isinstance(observer, CampaignMapObserver)


def test_standard_enemy_searching_observer_uses_the_exact_image_and_luma_offset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = cast("ImageArray", object())
    calls: list[tuple[object, object]] = []

    def match_luma(_button: object, observed_image: object, *, offset: object) -> bool:
        calls.append((observed_image, offset))
        return True

    monkeypatch.setattr(type(MAP_ENEMY_SEARCHING), "match_luma", match_luma)

    assert STANDARD_CAMPAIGN_MAP_OBSERVER.enemy_searching.appears(
        image,
        overlay_transparency_threshold=0.65,
    )
    assert calls == [(image, (5, 5))]


def test_enemy_searching_observer_composes_later_first_with_the_same_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = cast("ImageArray", object())
    calls: list[tuple[str, object, float | None]] = []

    def match_luma(_button: object, observed_image: object, *, offset: object) -> bool:
        calls.append(("standard", observed_image, None))
        assert offset == (5, 5)
        return True

    def handler(label: str) -> EnemySearchingHandler:
        def execute(
            observed_image: ImageArray,
            next_handler: EnemySearchingNext,
            *,
            overlay_transparency_threshold: float,
        ) -> bool:
            calls.append((label, observed_image, overlay_transparency_threshold))
            return next_handler(
                observed_image,
                overlay_transparency_threshold=overlay_transparency_threshold,
            )

        return execute

    monkeypatch.setattr(type(MAP_ENEMY_SEARCHING), "match_luma", match_luma)
    observer = build_campaign_map_observer(
        (
            CampaignMapObserverExecutor(CampaignMapObserverContributor(enemy_searching=handler("first"))),
            CampaignMapObserverExecutor(CampaignMapObserverContributor(enemy_searching=handler("second"))),
        )
    )

    assert observer.enemy_searching.appears(
        image,
        overlay_transparency_threshold=0.65,
    )
    assert calls == [
        ("second", image, 0.65),
        ("first", image, 0.65),
        ("standard", image, None),
    ]


def test_enemy_searching_replacement_does_not_call_next(monkeypatch: pytest.MonkeyPatch) -> None:
    image = cast("ImageArray", object())
    calls: list[tuple[object, float]] = []

    def unexpected_standard(_button: object, _image: object, *, offset: object) -> bool:
        del offset
        raise AssertionError

    def replacement(
        observed_image: ImageArray,
        next_handler: EnemySearchingNext,
        *,
        overlay_transparency_threshold: float,
    ) -> bool:
        del next_handler
        calls.append((observed_image, overlay_transparency_threshold))
        return False

    monkeypatch.setattr(type(MAP_ENEMY_SEARCHING), "match_luma", unexpected_standard)
    observer = build_campaign_map_observer(
        (CampaignMapObserverExecutor(CampaignMapObserverContributor(enemy_searching=replacement)),)
    )

    assert not observer.enemy_searching.appears(
        image,
        overlay_transparency_threshold=0.5,
    )
    assert calls == [(image, 0.5)]
