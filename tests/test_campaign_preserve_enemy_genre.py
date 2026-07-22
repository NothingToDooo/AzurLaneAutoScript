from dataclasses import replace
from typing import TYPE_CHECKING, Literal, cast

import pytest

from module.adapters.campaign_map_observer import (
    CampaignMapObserverContributor,
    CampaignMapObserverExecutor,
    build_campaign_map_observer,
)
from module.adapters.campaign_runtime_observation import (
    PreserveEnemyGenreExecutor,
    observation_runtime_executor_descriptors,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileManager,
)
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
)
from module.map.map_base import CampaignMap
from module.map.map_scanner import (
    MapScanRequest,
    MovableEnemyRules,
    MovableEnemySnapshot,
    MovableScanRequest,
)
from module.map.map_spawn_gap import MapSpawnProgress

if TYPE_CHECKING:
    from module.adapters.campaign_map_observer import FullScanMovableNext, FullScanNext
    from module.map.map_observer import CampaignMapObserver
    from module.map.map_scanner import MapScannerRuntime

type _MovableBehavior = Literal["normal", "no_scan", "next_error", "scan_error", "reset"]

_IMPLEMENTATION = RuntimeImplementationId("observation/preserve_enemy_genre")
_GENRE = "Siren_Dace"


def _manager(**extra_options: object) -> CampaignRuntimeProfileManager:
    options = {"genre": _GENRE, **extra_options}
    extension = CampaignRuntimeExtension(
        CampaignRuntimeExtensionId("preserve-enemy-genre-test"),
        (
            RuntimeExecutorBinding(
                RuntimeExecutorKind.MAP_OBSERVATION,
                _IMPLEMENTATION,
                options,
            ),
        ),
    )
    return CampaignRuntimeProfileManager(
        CampaignRuntimeProfile(
            CampaignRuntimeProfileId("preserve-enemy-genre-test"),
            (extension,),
        ),
        CampaignRuntimeExecutorRegistry(observation_runtime_executor_descriptors()),
    )


class _PreserveRuntime:
    def __init__(
        self,
        observer: CampaignMapObserver,
        executor: PreserveEnemyGenreExecutor,
        behavior: _MovableBehavior,
    ) -> None:
        self.map = CampaignMap("preserve-enemy-genre-test")
        self.map.layout.initialize("A1")
        self.grid = self.map[(0, 0)]
        self.grid.is_siren = True
        self.grid.enemy_genre = _GENRE
        self.observer = observer
        self.executor = executor
        self.behavior = behavior
        self.events: list[tuple[object, ...]] = []

    def full_scan(
        self,
        request: MapScanRequest | None = None,
    ) -> None:
        self.observer.scanner.full_scan(
            cast("MapScannerRuntime", self),
            request or MapScanRequest(),
        )

    def base_full_scan(self, request: MapScanRequest) -> None:
        self.events.append(("scan", self.grid.is_siren, self.grid.enemy_genre, request.progress.mode))
        if self.behavior == "scan_error":
            message = "nested scan failed"
            raise RuntimeError(message)

    def base_full_scan_movable(self, request: MovableScanRequest) -> None:
        self.grid.wipe_out()
        self.events.append(("after_wipe", self.grid.is_siren, self.grid.enemy_genre, request.enemy_cleared))
        if self.behavior == "next_error":
            message = "movable scan failed"
            raise RuntimeError(message)
        if self.behavior == "no_scan":
            return
        if self.behavior == "reset":
            self.executor.reset()
            self.events.append(("after_reset", self.grid.is_siren, self.grid.enemy_genre))
            return
        self.full_scan(MapScanRequest(progress=replace(request.progress, mode="movable")))
        self.events.append(("track", self.grid.is_siren, self.grid.enemy_genre))


def _base_full_scan(
    runtime: MapScannerRuntime,
    request: MapScanRequest,
    next_handler: FullScanNext,
) -> None:
    del next_handler
    cast("_PreserveRuntime", runtime).base_full_scan(request)


def _base_full_scan_movable(
    runtime: MapScannerRuntime,
    request: MovableScanRequest,
    next_handler: FullScanMovableNext,
) -> None:
    del next_handler
    cast("_PreserveRuntime", runtime).base_full_scan_movable(request)


def _executor_and_observer() -> tuple[PreserveEnemyGenreExecutor, CampaignMapObserver]:
    manager = _manager()
    instance = manager.executor_instance(RuntimeExecutorKind.MAP_OBSERVATION)
    assert isinstance(instance, PreserveEnemyGenreExecutor)
    base = CampaignMapObserverExecutor(
        CampaignMapObserverContributor(
            full_scan=_base_full_scan,
            full_scan_movable=_base_full_scan_movable,
        )
    )
    observer = build_campaign_map_observer((base, *manager.executor_instances(RuntimeExecutorKind.MAP_OBSERVATION)))
    return instance, observer


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


def _assert_no_later_scan_leak(runtime: _PreserveRuntime) -> None:
    runtime.behavior = "normal"
    runtime.grid.is_siren = False
    runtime.grid.enemy_genre = "Other"

    runtime.full_scan()

    assert not runtime.grid.is_siren
    assert runtime.grid.enemy_genre == "Other"


def test_preserve_restores_before_movable_tracking_continues() -> None:
    executor, observer = _executor_and_observer()
    runtime = _PreserveRuntime(observer, executor, "normal")

    observer.scanner.full_scan_movable(
        cast("MapScannerRuntime", runtime),
        _movable_request(enemy_cleared=False),
    )

    assert runtime.events == [
        ("after_wipe", False, None, False),
        ("scan", False, None, "movable"),
        ("track", True, _GENRE),
    ]


def test_preserve_restores_and_clears_when_movable_path_skips_full_scan() -> None:
    executor, observer = _executor_and_observer()
    runtime = _PreserveRuntime(observer, executor, "no_scan")

    observer.scanner.full_scan_movable(cast("MapScannerRuntime", runtime), _movable_request())

    assert runtime.grid.is_siren
    assert runtime.grid.enemy_genre == _GENRE
    _assert_no_later_scan_leak(runtime)


@pytest.mark.parametrize(
    ("behavior", "message"),
    [
        ("next_error", "movable scan failed"),
        ("scan_error", "nested scan failed"),
    ],
)
def test_preserve_restores_and_clears_after_scanner_exceptions(
    behavior: _MovableBehavior,
    message: str,
) -> None:
    executor, observer = _executor_and_observer()
    runtime = _PreserveRuntime(observer, executor, behavior)

    with pytest.raises(RuntimeError, match=message):
        observer.scanner.full_scan_movable(cast("MapScannerRuntime", runtime), _movable_request())

    assert runtime.grid.is_siren
    assert runtime.grid.enemy_genre == _GENRE
    _assert_no_later_scan_leak(runtime)


def test_preserve_reset_restores_and_clears_pending_state() -> None:
    executor, observer = _executor_and_observer()
    runtime = _PreserveRuntime(observer, executor, "reset")

    observer.scanner.full_scan_movable(cast("MapScannerRuntime", runtime), _movable_request())

    assert runtime.events[-1] == ("after_reset", True, _GENRE)
    _assert_no_later_scan_leak(runtime)
