from dataclasses import dataclass, field, replace
from typing import TYPE_CHECKING, Protocol

from module.base.failure import cleanup_scope
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.map.map_spawn_gap import MapSpawnProgress
from module.map.utils import location_ensure, match_movable

if TYPE_CHECKING:
    from module.map.map_base import CampaignMap
    from module.map.map_spawn_gap import MapSpawnGapPredictor
    from module.map.type_alias import FleetLocation, GridLocation, GridMode
    from module.map_detection.grid_info import GridInfo
    from module.map_detection.view import View


@dataclass(frozen=True, slots=True)
class MapScanRequest:
    queue: SelectedGrids[GridInfo] | None = None
    must_scan: SelectedGrids[GridInfo] | None = None
    progress: MapSpawnProgress = field(default_factory=MapSpawnProgress)

    def with_mode(self, mode: GridMode) -> MapScanRequest:
        return replace(self, progress=replace(self.progress, mode=mode))


@dataclass(frozen=True, slots=True)
class MovableEnemySnapshot:
    sirens: tuple[GridLocation, ...] = ()
    normal_enemies: tuple[GridLocation, ...] = ()

    @classmethod
    def capture(cls, map_: CampaignMap) -> MovableEnemySnapshot:
        return cls(
            sirens=tuple(location_ensure(grid) for grid in map_.layout.select(is_siren=True)),
            normal_enemies=tuple(location_ensure(grid) for grid in map_.layout.select(is_enemy=True)),
        )


@dataclass(frozen=True, slots=True)
class MovableEnemyRules:
    siren: bool
    normal_enemy: bool
    enemy_template: bool
    wall: bool
    portal: bool
    ambush: bool
    siren_step: int


@dataclass(frozen=True, slots=True)
class MapScannerRules:
    decoy_enemy: bool
    fleet_2_enabled: bool


@dataclass(frozen=True, slots=True)
class MovableScanRequest:
    snapshot: MovableEnemySnapshot
    progress: MapSpawnProgress
    rules: MovableEnemyRules
    enemy_cleared: bool = True


class FullScanContext(Protocol):
    map: CampaignMap
    camera: GridLocation
    view: View
    map_spawn_gap_predictor: MapSpawnGapPredictor

    def focus_to(self, location: GridInfo, swipe_limit: GridLocation = (4, 3)) -> None: ...

    def focus_to_grid_center(self, tolerance: float | None = None) -> bool: ...

    def ensure_edge_insight(self, *, skip_first_update: bool = True) -> list[GridLocation]: ...


class MovableTrackerContext(Protocol):
    map: CampaignMap
    map_spawn_gap_predictor: MapSpawnGapPredictor
    fleet_1_location: FleetLocation
    fleet_2_location: FleetLocation

    @property
    def fleet_current(self) -> FleetLocation: ...


class MapScannerRuntime(FullScanContext, MovableTrackerContext, Protocol):
    map_scanner_rules: MapScannerRules

    def full_scan(self, request: MapScanRequest | None = None) -> None: ...


class CampaignMapScanner(Protocol):
    def full_scan(self, runtime: MapScannerRuntime, request: MapScanRequest) -> None: ...

    def full_scan_movable(self, runtime: MapScannerRuntime, request: MovableScanRequest) -> None: ...


class CampaignFullScanEngine:
    """执行一次完整地图扫描，不处理舰队规则或 profile 分派。"""

    @staticmethod
    def scan(runtime: FullScanContext, request: MapScanRequest) -> None:
        progress = request.progress
        logger.info(f"Full scan start, mode={progress.mode}")
        runtime.map.reset_fleet()

        queue = request.queue or runtime.map.layout.camera_data
        if request.must_scan:
            queue = queue.add(request.must_scan)

        while len(queue) > 0:
            if runtime.map_spawn_gap_predictor.scan_complete(progress):
                if request.must_scan and queue.count != queue.delete(request.must_scan).count:
                    logger.info("Continue scanning.")
                else:
                    logger.info("All spawn found, Early stopped.")
                    break

            queue = queue.sort_by_camera_distance(runtime.camera)
            runtime.focus_to(queue[0])
            runtime.focus_to_grid_center(0.25)
            success = runtime.map.update(grids=runtime.view, camera=runtime.camera, mode=progress.mode)
            if not success:
                runtime.ensure_edge_insight(skip_first_update=False)
                continue

            queue = queue[1:]

        runtime.map_spawn_gap_predictor.infer_covered_spawns(progress)
        runtime.map.show()


