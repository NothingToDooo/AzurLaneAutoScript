import itertools
from dataclasses import dataclass

import numpy as np

from module.base.timer import Timer
from module.exception import MapDetectionError, MapEnemyMoved, MapWalkError
from module.handler.ambush import AmbushHandler
from module.logger import logger
from module.map.camera import Camera, FullScanOptions
from module.map.map_base import SelectedGrids, location2node, location_ensure
from module.map.utils import match_movable

WALK_OUT_OF_STEP_MESSAGE = "walk_out_of_step"


@dataclass(slots=True)
class _GotoState:
    location: object
    expected: str
    grid: object
    is_portal: bool
    may_submarine_icon: bool
    extra: float
    result: str = "nothing"
    result_mystery: str = ""
    arrived: bool = False
    arrive_timer: object = None
    arrive_unexpected_timer: object = None
    ambushed_retry: object = None
    walk_timeout: object = None


class Fleet(Camera, AmbushHandler):
    fleet_1_location = ()
    fleet_2_location = ()
    fleet_submarine_location = ()
    battle_count = 0
    mystery_count = 0
    siren_count = 0
    fleet_ammo = 5
    ammo_count = 3

    @property
    def fleet_1(self):
        if self.fleet_current_index != 1:
            self.fleet_ensure(index=1)
        return self

    @fleet_1.setter
    def fleet_1(self, value):
        self.fleet_1_location = value

    @property
    def fleet_2(self):
        if self.config.FLEET_2 and self.fleet_current_index != 2:
            self.fleet_ensure(index=2)
        return self

    @fleet_2.setter
    def fleet_2(self, value):
        self.fleet_2_location = value

    @property
    def fleet_submarine(self):
        return self

    @fleet_submarine.setter
    def fleet_submarine(self, value):
        self.fleet_submarine_location = value

    @property
    def fleet_current(self):
        if self.fleet_current_index == 2:
            return self.fleet_2_location
        return self.fleet_1_location

    @fleet_current.setter
    def fleet_current(self, value):
        if self.fleet_current_index == 2:
            self.fleet_2_location = value
        else:
            self.fleet_1_location = value

    @property
    def fleet_boss(self):
        if self.config.FLEET_BOSS == 2 and self.config.FLEET_2:
            return self.fleet_2
        return self.fleet_1

    @property
    def fleet_boss_index(self):
        if self.config.FLEET_BOSS == 2 and self.config.FLEET_2:
            return 2
        return 1

    @property
    def fleet_step(self):
        if not self.config.MAP_HAS_FLEET_STEP:
            return 0
        if self.fleet_current_index == 2:
            if self.fleets_reversed:
                return self.config.Fleet_Fleet1Step
            return self.config.Fleet_Fleet2Step
        if self.fleets_reversed:
            return self.config.Fleet_Fleet2Step
        return self.config.Fleet_Fleet1Step

    def fleet_ensure(self, index):
        if self.fleet_set(index=index):
            self.camera = self.fleet_current
            self.update()
            self.find_path_initial()
            self.map.show_cost()
            self.show_fleet()
            self.hp_get()
            self.lv_get()
            self.handle_strategy(index=self.fleet_show_index)
            return True
        return False

    def switch_to(self):
        pass

    def __init__(self, *args, **kwargs):
        self.round = 0
        self.enemy_round = {}
        super().__init__(*args, **kwargs)

    def round_next(self):
        """
        Call this method after fleet arrived.
        """
        if not self.config.MAP_HAS_MOVABLE_ENEMY and not self.config.MAP_HAS_MAZE:
            return False
        self.round += 1
        logger.info(f"Round: {self.round}, enemy_round: {self.enemy_round}")
        return True

    def round_battle(self):
        """
        清理敌人后更新敌方行动轮次。
        """
        if not self.config.MAP_HAS_MOVABLE_ENEMY:
            return False
        if not self.map.select(is_siren=True):
            if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
                if not self.map.select(is_enemy=True):
                    self.enemy_round = {}
            else:
                self.enemy_round = {}
        try:
            data = self.map.spawn_data[self.battle_count]
        except IndexError:
            data = {}
        enemy = data.get("siren", 0)
        if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
            enemy += data.get("enemy", 0)
        if enemy > 0:
            r = self.round
            self.enemy_round[r] = self.enemy_round.get(r, 0) + enemy
        return True

    def round_reset(self):
        """
        Call this method after entering map.
        """
        self.round = 0
        self.enemy_round = {}

    @property
    def round_enemy_turn(self):
        """
        Returns:
            tuple[int]: Enemy moves once after player move X times.
                        It's a tuple because different enemy may have different X.
        """
        if self.config.MAP_HAS_MOVABLE_ENEMY:
            if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
                return tuple(set(list(self.config.MOVABLE_ENEMY_TURN) + list(self.config.MOVABLE_NORMAL_ENEMY_TURN)))
            return self.config.MOVABLE_ENEMY_TURN
        if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
            return self.config.MOVABLE_NORMAL_ENEMY_TURN
        return ()

    @property
    def round_is_new(self):
        """
        Usually, MOVABLE_ENEMY_TURN = 2.
        So a walk round is `player - player - enemy`, player moves twice, enemy moves once.

        Different sirens have different MOVABLE_ENEMY_TURN:
            2: Non-siren elite, SIREN_CL
            3: SIREN_CA

        Returns:
            bool: If it's a new walk round, which means enemies have moved.
        """
        if not self.config.MAP_HAS_MOVABLE_ENEMY:
            return False
        for enemy in self.enemy_round:
            for turn in self.round_enemy_turn:
                if self.round - enemy > 0 and (self.round - enemy) % turn == 0:
                    return True

        return False

    @property
    def round_wait(self):
        """
        Returns:
            float: Seconds to wait enemies moving.
        """
        second = 0
        if self.config.MAP_HAS_MOVABLE_ENEMY:
            count = 0
            for enemy, c in self.enemy_round.items():
                for turn in self.round_enemy_turn:
                    if self.round + 1 - enemy > 0 and (self.round + 1 - enemy) % turn == 0:
                        count += c
                        break
            second += count * self.config.MAP_SIREN_MOVE_WAIT

        if self.config.MAP_HAS_MAZE and (self.round + 1) % 3 == 0:
            second += 1.0

        if self.config.MAP_HAS_BOUNCING_ENEMY:
            for route in self.map.bouncing_enemy_data:
                if route.select(may_bouncing_enemy=True):
                    second += self.config.MAP_SIREN_MOVE_WAIT

        return second

    @property
    def round_maze_changed(self):
        """
        Returns:
            bool: If maze changed at the start of this round.
        """
        if not self.config.MAP_HAS_MAZE:
            return False
        return self.round != 0 and self.round % 3 == 0

    def maze_active_on(self, grid):
        """
        Args:
            grid:

        Returns:
            bool: If maze wall is on a the specific grid.
        """
        if not self.config.MAP_HAS_MAZE:
            return False

        grid = self.map[location_ensure(grid)]
        if not grid.is_maze:
            return False
        return self.round % self.map.maze_round in grid.maze_round

    movable_before: SelectedGrids
    movable_before_normal: SelectedGrids

    @property
    def _walk_sight(self):
        sight = self.map.camera_sight
        return (sight[0], 0, sight[2], sight[3])

    def _goto_walk_extra(self, grid):
        extra = 0
        if self.config.Submarine_Mode in ["hunt_only", "hunt_and_boss"]:
            extra += 4.5
        if self.config.MAP_HAS_LAND_BASED and grid.is_mechanism_trigger:
            extra += grid.mechanism_wait
        return extra

    def _goto_click_target(self, location):
        self.fleet_ensure(self.fleet_current_index)
        self.in_sight(location, sight=self._walk_sight)
        self.focus_to_grid_center()
        grid = self.convert_global_to_local(location)

        self.ambush_color_initial()
        self.enemy_searching_color_initial()
        grid.__str__ = location
        self.device.click(grid)
        return grid

    def _goto_state(self, location, expected, grid, is_portal, may_submarine_icon):
        extra = self._goto_walk_extra(grid)
        return _GotoState(
            location=location,
            expected=expected,
            grid=grid,
            is_portal=is_portal,
            may_submarine_icon=may_submarine_icon,
            extra=extra,
            arrive_timer=Timer(0.5 + self.round_wait + extra, count=2),
            arrive_unexpected_timer=Timer(1.5 + self.round_wait + extra, count=6),
            ambushed_retry=Timer(0.5 + self.round_wait + extra, count=2),
            walk_timeout=Timer(20).start(),
        )

    def _goto_handle_fleet_lock(self, state):
        if not self.config.Campaign_UseFleetLock or self.is_in_map():
            return
        if self.handle_retirement():
            self.map_offensive()
            state.walk_timeout.reset()
        if self.handle_combat_low_emotion():
            state.walk_timeout.reset()

    def _goto_handle_combat(self, state):
        if not self.combat_appear():
            return
        self.combat(
            expected_end=self._expected_end(state.expected),
            fleet_index=self.fleet_show_index,
            submarine_mode=self._submarine_mode(state.expected),
        )
        self.hp_get()
        self.lv_get(after_battle=True)
        state.arrived = not self.config.MAP_HAS_MOVABLE_ENEMY
        state.result = "combat"
        self.battle_count += 1
        self.fleet_ammo -= 1
        if "siren" in state.expected or (self.config.MAP_HAS_MOVABLE_ENEMY and not state.expected):
            self.siren_count += 1
        elif self.map[state.location].may_enemy:
            self.map[state.location].is_cleared = True

        if self.catch_camera_repositioning():
            self.handle_boss_appear_refocus()
            if sum(self.hp) < 0.01:
                logger.warning("Empty HP on all slots, trying hp_get again")
                self.hp_get()
        if self.config.MAP_FOCUS_ENEMY_AFTER_BATTLE:
            self.camera = state.location
            self.update()
        state.grid = self.convert_global_to_local(state.location)
        state.arrive_timer = Timer(0.5 + state.extra, count=2)
        state.arrive_unexpected_timer = Timer(1.5 + state.extra, count=6)
        state.walk_timeout.reset()
        if not (state.grid.predict_fleet() and state.grid.predict_current_fleet()):
            state.ambushed_retry.start()

    def _goto_handle_ambush(self, state):
        if not self.handle_ambush():
            return
        self.hp_get()
        self.lv_get(after_battle=True)
        state.walk_timeout.reset()
        self.view.update(image=self.device.image)
        if not (state.grid.predict_fleet() and state.grid.predict_current_fleet()):
            state.ambushed_retry.start()

    def _goto_handle_mystery(self, state):
        mystery = self.handle_mystery(button=state.grid)
        if not mystery:
            return
        self.mystery_count += 1
        state.result = "mystery"
        state.result_mystery = mystery

    def _goto_handle_cat_attack(self, state):
        if not self.handle_map_cat_attack():
            return False
        # Already arrive, combat will appear later, but still need to wait siren moving
        state.arrive_timer.reset()
        state.arrive_unexpected_timer.reset()
        state.walk_timeout.reset()
        return True

    def _goto_handle_guild_popup(self, state):
        # Usually handled in combat_status, but sometimes delayed until after battle on slow PCs.
        if not self.handle_guild_popup_cancel():
            return False
        state.walk_timeout.reset()
        return True

    def _goto_arrive_prediction(self, state):
        if not self.is_in_map():
            return "", False
        if not state.may_submarine_icon and state.grid.predict_fleet():
            return "(is_fleet)", True
        if state.may_submarine_icon and state.grid.predict_current_fleet():
            return "(may_submarine_icon, is_current_fleet)", True
        if (
            self.config.MAP_WALK_USE_CURRENT_FLEET
            and state.expected != "combat_boss"
            and not ("combat" in state.expected and state.grid.may_boss)
            and (state.grid.predict_fleet() or state.grid.predict_current_fleet())
        ):
            return "(MAP_WALK_USE_CURRENT_FLEET, is_current_fleet)", True
        if state.walk_timeout.reached() and state.grid.predict_current_fleet():
            return "(walk_timeout, is_current_fleet)", True
        return "", False

    def _goto_confirm_arrival(self, state):
        arrive_predict, arrive_checker = self._goto_arrive_prediction(state)
        if not arrive_checker:
            if state.arrive_timer.started():
                state.arrive_timer.reset()
            if state.arrive_unexpected_timer.started():
                state.arrive_unexpected_timer.reset()
            return False
        if not state.arrive_timer.started():
            logger.info(f"Arrive {location2node(state.location)} {arrive_predict}".strip())
        state.arrive_timer.start()
        state.arrive_unexpected_timer.start()
        if state.result == "nothing" and not state.arrive_timer.reached():
            return False
        if state.expected and state.result not in state.expected:
            if state.arrive_unexpected_timer.reached():
                logger.warning("Arrive with unexpected result")
            else:
                return False
        if state.is_portal:
            state.location = self.map[state.location].portal_link
            self.camera = state.location
        logger.info(
            f"Arrive {location2node(state.location)} confirm. Result: {state.result}. Expected: {state.expected}"
        )
        state.arrived = True
        return True

    def _goto_handle_story(self, state):
        if state.expected == "story" and self.handle_story_skip():
            state.result = "story"
            return True
        return False

    def _goto_retry_needed(self, state):
        if state.ambushed_retry.started() and state.ambushed_retry.reached():
            return True
        if not state.walk_timeout.reached():
            return False
        logger.warning("Walk timeout. Retrying.")
        self.predict()
        self.ensure_edge_insight(skip_first_update=False)
        return True

    def _goto_wait_arrival(self, state):
        while 1:
            self.device.screenshot()
            self.view.update(image=self.device.image)
            if state.is_portal:
                self.update(allow_error=True)
                state.grid = self.view[self.view.center_loca]

            self._goto_handle_fleet_lock(state)
            self._goto_handle_combat(state)
            self._goto_handle_ambush(state)
            self._goto_handle_mystery(state)

            if self._goto_handle_cat_attack(state):
                continue
            if self._goto_handle_guild_popup(state):
                continue
            if self.handle_walk_out_of_step():
                raise MapWalkError(WALK_OUT_OF_STEP_MESSAGE)
            if self._goto_confirm_arrival(state):
                break
            if self._goto_handle_story(state):
                continue
            if self._goto_retry_needed(state):
                break
        return state

    def _goto_finish(self, state):
        self.map[self.fleet_current].is_fleet = False
        self.map[state.location].wipe_out()
        self.map[state.location].is_fleet = True
        self.__setattr__(f"fleet_{self.fleet_current_index}_location", state.location)
        if state.result_mystery == "get_carrier":
            self.full_scan_carrier()
        if state.result == "combat":
            self.round_battle()
            self.predict()
        self.round_next()
        if self.round_is_new:
            if state.result != "combat":
                self.predict()
            self.full_scan_movable(enemy_cleared=state.result == "combat")
            self.find_path_initial()
            raise MapEnemyMoved
        if self.round_maze_changed:
            self.find_path_initial()
            raise MapEnemyMoved
        self.find_path_initial()
        if self.config.MAP_HAS_DECOY_ENEMY and state.result == "nothing" and state.expected == "combat":
            raise MapEnemyMoved

    def _goto(self, location, expected=""):
        """Goto a grid directly and handle ambush, air raid, mystery picked up, combat.

        Args:
            location (tuple, str, GridInfo): Destination.
            expected (str): Expected result on destination grid, such as 'combat', 'combat_siren', 'mystery'.
                Will give a waring if arrive with unexpected result.
        """
        location = location_ensure(location)
        self.movable_before = self.map.select(is_siren=True)
        self.movable_before_normal = self.map.select(is_enemy=True)
        if self.hp_retreat_triggered():
            self.withdraw()
        is_portal = self.map[location].is_portal
        # The upper grid is submarine, may mess up predict_fleet()
        may_submarine_icon = self.map.grid_covered(self.map[location], location=[(0, -1)])
        may_submarine_icon = may_submarine_icon and self.fleet_submarine_location == may_submarine_icon[0].location

        while 1:
            grid = self._goto_click_target(location)
            state = self._goto_state(location, expected, grid, is_portal, may_submarine_icon)
            self._goto_wait_arrival(state)
            if state.arrived:
                # Ammo grid needs to click again, otherwise the next click doesn't work.
                if self.map[state.location].may_ammo:
                    self.device.click(state.grid)
                break

        self._goto_finish(state)

    def goto(self, location, expected="", step_optimize=None, turning_optimize=None):
        """
        Args:
            location (tuple, str, GridInfo): Destination.
            expected (str): Expected result on destination grid, such as 'combat', 'combat_siren', 'mystery'.
                Will give a waring if arrive with unexpected result.
            step_optimize (bool): True to walk in fleet step
            turning_optimize (bool): True to optimize route to reduce ambushes
        """
        location = location_ensure(location)
        step_optimize = self._goto_step_optimize(step_optimize)
        turning_optimize = self._goto_turning_optimize(turning_optimize)

        if not step_optimize and not turning_optimize:
            self._goto(location, expected=expected)
            return

        nodes = self._goto_find_path(location, step_optimize=step_optimize, turning_optimize=turning_optimize)
        for node in nodes:
            self._goto_wait_maze(node)
            self._goto_path_node(node, nodes[-1], expected=expected)

    def _goto_step_optimize(self, step_optimize):
        if step_optimize is not None:
            return step_optimize
        if self.config.MAP_HAS_PORTAL or self.config.MAP_HAS_MAZE:
            return True
        return self.config.MAP_HAS_FLEET_STEP

    def _goto_turning_optimize(self, turning_optimize):
        if turning_optimize is None:
            return self.config.MAP_HAS_AMBUSH
        return turning_optimize

    def _goto_find_path(self, location, *, step_optimize, turning_optimize):
        step = self.fleet_step if step_optimize else 0
        return self.map.find_path(location, step=step, turning_optimize=turning_optimize)

    def _goto_wait_maze(self, node):
        if not self.maze_active_on(node):
            return

        logger.info(f"Maze is active on {location2node(node)}, bouncing to wait")
        for _ in range(10):
            grids = self.map[node].maze_nearby.delete(self.map.select(is_fleet=True))
            non_enemy_grids = grids.select(is_enemy=False)
            if non_enemy_grids:
                grids = non_enemy_grids
            grids = grids.sort("cost")
            self._goto(grids[0], expected="")

    def _goto_path_node(self, node, final_node, *, expected):
        node_expected = expected if node == final_node else ""
        try:
            self._goto(node, expected=node_expected)
        except MapWalkError:
            self._goto_retry_after_walk_error(node, expected=node_expected)

    def _goto_retry_after_walk_error(self, node, *, expected):
        logger.warning("Map walk error.")
        self.predict()
        self.ensure_edge_insight()
        nodes = self.map.find_path(node, step=1, turning_optimize=False)
        for retry_node in nodes:
            self._goto(retry_node, expected=expected)

    def find_path_initial(self):
        """
        Call this method after fleet moved or entered map.
        """
        if self.fleet_1_location:
            self.map[self.fleet_1_location].is_fleet = True
        if self.fleet_2_location:
            self.map[self.fleet_2_location].is_fleet = True
        location_dict = {}
        if self.fleet_2_location:
            location_dict[2] = self.fleet_2_location
        location_dict[1] = self.fleet_1_location
        # 解除要塞阻挡。
        if self.config.MAP_HAS_FORTRESS and not self.map.select(is_fortress=True):
            self.map.select(is_mechanism_block=True).set(is_mechanism_block=False)
        self.map.find_path_initial_multi_fleet(
            location_dict, current=self.fleet_current, has_ambush=self.config.MAP_HAS_AMBUSH
        )

    def show_fleet(self):
        fleets = []
        for n in [1, 2]:
            fleet = self.__getattribute__(f"fleet_{n}_location")
            if len(fleet):
                text = f"Fleet_{n}: {location2node(fleet)}"
                if self.fleet_current_index == n:
                    text = f"[{text}]"
                fleets.append(text)
        logger.info(" ".join(fleets))

    def show_submarine(self):
        logger.info(f"Submarine: {location2node(self.fleet_submarine_location)}")

    def full_scan(self, options=None, queue=None, must_scan=None, mode="normal"):
        if options is None:
            options = FullScanOptions(
                queue=queue,
                must_scan=must_scan,
                battle_count=self.battle_count,
                mystery_count=self.mystery_count,
                siren_count=self.siren_count,
                carrier_count=self.carrier_count,
                mode=mode,
            )
        if self.config.MAP_HAS_DECOY_ENEMY and options.mode == "normal":
            options.mode = "decoy"
        super().full_scan(options)

        if self.config.FLEET_2 and not self.fleet_2_location:
            fleets = self.map.select(is_fleet=True, is_current_fleet=False)
            if fleets.count:
                logger.info(f"Predict fleet_2 to be {fleets[0]}")
                self.fleet_2_location = fleets[0].location

        for loca in [self.fleet_1_location, self.fleet_2_location]:
            if len(loca) and loca in self.map:
                grid = self.map[loca]
                if grid.may_boss and grid.is_caught_by_siren:
                    # Only boss appears on fleet's face
                    pass
                else:
                    self.map[loca].wipe_out()

    def full_scan_carrier(self):
        """
        Call this method if get enemy searching in mystery.
        """
        prev = self.map.select(is_enemy=True)
        self.full_scan(mode="carrier")
        diff = self.map.select(is_enemy=True).delete(prev)
        logger.info(f"Carrier spawn: {diff}")

    def full_scan_movable(self, enemy_cleared=True):
        """
        Call this method if enemy moved.

        Args:
            enemy_cleared (bool): True if cleared an enemy and need to scan spawn enemies.
                                  False if just a simple walk and only need to scan movable enemies.
        """
        if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
            if self.config.MAP_HAS_MOVABLE_ENEMY:
                for grid in self.movable_before:
                    grid.wipe_out()
                for grid in self.movable_before_normal:
                    grid.wipe_out()
                self.full_scan(mode="movable")
                self.track_movable(enemy_cleared=enemy_cleared, siren=True)
                self.track_movable(enemy_cleared=enemy_cleared, siren=False)
            else:
                for grid in self.movable_before_normal:
                    grid.wipe_out()
                self.full_scan(mode="movable")
                self.track_movable(enemy_cleared=enemy_cleared, siren=False)

        elif self.config.MAP_HAS_MOVABLE_ENEMY:
            for grid in self.movable_before:
                grid.wipe_out()
            self.full_scan(
                queue=None if enemy_cleared else self.movable_before, must_scan=self.movable_before, mode="movable"
            )
            self.track_movable(enemy_cleared=enemy_cleared, siren=True)

    def track_movable(self, enemy_cleared=True, siren=True):
        """
        Track enemy moving and predict missing enemies.

        Args:
            enemy_cleared (bool): True if cleared an enemy and need to scan spawn enemies.
                                  False if just a simple walk and only need to scan movable enemies.
            siren (bool): True if track sirens, false if track normal enemies
        """
        before, after, spawn, step = self._track_movable_context(siren=siren)
        matched_before, matched_after = match_movable(
            before=before.location,
            spawn=spawn.location,
            after=after.location,
            fleets=[self.fleet_current] if enemy_cleared else [],
            fleet_step=step,
        )
        matched_before = self.map.to_selected(matched_before)
        matched_after = self.map.to_selected(matched_after)
        logger.info(f"Movable enemy {before} -> {after}")
        logger.info(f"Tracked enemy {matched_before} -> {matched_after}")

        self._track_movable_delete_wrong_detection(after=after, matched_after=matched_after)
        diff = before.delete(matched_before)
        missing = self._track_movable_missing_count(siren=siren)
        if diff and missing != 0:
            logger.warning(f"Movable enemy tracking lost: {diff}")
            predict = self._track_movable_predict_missing(diff=diff, after=after, siren=siren)
            matched_after = matched_after.add(predict)
        elif missing == 0:
            logger.info(f"Movable enemy tracking drop: {diff}")

        self._track_movable_mark_matched(matched_after)

    def _track_movable_context(self, *, siren):
        before = self.movable_before if siren else self.movable_before_normal
        after = self.map.select(is_siren=True) if siren else self.map.select(is_enemy=True)
        spawn = self.map.select(may_siren=True) if siren else self.map.select(may_enemy=True)
        step = self.config.MOVABLE_ENEMY_FLEET_STEP if siren else 1
        return before, after, spawn, step

    def _track_movable_delete_wrong_detection(self, *, after, matched_after):
        if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
            return

        for grid in after.delete(matched_after):
            if not grid.may_siren:
                logger.warning(f"Wrong detection: {grid}")
                grid.wipe_out()

    def _track_movable_missing_count(self, *, siren):
        _, missing = self.map.missing_get(
            self.battle_count, self.mystery_count, self.siren_count, self.carrier_count, mode="normal"
        )
        return missing["siren"] if siren else missing["enemy"]

    def _track_movable_predict_missing(self, *, diff, after, siren):
        covered = self._track_movable_covered_grids(after=after, siren=siren)
        accessible = self._track_movable_accessible_grids(diff=diff, siren=siren)
        predict = accessible.intersect(covered).select(is_sea=True, is_fleet=False)
        logger.info(f"Movable enemy predict: {predict}")
        self._track_movable_mark_predicted(predict, siren=siren)
        return predict

    def _track_movable_covered_grids(self, *, after, siren):
        covered = self.map.grid_covered(self.map[self.fleet_current], location=[(0, -2)])
        for location in (self.fleet_1_location, self.fleet_2_location):
            if location:
                covered = covered.add(self.map.grid_covered(self.map[location], location=[(0, -1)]))

        if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY and not self.config.MAP_ENEMY_TEMPLATE:
            for location in (self.fleet_1_location, self.fleet_2_location):
                if location:
                    covered = covered.add(self.map.grid_covered(self.map[location], location=[(1, 0)]))

        covered = covered.add(self.map.manual_map_covered)
        cover_sources = after if siren else self.map.select(is_siren=True)
        for grid in cover_sources:
            covered = covered.add(self.map.grid_covered(grid))
        logger.attr("enemy_covered", covered)
        return covered

    def _track_movable_accessible_grids(self, *, diff, siren):
        accessible = SelectedGrids([])
        if self.config.MAP_HAS_WALL:
            self.map.grid_connection_initial(wall=False, portal=self.config.MAP_HAS_PORTAL)

        for grid in diff:
            self.map.find_path_initial(grid, has_ambush=False)
            accessible = accessible.add(self.map.select(cost=0)).add(self.map.select(cost=1))
            if siren:
                accessible = accessible.add(self.map.select(cost=2))

        if self.config.MAP_HAS_WALL:
            self.map.grid_connection_initial(wall=self.config.MAP_HAS_WALL, portal=self.config.MAP_HAS_PORTAL)
        self.map.find_path_initial(self.fleet_current, has_ambush=self.config.MAP_HAS_AMBUSH)
        logger.attr("enemy_accessible", accessible)
        return accessible

    def _track_movable_mark_predicted(self, predict, *, siren):
        for grid in predict:
            if siren:
                grid.is_siren = True
            grid.is_enemy = True

    def _track_movable_mark_matched(self, matched_after):
        for grid in matched_after:
            if grid.location != self.fleet_current:
                grid.is_movable = True

    def find_all_fleets(self):
        logger.hr("Find all fleets")
        queue = self.map.select(is_spawn_point=True)
        while queue:
            queue = queue.sort_by_camera_distance(self.camera)
            self.in_sight(queue[0], sight=(-1, 0, 1, 2))
            grid = self.convert_global_to_local(queue[0])
            if grid.predict_fleet():
                if grid.predict_current_fleet():
                    self.fleet_1 = queue[0].location
                else:
                    self.fleet_2 = queue[0].location
            queue = queue[1:]

    def find_current_fleet(self):
        logger.hr("Find current fleet")
        fleets = self._find_current_fleet_candidates()
        logger.info(f"Fleets: {fleets}")

        count = fleets.count
        if count == 1:
            self._find_current_fleet_from_single(fleets)
        elif count == 2:
            self._find_current_fleet_from_pair(fleets)
        else:
            self._find_current_fleet_from_unexpected_count(fleets)

        self.show_fleet()
        return self.fleet_current

    def _find_current_fleet_candidates(self):
        if not self.config.POOR_MAP_DATA:
            return self.map.select(is_fleet=True, is_spawn_point=True)
        return self.map.select(is_fleet=True)

    def _find_current_fleet_from_single(self, fleets):
        if not self.config.FLEET_2:
            self.fleet_1 = fleets[0].location
            return

        logger.info("Fleet_2 not detected.")
        spawn_points = self.map.select(is_spawn_point=True)
        if self.config.POOR_MAP_DATA and not spawn_points:
            self.fleet_1 = fleets[0].location
        elif spawn_points.count == 2:
            self._find_current_fleet_from_spawn_points(fleets[0], spawn_points)
        else:
            self._find_current_fleet_from_cover(fleets[0])

    def _find_current_fleet_from_spawn_points(self, detected, spawn_points):
        logger.info("Predict fleet to be spawn point")
        another = spawn_points.delete(SelectedGrids([detected]))[0]
        if detected.is_current_fleet:
            self.fleet_1 = detected.location
            self.fleet_2 = another.location
        else:
            self.fleet_1 = another.location
            self.fleet_2 = detected.location

    def _find_current_fleet_from_cover(self, detected):
        cover = self.map.grid_covered(detected, location=[(0, -1)])
        if detected.is_current_fleet and len(cover) and cover[0].is_spawn_point:
            self.fleet_1 = detected.location
            self.fleet_2 = cover[0].location
        else:
            self.find_all_fleets()

    def _find_current_fleet_from_pair(self, fleets):
        current = self.map.select(is_current_fleet=True)
        if current.count == 1:
            self.fleet_1 = current[0].location
            self.fleet_2 = fleets.delete(current)[0].location
            return

        self._find_current_fleet_pair_by_prediction(fleets)

    def _find_current_fleet_pair_by_prediction(self, fleets):
        fleets = fleets.sort_by_camera_distance(self.camera)
        first, second = fleets[0], fleets[1]
        if self._is_current_fleet_by_prediction(first):
            self.fleet_1 = first.location
            self.fleet_2 = second.location
        elif self._is_current_fleet_by_prediction(second):
            self.fleet_1 = second.location
            self.fleet_2 = first.location
        else:
            logger.warning("Current fleet not found")
            self.fleet_1 = first.location
            self.fleet_2 = second.location

    def _is_current_fleet_by_prediction(self, grid):
        self.in_sight(grid, sight=(-1, 0, 1, 2))
        return self.convert_global_to_local(grid).predict_current_fleet()

    def _find_current_fleet_from_unexpected_count(self, fleets):
        if fleets.count == 0:
            logger.warning("No fleets detected.")
            current = self.map.select(is_current_fleet=True)
            if current.count:
                self.fleet_1 = current[0].location
        else:
            logger.warning(f"Too many fleets: {fleets}.")
        self.find_all_fleets()

    def find_all_submarines(self):
        logger.hr("Find all submarines")
        queue = self.map.select(is_submarine_spawn_point=True)
        while queue:
            queue = queue.sort_by_camera_distance(self.camera)
            self.in_sight(queue[0], sight=(-2, -1, 2, -1))
            grid = self.convert_global_to_local(queue[0])
            if grid.predict_submarine():
                self.fleet_submarine = queue[0].location
                break
            queue = queue[1:]

    def find_submarine(self):
        if not (self.config.SUBMARINE and self.map.select(is_submarine_spawn_point=True)):
            return False

        fleets = self.map.select(is_submarine=True)
        count = fleets.count
        if count == 1:
            self.fleet_submarine = fleets[0].location
        elif count == 0:
            logger.info("No submarine found")
            # Try spawn points
            spawn_point = self.map.select(is_submarine_spawn_point=True)
            if spawn_point.count == 1:
                logger.info(f"Predict the only submarine spawn point {spawn_point[0]} as submarine")
                self.fleet_submarine = spawn_point[0].location
            else:
                logger.info(f"Having multiple submarine spawn points: {spawn_point}")
                # Try covered grids
                covered = SelectedGrids([])
                for grid in spawn_point:
                    covered = covered.add(self.map.grid_covered(grid, location=[(0, 1)]))
                covered = covered.filter(lambda g: g.is_enemy or g.is_fleet or g.is_siren or g.is_boss)
                if covered.count == 1:
                    spawn_point = self.map.grid_covered(covered[0], location=[(0, -1)])
                    logger.info(f"Submarine {spawn_point[0]} covered by {covered[0]}")
                    self.fleet_submarine = spawn_point[0].location
                else:
                    logger.info("Found multiple submarine spawn points being covered")
                    # Give up
                    self.find_all_submarines()
        else:
            logger.warning(f"Too many submarines: {fleets}.")
            self.find_all_submarines()

        if not len(self.fleet_submarine_location):
            logger.warning("Unable to find submarine, assume it is at map center")
            shape = self.map.shape
            center = (shape[0] // 2, shape[1] // 2)
            self.fleet_submarine = self.map.select(is_land=False).sort_by_camera_distance(center)[0].location

        self.show_submarine()
        return self.fleet_submarine_location

    def map_init(self, map_):
        """
        进入地图后、执行任何地图操作前调用。

        Args:
            map_ (CampaignMap)：当前战役地图。
        """
        logger.hr("Map init")
        self.map_data_init(map_)
        self.map_control_init()

    def map_data_init(self, map_):
        """
        Init map data according to settings and map status.
        Just data processing, no screenshots and clicks.

        Args:
            map_ (CampaignMap):
        """
        self.fleet_1_location = ()
        self.fleet_2_location = ()
        self.fleet_submarine_location = ()
        self.fleet_current_index = 1
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
        self.map.grid_connection_initial(
            wall=self.config.MAP_HAS_WALL,
            portal=self.config.MAP_HAS_PORTAL,
        )
        self.map.load_mechanism(
            land_based=self.config.MAP_HAS_LAND_BASED,
            maze=self.config.MAP_HAS_MAZE,
            fortress=self.config.MAP_HAS_FORTRESS,
            bouncing_enemy=self.config.MAP_HAS_BOUNCING_ENEMY,
        )

    def map_control_init(self):
        """
        Preparation before operations.
        Such as select strategy, calculate hp and level, init camera position, do first map scan.
        """
        self.update()
        if not self.handle_fleet_reverse():
            self.fleet_set(index=1)
        self.handle_strategy(index=self.fleet_show_index)
        self.hp_reset()
        self.hp_get()
        self.lv_reset()
        self.lv_get()
        self.ensure_edge_insight(preset=self.map.in_map_swipe_preset_data)
        self.handle_info_bar()  # The info_bar which shows "Changed to fleet 2", will block the ammo icon
        self.full_scan(must_scan=self.map.camera_data_spawn_point, mode="init")
        self.find_current_fleet()
        self.find_submarine()
        self.find_path_initial()
        self.map.show_cost()
        self.round_reset()
        self.round_battle()

    def handle_clear_mode_config_cover(self):
        if not self.map_is_clear_mode:
            return False

        if self.config.POOR_MAP_DATA and self.map.is_map_data_poor:
            self.config.POOR_MAP_DATA = False
        self.map.fortress_data = [(), ()]
        self.map.bouncing_enemy_data = []

        return True

    def _expected_end(self, expected):
        for data in self.map.spawn_data:
            if data.get("battle") == self.battle_count and "boss" in expected:
                return "in_stage"
            if data.get("battle") == self.battle_count + 1:
                if data.get("enemy", 0) + data.get("siren", 0) + data.get("boss", 0) > 0:
                    return "with_searching"
                return "no_searching"

        if "boss" in expected:
            return "in_stage"

        matched = False
        for data in self.map.spawn_data:
            if data.get("battle") == self.battle_count + 1:
                matched = True
        if not len(self.map.spawn_data) or matched:
            # No spawn_data
            # spawn_data is not continuous, some battles are missing
            return None
        # Out of the spawn_data, nothing will spawn
        return "no_searching"

    def _submarine_mode(self, expected):
        if self.is_call_submarine_at_boss:
            if "boss" in expected:
                return "every_combat"
            return "do_not_use"
        return None

    def fleet_at(self, grid, fleet=None):
        """
        Args:
            grid (Grid):
            fleet (int): 1, 2

        Returns:
            bool: If fleet is at grid.
        """
        if fleet is None:
            return self.fleet_current == grid.location
        if fleet == 1:
            return self.fleet_1_location == grid.location
        return self.fleet_2_location == grid.location

    def check_accessibility(self, grid, fleet=None):
        """
        Args:
            grid (Grid):
            fleet (int, str): 1, 2, 'boss'

        Returns:
            bool: If accessible.
        """
        if fleet is None:
            return grid.is_accessible
        if isinstance(fleet, str) and fleet.isdigit():
            fleet = int(fleet)
        if fleet == "boss":
            fleet = self.fleet_boss_index

        if fleet == self.fleet_current_index:
            return grid.is_accessible
        backup = self.fleet_current_index
        self.fleet_current_index = fleet
        self.find_path_initial()
        result = grid.is_accessible

        self.fleet_current_index = backup
        self.find_path_initial()
        return result

    def brute_find_roadblocks(self, grid, fleet=None):
        """
        Args:
            grid (Grid):
            fleet (int): 1, 2. Default to current fleet.

        Returns:
            SelectedGrids:
        """
        if fleet is not None and fleet != self.fleet_current_index:
            backup = self.fleet_current_index
            self.fleet_current_index = fleet
            self.find_path_initial()
        else:
            backup = None

        if grid.is_accessible:
            if backup is not None:
                self.fleet_current_index = backup
                self.find_path_initial()
            return SelectedGrids([])

        enemies = self.map.select(is_enemy=True)
        logger.info(f"Potential enemy roadblocks: {enemies}")
        for repeat in range(1, enemies.count + 1):
            for select in itertools.product(enemies, repeat=repeat):
                for block in select:
                    block.is_enemy = False
                self.find_path_initial()
                for block in select:
                    block.is_enemy = True

                if grid.is_accessible:
                    roadblock = SelectedGrids(list(select))
                    logger.info(f"Enemy roadblock: {roadblock}")
                    if backup is not None:
                        self.fleet_current_index = backup
                        self.find_path_initial()
                    return roadblock

        logger.warning("Enemy roadblock try exhausted.")
        return SelectedGrids([])

    def catch_camera_repositioning(self):
        """检测 Boss 出现后是否触发了地图镜头重定位。"""
        appear = False
        for data in self.map.spawn_data:
            if data.get("battle") == self.battle_count and data.get("boss", 0):
                logger.info("Catch camera re-positioning after boss appear")
                appear = True

        return appear

    def handle_boss_appear_refocus(self, preset=None):
        """
        Refocus to previous camera position after boss appear.

        Args:
            preset (tuple): (x, y).
        """
        camera = self.camera
        if preset is None:
            preset = self.config.MAP_BOSS_APPEAR_REFOCUS_SWIPE

        if preset is not None and np.linalg.norm(preset) > 0:
            try:
                self.update()
            except MapDetectionError:
                logger.info(f"MapDetectionError occurs after boss appear, trying swipe preset {preset}")
                # Swipe optimize here may not be accurate.
                self.map_swipe(preset)
            self.ensure_edge_insight()
        else:
            self.update()
            self.ensure_edge_insight()

        logger.info("Refocus to previous camera position.")
        self.focus_to(camera)

    def fleet_checked_reset(self):
        self.map_fleet_checked = False
        self.fleet_1_formation_fixed = False
        self.fleet_2_formation_fixed = False

    def _submarine_goto(self, location):
        """
        Move submarine to given location.

        Args:
            location (tuple, str, GridInfo): Destination.

        Returns:
            bool: If submarine moved.

        Pages:
            in: SUBMARINE_MOVE_CONFIRM
            out: SUBMARINE_MOVE_CONFIRM
        """
        location = location_ensure(location)
        moved = True
        while 1:
            self.in_sight(location, sight=self._walk_sight)
            self.focus_to_grid_center()
            grid = self.convert_global_to_local(location)
            grid.__str__ = location

            self.device.click(grid)
            arrived = False
            # Usually no need to wait
            arrive_timer = Timer(0.1, count=0)
            # If nothing happens, click again.
            walk_timeout = Timer(2, count=6).start()

            while 1:
                self.device.screenshot()
                self.view.update(image=self.device.image)

                # Arrive
                arrive_checker = grid.predict_submarine_move()
                if grid.predict_submarine() or (walk_timeout.reached() and grid.predict_fleet()):
                    arrive_checker = True
                    moved = False
                if arrive_checker:
                    if not arrive_timer.started():
                        logger.info(f"Arrive {location2node(location)}")
                    arrive_timer.start()
                    if not arrive_timer.reached():
                        continue
                    logger.info(f"Submarine arrive {location2node(location)} confirm.")
                    if not moved:
                        logger.info(f"Submarine already at {location2node(location)}")
                    arrived = True
                    break

                # End
                if walk_timeout.reached():
                    logger.warning("Walk timeout. Retrying.")
                    self.predict()
                    self.ensure_edge_insight(skip_first_update=False)
                    break

            # End
            if arrived:
                break

        return moved

    def submarine_goto(self, location):
        """
        Open strategy, move submarine to given location, close strategy.

        Args:
            location (tuple, str, GridInfo): Destination.

        Returns:
            bool: If submarine moved

        Pages:
            in: IN_MAP
            out: IN_MAP
        """
        self.strategy_open()
        self.strategy_submarine_move_enter()
        if self._submarine_goto(location):
            self.strategy_submarine_move_confirm()
            result = True
        else:
            self.strategy_submarine_move_cancel()
            result = False
        # Hunt zone view re-enabled by game, after entering sub move mode
        self.strategy_set_execute(sub_view=False)
        self.strategy_close()
        return result

    def submarine_move_near_boss(self, boss):
        """
        Args:
            boss (tuple, str, GridInfo): Destination.

        Returns:
            bool: If submarine moved
        """
        if not (self.is_call_submarine_at_boss and self.map.select(is_submarine_spawn_point=True)):
            return False
        if self.config.Submarine_DistanceToBoss == "use_open_ocean_support":
            logger.info("Going to use Open Ocean Support, skip moving submarines")
            return False

        boss = location_ensure(boss)
        logger.info(f"Move submarine near {location2node(boss)}")

        self.map.find_path_initial(self.fleet_submarine_location, has_ambush=False, has_enemy=False)
        self.map.show_cost()

        def get_location(distance=2):
            grids = self.map.select(is_land=False).filter(
                lambda grid: np.sum(np.abs(np.subtract(grid.location, boss))) <= distance
            )
            if grids:
                return grids.sort("cost")[0].location
            if distance > 0:
                logger.info(f"Unable to find a grid near boss in distance {distance}, fallback to {distance - 1}")
                return get_location(distance - 1)
            logger.warning(f"Unable to find a grid near boss in distance {distance}, return boss position")
            return boss

        distance_dict = {"to_boss_position": 0, "1_grid_to_boss": 1, "2_grid_to_boss": 2}
        distance_to_boss = distance_dict.get(self.config.Submarine_DistanceToBoss, 0)
        logger.attr("Distance to boss", distance_to_boss)

        if np.sum(np.abs(np.subtract(self.fleet_submarine_location, boss))) <= distance_to_boss:
            logger.info("Boss is already in hunting zone")
            self.find_path_initial()
            return False
        near = get_location(distance_to_boss)
        self.find_path_initial()
        logger.info(f"Move submarine to {location2node(near)}")
        return self.submarine_goto(near)
