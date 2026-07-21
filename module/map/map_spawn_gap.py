from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

from module.base.utils import location2node
from module.logger import logger
from module.map.utils import location_ensure

if TYPE_CHECKING:
    from collections.abc import Collection, Iterable, Iterator, Mapping, Sequence

    from module.map.type_alias import GridMode
    from module.map_detection.grid_info import GridInfo


class _SpawnGapMap(Protocol):
    poor_map_data: bool

    def __iter__(self) -> Iterator[GridInfo]: ...

    @property
    def spawn_data_stack(self) -> Sequence[Mapping[str, int]]: ...

    @property
    def fortress_data(self) -> tuple[Collection[GridInfo], Collection[GridInfo]]: ...

    @property
    def bouncing_enemy_data(self) -> Sequence[Iterable[GridInfo]]: ...

    @property
    def map_covered(self) -> Iterable[GridInfo]: ...


@dataclass(frozen=True, slots=True)
class MapSpawnProgress:
    battle_count: int = 0
    mystery_count: int = 0
    siren_count: int = 0
    carrier_count: int = 0
    mode: GridMode = "normal"


@dataclass(frozen=True, slots=True)
class MapSpawnGapSnapshot:
    possible: dict[str, int]
    missing: dict[str, int]


class MapSpawnGapPredictor:
    """根据刷新规则和当前遮挡状态推断尚未识别的地图目标。"""

    def __init__(self, map_: _SpawnGapMap) -> None:
        self._map = map_

    def estimate(self, progress: MapSpawnProgress) -> MapSpawnGapSnapshot:
        missing = self._spawn_rule_at(progress.battle_count)
        missing["enemy"] -= progress.battle_count - progress.siren_count
        missing["mystery"] -= progress.mystery_count
        missing["siren"] -= progress.siren_count
        missing["carrier"] = self._carrier_gap(progress)
        self._subtract_observed_spawns(missing)
        self._restore_dynamic_enemy_gaps(missing)
        possible = self._possible_covered_spawns(progress.mode)

        logger.attr(
            "enemy_missing",
            ", ".join(f"{kind[:2].upper()}:{str(count).rjust(2)}" for kind, count in missing.items()),
        )
        logger.attr(
            "enemy_may____",
            ", ".join(f"{kind[:2].upper()}:{str(count).rjust(2)}" for kind, count in possible.items()),
        )
        return MapSpawnGapSnapshot(possible=possible, missing=missing)

    def scan_complete(self, progress: MapSpawnProgress) -> bool:
        if self._map.poor_map_data:
            return False

        snapshot = self.estimate(progress)
        return all(snapshot.missing[kind] == 0 for kind in snapshot.possible)

    def infer_covered_spawns(self, progress: MapSpawnProgress) -> None:
        if self._map.poor_map_data:
            return

        snapshot = self.estimate(progress)
        for grid in self._map.map_covered:
            for kind in ("enemy", "mystery", "siren", "boss"):
                if (
                    getattr(grid, "may_" + kind)
                    and snapshot.missing[kind] > 0
                    and snapshot.missing[kind] == snapshot.possible[kind]
                ):
                    logger.info(f"Predict {location2node(location_ensure(grid))} to be {kind}")
                    setattr(grid, "is_" + kind, True)
            if (
                progress.carrier_count
                and grid.may_carrier
                and snapshot.missing["carrier"] > 0
                and snapshot.missing["carrier"] == snapshot.possible["carrier"]
            ):
                logger.info(f"Predict {location2node(location_ensure(grid))} to be enemy")
                grid.is_enemy = True

    def _spawn_rule_at(self, battle_count: int) -> dict[str, int]:
        try:
            rule = dict(self._map.spawn_data_stack[battle_count])
        except IndexError:
            rule = dict(self._map.spawn_data_stack[-1])
        rule.pop("battle", None)
        return rule

    def _carrier_gap(self, progress: MapSpawnProgress) -> int:
        if progress.mode != "carrier":
            return 0
        observed = sum(grid.is_enemy and not grid.may_enemy for grid in self._map)
        return progress.carrier_count - observed

    def _subtract_observed_spawns(self, missing: dict[str, int]) -> None:
        for grid in self._map:
            for kind in ("enemy", "mystery", "siren", "boss"):
                if getattr(grid, "is_" + kind):
                    missing[kind] -= 1

    def _restore_dynamic_enemy_gaps(self, missing: dict[str, int]) -> None:
        active_fortresses = sum(grid.is_fortress for grid in self._map)
        missing["enemy"] += len(self._map.fortress_data[0]) - active_fortresses
        for route in self._map.bouncing_enemy_data:
            if not any(grid.may_bouncing_enemy for grid in route):
                # 弹跳敌人已被清理，重新补一个敌人缺口。
                missing["enemy"] += 1

    def _possible_covered_spawns(self, mode: GridMode) -> dict[str, int]:
        possible = {"enemy": 0, "mystery": 0, "siren": 0, "boss": 0, "carrier": 0}
        for grid in self._map.map_covered:
            if (grid.may_enemy or mode == "movable") and not grid.is_enemy:
                possible["enemy"] += 1
            if grid.may_mystery and not grid.is_mystery:
                possible["mystery"] += 1
            if (grid.may_siren or mode == "movable") and not grid.is_siren:
                possible["siren"] += 1
            if grid.may_boss and not grid.is_boss:
                possible["boss"] += 1
            if grid.may_carrier:
                possible["carrier"] += 1
        return possible