class MovableEnemyTracker:
    """按单次移动前快照跟踪敌人，并恢复临时拓扑/寻路投影。"""

    def track(
        self,
        runtime: MovableTrackerContext,
        request: MovableScanRequest,
        *,
        siren: bool,
    ) -> None:
        before, after, spawn, step = self._context(runtime, request, siren=siren)
        matched_before, matched_after = match_movable(
            before=self._locations(before),
            spawn=self._locations(spawn),
            after=self._locations(after),
            fleets=[self._require_fleet_location(runtime.fleet_current)] if request.enemy_cleared else [],
            fleet_step=step,
        )
        matched_before_grids = runtime.map.layout.to_selected(matched_before)
        matched_after_grids = runtime.map.layout.to_selected(matched_after)
        logger.info(f"Movable enemy {before} -> {after}")
        logger.info(f"Tracked enemy {matched_before_grids} -> {matched_after_grids}")

        self._delete_wrong_detection(
            request,
            after=after,
            matched_after=matched_after_grids,
        )
        diff = before.delete(matched_before_grids)
        missing = self._missing_count(runtime, request, siren=siren)
        if diff and missing != 0:
            logger.warning(f"Movable enemy tracking lost: {diff}")
            predicted = self._predict_missing(runtime, request, diff=diff, after=after, siren=siren)
            matched_after_grids = matched_after_grids.add(predicted)
        elif missing == 0:
            logger.info(f"Movable enemy tracking drop: {diff}")

        self._mark_matched(matched_after_grids, current=runtime.fleet_current)

    @staticmethod
    def _locations(grids: SelectedGrids[GridInfo]) -> list[GridLocation]:
        return [location_ensure(grid) for grid in grids]

    @staticmethod
    def _require_fleet_location(location: FleetLocation) -> GridLocation:
        if len(location) != 2:
            msg = "舰队缺少地图位置"
            raise RuntimeError(msg)
        return location

    @staticmethod
    def _context(
        runtime: MovableTrackerContext,
        request: MovableScanRequest,
        *,
        siren: bool,
    ) -> tuple[SelectedGrids[GridInfo], SelectedGrids[GridInfo], SelectedGrids[GridInfo], int]:
        before_locations = request.snapshot.sirens if siren else request.snapshot.normal_enemies
        layout = runtime.map.layout
        before = layout.to_selected(before_locations)
        after = layout.select(is_siren=True) if siren else layout.select(is_enemy=True)
        spawn = layout.select(may_siren=True) if siren else layout.select(may_enemy=True)
        step = request.rules.siren_step if siren else 1
        return before, after, spawn, step

    @staticmethod
    def _delete_wrong_detection(
        request: MovableScanRequest,
        *,
        after: SelectedGrids[GridInfo],
        matched_after: SelectedGrids[GridInfo],
    ) -> None:
        if request.rules.normal_enemy:
            return
        for grid in after.delete(matched_after):
            if not grid.may_siren:
                logger.warning(f"Wrong detection: {grid}")
                grid.wipe_out()

    @staticmethod
    def _missing_count(runtime: MovableTrackerContext, request: MovableScanRequest, *, siren: bool) -> int:
        snapshot = runtime.map_spawn_gap_predictor.estimate(request.progress)
        return snapshot.missing["siren"] if siren else snapshot.missing["enemy"]

    def _predict_missing(
        self,
        runtime: MovableTrackerContext,
        request: MovableScanRequest,
        *,
        diff: SelectedGrids[GridInfo],
        after: SelectedGrids[GridInfo],
        siren: bool,
    ) -> SelectedGrids[GridInfo]:
        covered = self._covered_grids(runtime, request, after=after, siren=siren)
        accessible = self._accessible_grids(runtime, request, diff=diff, siren=siren)
        predicted = accessible.intersect(covered).select(is_sea=True, is_fleet=False)
        logger.info(f"Movable enemy predict: {predicted}")
        self._mark_predicted(predicted, siren=siren)
        return predicted

    @staticmethod
    def _covered_grids(
        runtime: MovableTrackerContext,
        request: MovableScanRequest,
        *,
        after: SelectedGrids[GridInfo],
        siren: bool,
    ) -> SelectedGrids[GridInfo]:
        current = MovableEnemyTracker._require_fleet_location(runtime.fleet_current)
        layout = runtime.map.layout
        covered = layout.covered_by(layout[current], offsets=[(0, -2)])
        for location in (runtime.fleet_1_location, runtime.fleet_2_location):
            if location:
                covered = covered.add(layout.covered_by(layout[location], offsets=[(0, -1)]))

        if request.rules.normal_enemy and not request.rules.enemy_template:
            for location in (runtime.fleet_1_location, runtime.fleet_2_location):
                if location:
                    covered = covered.add(layout.covered_by(layout[location], offsets=[(1, 0)]))

        covered = covered.add(layout.manual_coverage)
        cover_sources = after if siren else layout.select(is_siren=True)
        for grid in cover_sources:
            covered = covered.add(layout.covered_by(grid))
        logger.attr("enemy_covered", covered)
        return covered

    @staticmethod
    def _accessible_grids(
        runtime: MovableTrackerContext,
        request: MovableScanRequest,
        *,
        diff: SelectedGrids[GridInfo],
        siren: bool,
    ) -> SelectedGrids[GridInfo]:
        accessible: SelectedGrids[GridInfo] = SelectedGrids([])

        def restore_projection() -> None:
            if request.rules.wall:
                runtime.map.topology.rebuild(wall=True, portal=request.rules.portal)
            runtime.map.pathfinder.project(runtime.fleet_current, has_ambush=request.rules.ambush)

        with cleanup_scope(
            restore_projection,
            message="movable enemy projection and path restore both failed",
        ):
            if request.rules.wall:
                runtime.map.topology.rebuild(wall=False, portal=request.rules.portal)
            for grid in diff:
                runtime.map.pathfinder.project(grid, has_ambush=False)
                accessible = accessible.add(runtime.map.layout.select(cost=0)).add(runtime.map.layout.select(cost=1))
                if siren:
                    accessible = accessible.add(runtime.map.layout.select(cost=2))

        logger.attr("enemy_accessible", accessible)
        return accessible

    @staticmethod
    def _mark_predicted(predicted: SelectedGrids[GridInfo], *, siren: bool) -> None:
        for grid in predicted:
            if siren:
                grid.is_siren = True
            grid.is_enemy = True

    @staticmethod
    def _mark_matched(matched_after: SelectedGrids[GridInfo], *, current: FleetLocation) -> None:
        for grid in matched_after:
            if grid.location != current:
                grid.is_movable = True


