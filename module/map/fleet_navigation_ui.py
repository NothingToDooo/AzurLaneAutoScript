from typing import TYPE_CHECKING

from module.logger import logger
from module.map import assets as map_assets
from module.map.fleet_navigation import NavigationCombatOutcome, NavigationTimer
from module.map.map_scanner import MapScanRequest, MovableEnemyRules, MovableScanRequest
from module.map.map_spawn_gap import MapSpawnProgress

if TYPE_CHECKING:
    from typing import Literal

    from module.handler.map_transition_ui import MapTransitionUi
    from module.map.fleet import Fleet
    from module.map.map_observer import CampaignMapObserver
    from module.map.map_scanner import MovableEnemySnapshot
    from module.map.type_alias import GridLocation, GridMode
    from module.map_detection.grid import Grid


class CampaignFleetSwitchUi:
    """把舰队切换状态机所需的 UI 原子操作投影到 Campaign runtime。"""

    def __init__(self, runtime: Fleet, transition_ui: MapTransitionUi) -> None:
        self._runtime = runtime
        self._transition_ui = transition_ui

    def navigation_screenshot(self) -> None:
        self._runtime.device.screenshot()

    def navigation_handle_switch_interruption(self) -> bool:
        if self._runtime.handle_story_skip():
            return True
        return self._transition_ui.handle_stage_return(self._runtime)

    def navigation_detect_shown_fleet(self) -> int:
        runtime = self._runtime
        if runtime.appear(map_assets.FLEET_NUM_1, offset=(20, 20)):
            return 1
        if runtime.appear(map_assets.FLEET_NUM_2, offset=(20, 20)):
            return 2
        logger.warning("Unknown fleet current index, use 1 by default")
        return 1

    def navigation_click_switch(self) -> bool:
        return self._runtime.appear_then_click(map_assets.SWITCH_OVER)

    def navigation_sleep_after_switch(self) -> None:
        self._runtime.device.sleep((1, 1.5))

    def navigation_focus_after_activation(self, location: GridLocation) -> None:
        self._runtime.camera = location
        self._runtime.update()

    def navigation_refresh_after_activation(self, shown_index: int) -> None:
        runtime = self._runtime
        runtime.hp_get()
        runtime.lv_get()
        runtime.handle_strategy(index=shown_index)


