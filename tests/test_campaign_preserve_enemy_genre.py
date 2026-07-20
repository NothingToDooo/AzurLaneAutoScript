from typing import TYPE_CHECKING, Literal

import pytest

from module.adapters.campaign_map_observer import build_campaign_map_observer
from module.adapters.campaign_runtime_observation import (
    PreserveEnemyGenreExecutor,
    observation_runtime_executor_descriptors,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileError,
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

if TYPE_CHECKING:
    from module.map.camera import FullScanOptions
    from module.map.map_grids import SelectedGrids
    from module.map.map_observer import CampaignMapObserver
    from module.map.type_alias import GridMode
    from module.map_detection.grid_info import GridInfo

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


def _executor_and_observer() -> tuple[PreserveEnemyGenreExecutor, CampaignMapObserver]:
    manager = _manager()
    instance = manager.executor_instance(RuntimeExecutorKind.MAP_OBSERVATION)
    assert isinstance(instance, PreserveEnemyGenreExecutor)
    observer = build_campaign_map_observer(manager.executor_instances(RuntimeExecutorKind.MAP_OBSERVATION))
    return instance, observer


class _PreserveRuntime:
    def __init__(
        self,
        observer: CampaignMapObserver,
        executor: PreserveEnemyGenreExecutor,
        behavior: _MovableBehavior,
    ) -> None:
        self.map = CampaignMap("preserve-enemy-genre-test")
        self.map.shape = "A1"
        self.grid = self.map[(0, 0)]
        self.grid.is_siren = True
        self.grid.enemy_genre = _GENRE
        self.observer = observer
        self.executor = executor
        self.behavior = behavior
        self.events: list[tuple[object, ...]] = []

    def full_scan(
        self,
        options: FullScanOptions | None = None,
        queue: SelectedGrids[GridInfo] | None = None,
        must_scan: SelectedGrids[GridInfo] | None = None,
        mode: GridMode = "normal",
    ) -> None:
        self.observer.scanner.full_scan(
            self,
            options=options,
            queue=queue,
            must_scan=must_scan,
            mode=mode,
        )

    def _standard_full_scan(
        self,
        options: FullScanOptions | None = None,
        queue: SelectedGrids[GridInfo] | None = None,
        must_scan: SelectedGrids[GridInfo] | None = None,
        mode: GridMode = "normal",
    ) -> None:
        self.events.append(("scan", self.grid.is_siren, self.grid.enemy_genre, options, queue, must_scan, mode))
        if self.behavior == "scan_error":
            message = "nested scan failed"
            raise RuntimeError(message)

    def _standard_full_scan_movable(self, *, enemy_cleared: bool = True) -> None:
        self.grid.wipe_out()
        self.events.append(("after_wipe", self.grid.is_siren, self.grid.enemy_genre, enemy_cleared))
        if self.behavior == "next_error":
            message = "movable scan failed"
            raise RuntimeError(message)
        if self.behavior == "no_scan":
            return
        if self.behavior == "reset":
            self.executor.reset()
            self.events.append(("after_reset", self.grid.is_siren, self.grid.enemy_genre))
            return
        self.full_scan(mode="movable")
        self.events.append(("track", self.grid.is_siren, self.grid.enemy_genre))


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

    observer.scanner.full_scan_movable(runtime, enemy_cleared=False)

    assert runtime.events == [
        ("after_wipe", False, None, False),
        ("scan", False, None, None, None, None, "movable"),
        ("track", True, _GENRE),
    ]


def test_preserve_restores_and_clears_when_movable_path_skips_full_scan() -> None:
    executor, observer = _executor_and_observer()
    runtime = _PreserveRuntime(observer, executor, "no_scan")

    observer.scanner.full_scan_movable(runtime)

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
        observer.scanner.full_scan_movable(runtime)

    assert runtime.grid.is_siren
    assert runtime.grid.enemy_genre == _GENRE
    _assert_no_later_scan_leak(runtime)


def test_preserve_reset_restores_and_clears_pending_state() -> None:
    executor, observer = _executor_and_observer()
    runtime = _PreserveRuntime(observer, executor, "reset")

    observer.scanner.full_scan_movable(runtime)

    assert runtime.events[-1] == ("after_reset", True, _GENRE)
    _assert_no_later_scan_leak(runtime)


@pytest.mark.parametrize(
    "obsolete_options",
    [
        {"operations": ["full_scan", "full_scan_movable"]},
        {"state": ["dace"]},
    ],
)
def test_preserve_rejects_obsolete_string_operations_and_state(
    obsolete_options: dict[str, object],
) -> None:
    with pytest.raises(CampaignRuntimeProfileError, match="unknown option"):
        _manager(**obsolete_options)