class StandardCampaignMapScanner:
    def __init__(
        self,
        engine: CampaignFullScanEngine | None = None,
        tracker: MovableEnemyTracker | None = None,
    ) -> None:
        self._engine = engine or CampaignFullScanEngine()
        self._tracker = tracker or MovableEnemyTracker()

    def full_scan(self, runtime: MapScannerRuntime, request: MapScanRequest) -> None:
        effective = (
            request.with_mode("decoy")
            if runtime.map_scanner_rules.decoy_enemy and request.progress.mode == "normal"
            else request
        )
        self._engine.scan(runtime, effective)
        self._refresh_fleet_projection(runtime)

    def full_scan_movable(self, runtime: MapScannerRuntime, request: MovableScanRequest) -> None:
        rules = request.rules
        sirens = runtime.map.layout.to_selected(request.snapshot.sirens)
        normal_enemies = runtime.map.layout.to_selected(request.snapshot.normal_enemies)
        if rules.normal_enemy:
            if rules.siren:
                self._wipe(sirens)
                self._wipe(normal_enemies)
                runtime.full_scan(MapScanRequest(progress=request.progress).with_mode("movable"))
                self._tracker.track(runtime, request, siren=True)
                self._tracker.track(runtime, request, siren=False)
            else:
                self._wipe(normal_enemies)
                runtime.full_scan(MapScanRequest(progress=request.progress).with_mode("movable"))
                self._tracker.track(runtime, request, siren=False)
        elif rules.siren:
            self._wipe(sirens)
            runtime.full_scan(
                MapScanRequest(
                    queue=None if request.enemy_cleared else sirens,
                    must_scan=sirens,
                    progress=replace(request.progress, mode="movable"),
                )
            )
            self._tracker.track(runtime, request, siren=True)

    @staticmethod
    def _wipe(grids: SelectedGrids[GridInfo]) -> None:
        for grid in grids:
            grid.wipe_out()

    @staticmethod
    def _refresh_fleet_projection(runtime: MapScannerRuntime) -> None:
        if runtime.map_scanner_rules.fleet_2_enabled and not runtime.fleet_2_location:
            fleets = runtime.map.layout.select(is_fleet=True, is_current_fleet=False)
            if fleets.count:
                logger.info(f"Predict fleet_2 to be {fleets[0]}")
                runtime.fleet_2_location = location_ensure(fleets[0])

        for location in (runtime.fleet_1_location, runtime.fleet_2_location):
            if location and location in runtime.map:
                grid = runtime.map[location]
                if grid.may_boss and grid.is_caught_by_siren:
                    # Boss 可能直接刷新在舰队所在格。
                    continue
                grid.wipe_out()


STANDARD_CAMPAIGN_MAP_SCANNER = StandardCampaignMapScanner()
