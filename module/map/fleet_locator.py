from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Protocol, override

from module.base.utils import location2node
from module.logger import logger
from module.map.map_grids import SelectedGrids
from module.map.utils import location_ensure

if TYPE_CHECKING:
    from module.map.map_base import CampaignMap
    from module.map.type_alias import FleetLocation, GridLocation
    from module.map_detection.grid_info import GridInfo


@dataclass(frozen=True, slots=True)
class SurfaceFleetLocations:
    fleet_1: FleetLocation
    fleet_2: FleetLocation


@dataclass(frozen=True, slots=True)
class SurfaceFleetLocationRequest:
    previous: SurfaceFleetLocations
    fleet_2_enabled: bool
    poor_map_data: bool

    def __post_init__(self) -> None:
        if not isinstance(self.previous, SurfaceFleetLocations):
            message = "surface fleet location request requires previous locations"
            raise TypeError(message)
        if type(self.fleet_2_enabled) is not bool or type(self.poor_map_data) is not bool:
            message = "surface fleet location request flags must be booleans"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class SurfaceFleetObservation:
    found: bool
    current: bool

    def __post_init__(self) -> None:
        if type(self.found) is not bool or type(self.current) is not bool:
            message = "surface fleet observation values must be booleans"
            raise TypeError(message)


class FleetLocationContext(Protocol):
    @property
    def map(self) -> CampaignMap: ...

    @property
    def camera(self) -> GridLocation: ...

    def _observe_surface_fleet(self, grid: GridInfo) -> SurfaceFleetObservation: ...

    def _observe_current_fleet(self, grid: GridInfo) -> bool: ...

    def _observe_submarine(self, grid: GridInfo) -> bool: ...


class CampaignFleetLocator(Protocol):
    def locate_surface(
        self,
        context: FleetLocationContext,
        request: SurfaceFleetLocationRequest,
    ) -> SurfaceFleetLocations: ...

    def locate_submarine(
        self,
        context: FleetLocationContext,
        *,
        enabled: bool,
    ) -> GridLocation | None: ...