class CampaignFleetMovementUi:
    """封装导航状态机需要的截图、战斗和地图观察副作用。"""

    def __init__(self, runtime: Fleet, observer: CampaignMapObserver) -> None:
        self._runtime = runtime
        self._observer = observer

    def navigation_withdraw_if_needed(self) -> None:
        if self._runtime.hp_retreat_triggered():
            self._runtime.withdraw()

    def navigation_click_target(self, location: GridLocation, sight: tuple[int, int, int, int]) -> Grid:
        runtime = self._runtime
        runtime.in_sight(location, sight=sight)
        runtime.focus_to_grid_center()
        grid = runtime.convert_global_to_local(location)
        runtime.ambush_color_initial()
        runtime.enemy_searching_color_initial()
        runtime.device.click(grid)
        return grid

    def navigation_refresh_target(self, grid: Grid, *, portal: bool) -> Grid:
        runtime = self._runtime
        runtime.device.screenshot()
        runtime.view.update(image=runtime.device.image)
        if not portal:
            return grid
        runtime.update(allow_error=True)
        return runtime.view[runtime.view.center_loca]

    def navigation_handle_fleet_lock(self, walk_timeout: NavigationTimer) -> None:
        runtime = self._runtime
        if not runtime.config.Campaign_UseFleetLock or runtime.is_in_map():
            return
        if runtime.handle_retirement():
            runtime.map_offensive()
            walk_timeout.reset()
        if runtime.handle_combat_low_emotion():
            walk_timeout.reset()

    def navigation_handle_combat(
        self,
        expected: str,
        location: GridLocation,
    ) -> NavigationCombatOutcome | None:
        runtime = self._runtime
        if not runtime.combat_appear():
            return None
        runtime.combat(
            expected_end=runtime.navigation_expected_end(expected),
            fleet_index=runtime.navigation.shown_index,
            submarine_mode=self._submarine_mode(expected),
        )
        runtime.hp_get()
        runtime.lv_get(after_battle=True)
        runtime.battle_count += 1
        runtime.fleet_ammo -= 1
        destination = runtime.map[location]
        if "siren" in expected or (runtime.config.MAP_HAS_MOVABLE_ENEMY and not expected):
            runtime.siren_count += 1
        elif destination.may_enemy:
            destination.is_cleared = True

        if self._observer.combat.camera_repositioned_after_combat(runtime, destination):
            runtime.handle_boss_appear_refocus()
            if sum(runtime.hp) < 0.01:
                logger.warning("Empty HP on all slots, trying hp_get again")
                runtime.hp_get()
        if runtime.config.MAP_FOCUS_ENEMY_AFTER_BATTLE:
            runtime.camera = location
            runtime.update()
        grid = runtime.convert_global_to_local(location)
        needs_retry = not (grid.predict_fleet() and grid.predict_current_fleet())
        return NavigationCombatOutcome(
            grid=grid,
            battle_count=runtime.battle_count,
            arrived=not runtime.config.MAP_HAS_MOVABLE_ENEMY,
            needs_retry=needs_retry,
        )

    def navigation_handle_ambush(self, grid: Grid) -> bool:
        del grid
        runtime = self._runtime
        if not runtime.handle_ambush():
            return False
        runtime.hp_get()
        runtime.lv_get(after_battle=True)
        runtime.view.update(image=runtime.device.image)
        return True

    def navigation_handle_mystery(self, grid: Grid) -> str | None:
        runtime = self._runtime
        mystery = runtime.handle_mystery(button=grid)
        if mystery is None:
            return None
        if mystery.counts_toward_mystery:
            runtime.mystery_count += 1
        return mystery.kind.value

    def navigation_handle_cat_attack(self) -> bool:
        return self._runtime.handle_map_cat_attack()

    def navigation_handle_guild_popup(self) -> bool:
        return self._runtime.handle_guild_popup_cancel()

    def navigation_handle_walk_out_of_step(self) -> bool:
        return self._runtime.handle_walk_out_of_step()

    def navigation_handle_story(self, expected: str) -> bool:
        return expected == "story" and self._runtime.handle_story_skip()

    def navigation_is_in_map(self) -> bool:
        return self._runtime.is_in_map()

    def navigation_recover_walk(self, *, skip_first_update: bool) -> None:
        self._runtime.ensure_edge_insight(skip_first_update=skip_first_update)

    def navigation_click_grid(self, grid: Grid) -> None:
        self._runtime.device.click(grid)

    def navigation_predict(self) -> None:
        self._runtime.predict()

    def navigation_handle_carrier_spawn(self) -> None:
        runtime = self._runtime
        previous = runtime.map.layout.select(is_enemy=True)
        runtime.full_scan(MapScanRequest(progress=self._spawn_progress(mode="carrier")))
        spawned = runtime.map.layout.select(is_enemy=True).delete(previous)
        logger.info(f"Carrier spawn: {spawned}")

    def navigation_scan_movable(self, snapshot: MovableEnemySnapshot, *, enemy_cleared: bool) -> None:
        runtime = self._runtime
        self._observer.scanner.full_scan_movable(
            runtime,
            MovableScanRequest(
                snapshot=snapshot,
                progress=self._spawn_progress(),
                rules=MovableEnemyRules(
                    siren=runtime.config.MAP_HAS_MOVABLE_ENEMY,
                    normal_enemy=runtime.config.MAP_HAS_MOVABLE_NORMAL_ENEMY,
                    enemy_template=bool(runtime.config.MAP_ENEMY_TEMPLATE),
                    wall=runtime.config.MAP_HAS_WALL,
                    portal=runtime.config.MAP_HAS_PORTAL,
                    ambush=runtime.config.MAP_HAS_AMBUSH,
                    siren_step=runtime.config.MOVABLE_ENEMY_FLEET_STEP,
                ),
                enemy_cleared=enemy_cleared,
            ),
        )

    @staticmethod
    def navigation_after_arrival(location: GridLocation) -> None:
        del location

    def navigation_set_camera(self, location: GridLocation) -> None:
        self._runtime.camera = location

    def _spawn_progress(self, mode: GridMode = "normal") -> MapSpawnProgress:
        runtime = self._runtime
        return MapSpawnProgress(
            battle_count=runtime.battle_count,
            mystery_count=runtime.mystery_count,
            siren_count=runtime.siren_count,
            carrier_count=runtime.carrier_count,
            mode=mode,
        )

    def _submarine_mode(self, expected: str) -> Literal["every_combat", "do_not_use"] | None:
        if not self._runtime.is_call_submarine_at_boss:
            return None
        return "every_combat" if "boss" in expected else "do_not_use"


class CampaignSubmarineMovementUi:
    """封装潜艇移动模式的页面进出和视觉刷新。"""

    def __init__(self, runtime: Fleet) -> None:
        self._runtime = runtime

    def navigation_click_submarine_target(
        self,
        location: GridLocation,
        sight: tuple[int, int, int, int],
    ) -> Grid:
        runtime = self._runtime
        runtime.in_sight(location, sight=sight)
        runtime.focus_to_grid_center()
        grid = runtime.convert_global_to_local(location)
        runtime.device.click(grid)
        return grid

    def navigation_refresh_submarine_target(self, grid: Grid) -> None:
        del grid
        runtime = self._runtime
        runtime.device.screenshot()
        runtime.view.update(image=runtime.device.image)

    def navigation_submarine_open(self) -> None:
        self._runtime.strategy_open()
        self._runtime.strategy_submarine_move_enter()

    def navigation_submarine_confirm(self) -> None:
        self._runtime.strategy_submarine_move_confirm()

    def navigation_submarine_cancel(self) -> None:
        self._runtime.strategy_submarine_move_cancel()

    def navigation_submarine_finish(self) -> None:
        self._runtime.strategy_set_execute(sub_view=False)
        self._runtime.strategy_close()
