from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Protocol

from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Collection, Mapping, Sequence

    from module.map.type_alias import GridLocation


class _BouncingRoute(Protocol):
    def select(self, **criteria: object) -> object: ...


class _MazeGrid(Protocol):
    @property
    def is_maze(self) -> bool: ...

    @property
    def maze_round(self) -> Collection[int]: ...


class _FleetTurnMap(Protocol):
    @property
    def spawn_data(self) -> Sequence[Mapping[str, int]]: ...

    @property
    def maze_round(self) -> int: ...

    @property
    def bouncing_enemy_data(self) -> Sequence[_BouncingRoute]: ...

    def select(self, **criteria: object) -> object: ...

    def __getitem__(self, location: GridLocation, /) -> _MazeGrid: ...


@dataclass(frozen=True, slots=True)
class FleetTurnRules:
    movable_enemy: bool = False
    movable_normal_enemy: bool = False
    maze: bool = False
    bouncing_enemy: bool = False
    movable_enemy_turns: tuple[int, ...] = ()
    movable_normal_enemy_turns: tuple[int, ...] = ()
    enemy_move_wait: float = 0.0


class FleetTurnEvent(Enum):
    STABLE = auto()
    ENEMY_MOVED = auto()
    MAZE_CHANGED = auto()


class FleetTurnController:
    """维护当前地图的玩家行动轮次，并把轮次变化收口成事件。"""

    __slots__ = ("_enemy_round", "_map", "_round", "_rules")

    def __init__(self, rules: FleetTurnRules, map_: _FleetTurnMap) -> None:
        if not isinstance(rules, FleetTurnRules):
            message = "fleet turn controller requires FleetTurnRules"
            raise TypeError(message)
        self._rules = rules
        self._map = map_
        self._round = 0
        self._enemy_round: dict[int, int] = {}

    def initialize(self, battle_count: int) -> None:
        """重置轮次，并登记当前波次已经出现的可移动敌人。"""

        self._round = 0
        self._enemy_round = {}
        self.battle_resolved(battle_count)

    def battle_resolved(self, battle_count: int) -> None:
        """战斗清除敌人后更新仍会参与后续行动的敌方波次。"""

        rules = self._rules
        if not rules.movable_enemy:
            return
        if not self._map.select(is_siren=True):
            if rules.movable_normal_enemy:
                if not self._map.select(is_enemy=True):
                    self._enemy_round = {}
            else:
                self._enemy_round = {}
        try:
            data = self._map.spawn_data[battle_count]
        except IndexError:
            data = {}
        enemy = data.get("siren", 0)
        if rules.movable_normal_enemy:
            enemy += data.get("enemy", 0)
        if enemy > 0:
            self._enemy_round[self._round] = self._enemy_round.get(self._round, 0) + enemy

    def fleet_arrived(self) -> FleetTurnEvent:
        """舰队完成一次移动后推进轮次，并返回本轮最高优先级变化。"""

        rules = self._rules
        if not rules.movable_enemy and not rules.maze:
            return FleetTurnEvent.STABLE
        self._round += 1
        logger.info(f"Round: {self._round}, enemy_round: {self._enemy_round}")
        if self._enemy_moved:
            return FleetTurnEvent.ENEMY_MOVED
        if self._maze_changed:
            return FleetTurnEvent.MAZE_CHANGED
        return FleetTurnEvent.STABLE

    @property
    def movement_wait(self) -> float:
        """返回下一次移动前应为敌人、迷宫和弹跳路线预留的秒数。"""

        rules = self._rules
        second = 0.0
        if rules.movable_enemy:
            count = 0
            for enemy, enemy_count in self._enemy_round.items():
                for turn in self._enemy_turns:
                    if self._round + 1 - enemy > 0 and (self._round + 1 - enemy) % turn == 0:
                        count += enemy_count
                        break
            second += count * rules.enemy_move_wait

        if rules.maze and (self._round + 1) % 3 == 0:
            second += 1.0

        if rules.bouncing_enemy:
            for route in self._map.bouncing_enemy_data:
                if route.select(may_bouncing_enemy=True):
                    second += rules.enemy_move_wait

        return second

    def maze_active_on(self, location: GridLocation) -> bool:
        if not self._rules.maze:
            return False
        grid = self._map[location]
        if not grid.is_maze:
            return False
        return self._round % self._map.maze_round in grid.maze_round

    @property
    def _enemy_turns(self) -> tuple[int, ...]:
        rules = self._rules
        if rules.movable_enemy:
            if rules.movable_normal_enemy:
                return tuple({*rules.movable_enemy_turns, *rules.movable_normal_enemy_turns})
            return rules.movable_enemy_turns
        if rules.movable_normal_enemy:
            return rules.movable_normal_enemy_turns
        return ()

    @property
    def _enemy_moved(self) -> bool:
        if not self._rules.movable_enemy:
            return False
        return any(
            self._round - enemy > 0 and (self._round - enemy) % turn == 0
            for enemy in self._enemy_round
            for turn in self._enemy_turns
        )

    @property
    def _maze_changed(self) -> bool:
        return self._rules.maze and self._round != 0 and self._round % 3 == 0