class _StandardCampaignFleetLocator(CampaignFleetLocator):
    @override
    def locate_surface(
        self,
        context: FleetLocationContext,
        request: SurfaceFleetLocationRequest,
    ) -> SurfaceFleetLocations:
        logger.hr("Find current fleet")
        fleets = self._surface_candidates(context, poor_map_data=request.poor_map_data)
        logger.info(f"Fleets: {fleets}")

        count = fleets.count
        if count == 1:
            return self._from_single(context, request, fleets[0])
        if count == 2:
            return self._from_pair(context, request.previous, fleets)
        return self._from_unexpected_count(context, request.previous, fleets)

    @staticmethod
    def _surface_candidates(
        context: FleetLocationContext,
        *,
        poor_map_data: bool,
    ) -> SelectedGrids[GridInfo]:
        if not poor_map_data:
            return context.map.select(is_fleet=True, is_spawn_point=True)
        return context.map.select(is_fleet=True)

    def _from_single(
        self,
        context: FleetLocationContext,
        request: SurfaceFleetLocationRequest,
        detected: GridInfo,
    ) -> SurfaceFleetLocations:
        if not request.fleet_2_enabled:
            return replace(request.previous, fleet_1=location_ensure(detected))

        logger.info("Fleet_2 not detected.")
        spawn_points = context.map.select(is_spawn_point=True)
        if request.poor_map_data and not spawn_points:
            return replace(request.previous, fleet_1=location_ensure(detected))
        if spawn_points.count == 2:
            return self._from_spawn_points(request.previous, detected, spawn_points)
        return self._from_cover(context, request.previous, detected)

    @staticmethod
    def _from_spawn_points(
        previous: SurfaceFleetLocations,
        detected: GridInfo,
        spawn_points: SelectedGrids[GridInfo],
    ) -> SurfaceFleetLocations:
        logger.info("Predict fleet to be spawn point")
        another = spawn_points.delete(SelectedGrids([detected]))[0]
        if detected.is_current_fleet:
            return replace(
                previous,
                fleet_1=location_ensure(detected),
                fleet_2=location_ensure(another),
            )
        return replace(
            previous,
            fleet_1=location_ensure(another),
            fleet_2=location_ensure(detected),
        )

    def _from_cover(
        self,
        context: FleetLocationContext,
        previous: SurfaceFleetLocations,
        detected: GridInfo,
    ) -> SurfaceFleetLocations:
        cover = context.map.grid_covered(detected, location=[(0, -1)])
        if detected.is_current_fleet and len(cover) and cover[0].is_spawn_point:
            return replace(
                previous,
                fleet_1=location_ensure(detected),
                fleet_2=location_ensure(cover[0]),
            )
        return self._locate_all_surface(context, previous)

    def _from_pair(
        self,
        context: FleetLocationContext,
        previous: SurfaceFleetLocations,
        fleets: SelectedGrids[GridInfo],
    ) -> SurfaceFleetLocations:
        current = context.map.select(is_current_fleet=True)
        if current.count == 1:
            return replace(
                previous,
                fleet_1=location_ensure(current[0]),
                fleet_2=location_ensure(fleets.delete(current)[0]),
            )
        return self._pair_by_prediction(context, previous, fleets)

    @staticmethod
    def _observe_current(context: FleetLocationContext, grid: GridInfo) -> bool:
        return context._observe_current_fleet(  # ruff:ignore[private-member-access] - context 只暴露定向观测原语。
            grid
        )

    def _pair_by_prediction(
        self,
        context: FleetLocationContext,
        previous: SurfaceFleetLocations,
        fleets: SelectedGrids[GridInfo],
    ) -> SurfaceFleetLocations:
        fleets = fleets.sort_by_camera_distance(context.camera)
        first, second = fleets[0], fleets[1]
        if self._observe_current(context, first):
            return replace(
                previous,
                fleet_1=location_ensure(first),
                fleet_2=location_ensure(second),
            )
        if self._observe_current(context, second):
            return replace(
                previous,
                fleet_1=location_ensure(second),
                fleet_2=location_ensure(first),
            )
        logger.warning("Current fleet not found")
        return replace(
            previous,
            fleet_1=location_ensure(first),
            fleet_2=location_ensure(second),
        )

    def _from_unexpected_count(
        self,
        context: FleetLocationContext,
        previous: SurfaceFleetLocations,
        fleets: SelectedGrids[GridInfo],
    ) -> SurfaceFleetLocations:
        locations = previous
        if fleets.count == 0:
            logger.warning("No fleets detected.")
            current = context.map.select(is_current_fleet=True)
            if current.count:
                locations = replace(locations, fleet_1=location_ensure(current[0]))
        else:
            logger.warning(f"Too many fleets: {fleets}.")
        return self._locate_all_surface(context, locations)

    @staticmethod
    def _observe_surface(
        context: FleetLocationContext,
        grid: GridInfo,
    ) -> SurfaceFleetObservation:
        return context._observe_surface_fleet(  # ruff:ignore[private-member-access] - context 只暴露定向观测原语。
            grid
        )

    def _locate_all_surface(
        self,
        context: FleetLocationContext,
        previous: SurfaceFleetLocations,
    ) -> SurfaceFleetLocations:
        logger.hr("Find all fleets")
        locations = previous
        queue = context.map.select(is_spawn_point=True)
        while queue:
            queue = queue.sort_by_camera_distance(context.camera)
            observation = self._observe_surface(context, queue[0])
            if observation.found:
                if observation.current:
                    locations = replace(locations, fleet_1=location_ensure(queue[0]))
                else:
                    locations = replace(locations, fleet_2=location_ensure(queue[0]))
            queue = queue[1:]
        return locations

    @override
    def locate_submarine(
        self,
        context: FleetLocationContext,
        *,
        enabled: bool,
    ) -> GridLocation | None:
        if type(enabled) is not bool:
            message = "submarine location enabled flag must be a boolean"
            raise TypeError(message)
        if not (enabled and context.map.select(is_submarine_spawn_point=True)):
            return None

        submarines = context.map.select(is_submarine=True)
        count = submarines.count
        if count == 1:
            location = location_ensure(submarines[0])
        elif count == 0:
            location = self._locate_missing_submarine(context)
        else:
            logger.warning(f"Too many submarines: {submarines}.")
            location = self._locate_all_submarines(context)

        if location is None:
            logger.warning("Unable to find submarine, assume it is at map center")
            shape = context.map.shape
            center = (shape[0] // 2, shape[1] // 2)
            location = location_ensure(context.map.select(is_land=False).sort_by_camera_distance(center)[0])

        logger.info(f"Submarine: {location2node(location)}")
        return location

    def _locate_missing_submarine(self, context: FleetLocationContext) -> GridLocation | None:
        logger.info("No submarine found")
        spawn_points = context.map.select(is_submarine_spawn_point=True)
        if spawn_points.count == 1:
            logger.info(f"Predict the only submarine spawn point {spawn_points[0]} as submarine")
            return location_ensure(spawn_points[0])

        logger.info(f"Having multiple submarine spawn points: {spawn_points}")
        covered: SelectedGrids[GridInfo] = SelectedGrids([])
        for grid in spawn_points:
            covered = covered.add(context.map.grid_covered(grid, location=[(0, 1)]))
        covered = covered.filter(lambda grid: grid.is_enemy or grid.is_fleet or grid.is_siren or grid.is_boss)
        if covered.count == 1:
            spawn_points = context.map.grid_covered(covered[0], location=[(0, -1)])
            logger.info(f"Submarine {spawn_points[0]} covered by {covered[0]}")
            return location_ensure(spawn_points[0])

        logger.info("Found multiple submarine spawn points being covered")
        return self._locate_all_submarines(context)

    @staticmethod
    def _observe_submarine(context: FleetLocationContext, grid: GridInfo) -> bool:
        return context._observe_submarine(  # ruff:ignore[private-member-access] - context 只暴露定向观测原语。
            grid
        )

    def _locate_all_submarines(self, context: FleetLocationContext) -> GridLocation | None:
        logger.hr("Find all submarines")
        queue = context.map.select(is_submarine_spawn_point=True)
        while queue:
            queue = queue.sort_by_camera_distance(context.camera)
            if self._observe_submarine(context, queue[0]):
                return location_ensure(queue[0])
            queue = queue[1:]
        return None


STANDARD_CAMPAIGN_FLEET_LOCATOR: CampaignFleetLocator = _StandardCampaignFleetLocator()
