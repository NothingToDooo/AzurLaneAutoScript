from typing import TYPE_CHECKING, Literal

import numpy as np

from module.exception import MapDetectionError
from module.handler.ambush import AmbushHandler
from module.logger import logger
from module.map.camera import Camera
from module.map.fleet_locator import (
    SurfaceFleetLocationRequest,
    SurfaceFleetLocations,
    SurfaceFleetObservation,
)
from module.map.fleet_navigation import (
    FleetNavigationController,
    FleetNavigationRules,
    FleetNavigationServices,
)
from module.map.fleet_navigation_ui import (
    CampaignFleetMovementUi,
    CampaignFleetSwitchUi,
    CampaignSubmarineMovementUi,
)
from module.map.fleet_turn import FleetTurnController, FleetTurnRules
from module.map.map_scanner import MapScannerRules, MapScanRequest
from module.map.map_spawn_gap import MapSpawnGapPredictor, MapSpawnProgress

if TYPE_CHECKING:
    from module.combat.combat import CombatEnd
    from module.map.map_base import CampaignMap
    from module.map.type_alias import GridLocation, GridMode
    from module.map_detection.grid_info import GridInfo


class Fleet(Camera, AmbushHandler):
    battle_count = 0
    mystery_count = 0
    siren_count = 0
    fleet_ammo = 5
    ammo_count = 3
    _turn_controller: FleetTurnController
    navigation: FleetNavigationController
    map_spawn_gap_predictor: MapSpawnGapPredictor
    map_scanner_rules: MapScannerRules

    @property
    def configured_boss_fleet(self) -> int:
        """返回当前运行实例采用的 boss 舰队配置。"""

        return self.config.fleet_boss

    def _boss_fleet_index(self) -> Literal[1, 2]:
        configured = self.configured_boss_fleet
        if configured == 1:
            return 1
        if configured == 2:
            return 2
        message = f"boss fleet index must be 1 or 2, got {configured}"
        raise ValueError(message)

    def _fleets_are_reversed(self) -> bool:
        return bool(
            self.config.fleet_2
            and self.config.Fleet_FleetOrder in {"fleet1_boss_fleet2_mob", "fleet1_standby_fleet2_all"}
        )

    @staticmethod
    def _navigation_walk_sight() -> tuple[int, int, int, int] | None:
        return None

    def _active_hp_fleet_index(self) -> int:
        return self.navigation.current_index

    def _build_navigation_movement_ui(self) -> CampaignFleetMovementUi:
        return CampaignFleetMovementUi(self, self._map_observer)

    def navigation_expected_end(self, expected: str) -> CombatEnd | None:
        """根据刷新表推断导航触发战斗后的地图页面状态。"""
        for data in self.map.spawn_data:
            if data.get("battle") == self.battle_count and "boss" in expected:
                return "in_stage"
            if data.get("battle") == self.battle_count + 1:
                if data.get("enemy", 0) + data.get("siren", 0) + data.get("boss", 0) > 0:
                    return "with_searching"
                return "no_searching"
        if "boss" in expected:
            return "in_stage"
        matched = any(data.get("battle") == self.battle_count + 1 for data in self.map.spawn_data)
        if not self.map.spawn_data or matched:
            return None
        return "no_searching"

    def _navigation_rules(self) -> FleetNavigationRules:
        return FleetNavigationRules(
            fleet_2_enabled=bool(self.config.fleet_2),
            boss_fleet_index=self._boss_fleet_index(),
            fleets_reversed=self._fleets_are_reversed(),
            fleet_step_enabled=self.config.MAP_HAS_FLEET_STEP,
            fleet_1_step=self.config.Fleet_Fleet1Step,
            fleet_2_step=self.config.Fleet_Fleet2Step,
            portal=self.config.MAP_HAS_PORTAL,
            maze=self.config.MAP_HAS_MAZE,
            ambush=self.config.MAP_HAS_AMBUSH,
            movable_enemy=self.config.MAP_HAS_MOVABLE_ENEMY,
            decoy_enemy=self.config.MAP_HAS_DECOY_ENEMY,
            walk_use_current_fleet=self.config.MAP_WALK_USE_CURRENT_FLEET,
            submarine_mode=self.config.Submarine_Mode,
            land_based=self.config.MAP_HAS_LAND_BASED,
            fortress=self.config.MAP_HAS_FORTRESS,
            call_submarine_at_boss=self.is_call_submarine_at_boss,
            submarine_distance_to_boss=self.config.Submarine_DistanceToBoss,
            walk_sight=self._navigation_walk_sight(),
        )

    def _assemble_navigation(self) -> None:
        self.navigation = FleetNavigationController(
            self._navigation_rules(),
            FleetNavigationServices(
                map=self.map,
                turn_controller=self._turn_controller,
                switch_ui=CampaignFleetSwitchUi(self, self._map_transition_ui),
                movement_ui=self._build_navigation_movement_ui(),
                submarine_ui=CampaignSubmarineMovementUi(self),
            ),
        )

    def _spawn_progress(self, mode: GridMode = "normal") -> MapSpawnProgress:
        return MapSpawnProgress(
            battle_count=self.battle_count,
            mystery_count=self.mystery_count,
            siren_count=self.siren_count,
            carrier_count=self.carrier_count,
            mode=mode,
        )

    def full_scan(self, request: MapScanRequest | None = None) -> None:
        """通过当前 profile 的 scanner 执行一次完整地图扫描。"""
        self._map_observer.scanner.full_scan(
            self,
            request or MapScanRequest(progress=self._spawn_progress()),
        )

    def _observe_surface_fleet(self, grid: GridInfo) -> SurfaceFleetObservation:
        self.in_sight(grid, sight=(-1, 0, 1, 2))
        local = self.convert_global_to_local(grid)
        found = local.predict_fleet()
        return SurfaceFleetObservation(found=found, current=found and local.predict_current_fleet())

    def _observe_current_fleet(self, grid: GridInfo) -> bool:
        self.in_sight(grid, sight=(-1, 0, 1, 2))
        return self.convert_global_to_local(grid).predict_current_fleet()

    def _observe_submarine(self, grid: GridInfo) -> bool:
        self.in_sight(grid, sight=(-2, -1, 2, -1))
        return self.convert_global_to_local(grid).predict_submarine()

    def map_init(self, map_: CampaignMap | None) -> None:
        """进入地图后、执行任何地图操作前调用。"""
        logger.hr("Map init")
        self.map_data_init(map_)
        self.map_control_init()

    def map_data_init(self, map_: CampaignMap | None) -> None:
        """按配置和地图状态初始化数据，不截图也不点击。"""
        if map_ is None:
            message = "普通地图初始化需要 CampaignMap"
            raise ValueError(message)
        self.battle_count = 0
        self.mystery_count = 0
        self.carrier_count = 0
        self.siren_count = 0
        self.ammo_count = 3
        self.map = map_
        self.map.reset()
        self.handle_clear_mode_config_cover()
        self.map.poor_map_data = self.config.POOR_MAP_DATA
        self.map.load_map_data(use_loop=self.map_is_clear_mode)
        self.map.load_spawn_data(use_loop=self.map_is_clear_mode)
        self.map.topology.rebuild(
            wall=self.config.MAP_HAS_WALL,
            portal=self.config.MAP_HAS_PORTAL,
        )
        self.map.load_mechanism(
            land_based=self.config.MAP_HAS_LAND_BASED,
            maze=self.config.MAP_HAS_MAZE,
            fortress=self.config.MAP_HAS_FORTRESS,
            bouncing_enemy=self.config.MAP_HAS_BOUNCING_ENEMY,
        )
        self.map_spawn_gap_predictor = MapSpawnGapPredictor(self.map)
        self.map_scanner_rules = MapScannerRules(
            decoy_enemy=bool(self.config.MAP_HAS_DECOY_ENEMY),
            fleet_2_enabled=bool(self.config.fleet_2),
        )
        self._turn_controller = FleetTurnController(
            FleetTurnRules(
                movable_enemy=self.config.MAP_HAS_MOVABLE_ENEMY,
                movable_normal_enemy=self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY,
                maze=self.config.MAP_HAS_MAZE,
                bouncing_enemy=self.config.MAP_HAS_BOUNCING_ENEMY,
                movable_enemy_turns=self.config.MOVABLE_ENEMY_TURN,
                movable_normal_enemy_turns=self.config.MOVABLE_NORMAL_ENEMY_TURN,
                enemy_move_wait=self.config.MAP_SIREN_MOVE_WAIT,
            ),
            self.map,
        )
        self._assemble_navigation()

    def map_control_init(self) -> None:
        """初始化阵型、血量、等级和相机，并执行首次地图扫描。"""
        self.update()
        reversed_fleets = self._fleets_are_reversed()
        if not self.map_is_hard_mode and reversed_fleets:
            logger.warning(f"You shouldn't use a reversed fleet order ({self.config.Fleet_FleetOrder}) in normal mode.")
            logger.warning(
                'Please reverse your Fleet 1 and Fleet 2, use "fleet1_mob_fleet2_boss" or "fleet1_all_fleet2_standby"'
            )
        self.navigation.activate(2 if reversed_fleets else 1)
        self.handle_strategy(index=self.navigation.shown_index)
        self.hp_reset()
        self.hp_get()
        self.lv_reset()
        self.lv_get()
        self.ensure_edge_insight(preset=self.map.in_map_swipe_preset_data)
        self.handle_info_bar()  # “Changed to fleet 2”信息条会遮住弹药图标。
        self.full_scan(
            MapScanRequest(
                must_scan=self.map.layout.camera_data_spawn_point,
                progress=self._spawn_progress(mode="init"),
            )
        )
        previous = self.navigation.snapshot
        surface_locations = self._map_observer.fleet_locator.locate_surface(
            self,
            SurfaceFleetLocationRequest(
                previous=SurfaceFleetLocations(
                    fleet_1=previous.fleet_1,
                    fleet_2=previous.fleet_2,
                ),
                fleet_2_enabled=bool(self.config.fleet_2),
                poor_map_data=self.map.poor_map_data,
            ),
        )
        self.navigation.seed_surface(
            fleet_1=surface_locations.fleet_1,
            fleet_2=surface_locations.fleet_2,
        )
        self.navigation.show()
        submarine_location = self._map_observer.fleet_locator.locate_submarine(
            self,
            enabled=bool(self.config.submarine),
        )
        self.navigation.seed_submarine(submarine_location or ())
        self.navigation.rebuild_paths()
        self.map.pathfinder.show_cost()
        self._turn_controller.initialize(self.battle_count)

    def handle_clear_mode_config_cover(self) -> bool:
        if not self.map_is_clear_mode:
            return False

        if self.config.POOR_MAP_DATA and self.map.is_map_data_poor:
            self.config.POOR_MAP_DATA = False
        self.map.fortress_data = [(), ()]
        self.map.bouncing_enemy_data = []
        return True

    def handle_boss_appear_refocus(self, preset: GridLocation | None = None) -> None:
        """Boss 出现并触发镜头移动后，按 (x, y) 滑动预设恢复原相机位置。"""
        camera = self.camera
        if preset is None:
            preset = self.config.MAP_BOSS_APPEAR_REFOCUS_SWIPE

        if preset is not None and np.linalg.norm(preset) > 0:
            try:
                self.update()
            except MapDetectionError:
                logger.info(f"MapDetectionError occurs after boss appear, trying swipe preset {preset}")
                self.map_swipe(preset)
            self.ensure_edge_insight()
        else:
            self.update()
            self.ensure_edge_insight()

        logger.info("Refocus to previous camera position.")
        self.focus_to(camera)

    def fleet_checked_reset(self) -> None:
        self.map_fleet_checked = False
        self.fleet_1_formation_fixed = False
        self.fleet_2_formation_fixed = False
