import itertools
import re
from dataclasses import dataclass
from dataclasses import fields as dataclass_fields
from typing import TYPE_CHECKING, TypedDict, cast

from module.base.filter import Filter
from module.exception import MapEnemyMoved
from module.logger import logger
from module.map.fleet import Fleet
from module.map.map_grids import SelectedGrids

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from module.map.map_grids import RoadGrids
    from module.map_detection.grid_info import GridInfo

ENEMY_FILTER: Filter[GridInfo] = Filter(regex=re.compile(r"^(.*?)$"), attr=("str",))
UNKNOWN_GRID_SELECTION_SETTINGS_TEMPLATE = "Unknown grid selection settings: {settings}"


class GridSelectionSettings[T](TypedDict, total=False):
    nearby: bool
    is_accessible: bool
    scale: tuple[int, ...] | list[int]
    genre: tuple[str, ...] | list[str]
    strongest: bool
    weakest: bool
    sort: tuple[str, ...]
    ignore: SelectedGrids[T] | None


@dataclass(slots=True)
class GridSelection[T]:
    nearby: bool = False
    is_accessible: bool = True
    scale: tuple[int, ...] | list[int] = ()
    genre: tuple[str, ...] | list[str] = ()
    strongest: bool = False
    weakest: bool = False
    sort: tuple[str, ...] = ("weight", "cost")
    ignore: SelectedGrids[T] | None = None

    @classmethod
    def from_settings(cls, settings: Mapping[str, object]) -> GridSelection[T]:
        allowed = {field.name for field in dataclass_fields(cls)}
        unknown = set(settings) - allowed
        if unknown:
            message = UNKNOWN_GRID_SELECTION_SETTINGS_TEMPLATE.format(settings=", ".join(sorted(unknown)))
            raise TypeError(message)
        return cls(**cast("GridSelectionSettings[T]", settings))


class Map(Fleet):
    def clear_chosen_enemy(self, grid: GridInfo, expected: str = "") -> bool:
        logger.info(f"targetEnemyScale:{self.config.EnemyPriority_EnemyScaleBalanceWeight}")
        logger.info(f"Clear enemy: {grid}")
        expected = f"combat_{expected}" if expected else "combat"
        battle_count = self.battle_count
        self.show_fleet()
        if self.emotion.is_calculate and self.config.Campaign_UseFleetLock:
            self.emotion.wait(fleet_index=self.fleet_current_index)
        self.goto(grid, expected=expected)

        self.full_scan()
        self.find_path_initial()
        self.map.pathfinder.show_cost()
        return self.battle_count >= battle_count

    def clear_chosen_mystery(self, grid: GridInfo) -> None:
        logger.info(f"Clear mystery: {grid}")
        self.show_fleet()
        self.goto(grid, expected="mystery")
        self.map.pathfinder.show_cost()

    def pick_up_ammo(self, grid: GridInfo | None = None) -> bool:
        if grid is None:
            ammo_grids = self.map.layout.select(may_ammo=True)
            if not ammo_grids:
                logger.info("Map has no ammo.")
                return False
            grid = ammo_grids[0]

        if self.ammo_count > 0 and grid.is_accessible:
            logger.info(f"Pick up ammo: {grid}")
            self.goto(grid, expected="")
            self.ensure_no_info_bar()

            recover = 5 - self.fleet_ammo
            recover = min(recover, 3)
            logger.attr("Got ammo", recover)

            self.ammo_count -= recover
            self.fleet_ammo += recover
            return True
        return False

    def clear_mechanism(self, grids: SelectedGrids[GridInfo] | None = None) -> bool:
        """触发指定机制格；grids 为 None 时选择全部触发格，且因未清敌固定返回 False。"""
        if not self.config.MAP_HAS_LAND_BASED:
            return False

        if not grids:
            grids = self.map.layout.select(is_mechanism_trigger=True, is_mechanism_block=False)
        else:
            grids = grids.select(is_mechanism_trigger=True, is_mechanism_block=False)
        grids = self.select_grids(grids, GridSelection(is_accessible=True, sort=("weight", "cost")))

        for grid in grids:
            logger.info(f"Clear mechanism: {grid}")
            self.goto(grid)
            self.map.pathfinder.show_cost()
            logger.info(f"Mechanism trigger release: {grid.mechanism_trigger}")
            logger.info(f"Mechanism block release: {grid.mechanism_block}")
            raise MapEnemyMoved

        logger.info("Mechanism all cleared")
        return False

    @staticmethod
    def _select_basic_grids[T](
        grids: SelectedGrids[T],
        *,
        nearby: bool,
        is_accessible: bool,
        ignore: SelectedGrids[T] | None,
    ) -> SelectedGrids[T]:
        if nearby:
            grids = grids.select(is_nearby=True)
        if is_accessible:
            grids = grids.select(is_accessible=True)
        if ignore is not None:
            grids = grids.delete(grids=ignore)
        return grids

    @staticmethod
    def _normalize_enemy_genre(raw_enemy_genre: str) -> str:
        if raw_enemy_genre[0].islower():
            return raw_enemy_genre[0].upper() + raw_enemy_genre[1:]
        return raw_enemy_genre

    @staticmethod
    def _select_by_ordered_values[T, V: int | str](
        grids: SelectedGrids[T], attr: str, values: Sequence[V]
    ) -> SelectedGrids[T]:
        selected: SelectedGrids[T] = SelectedGrids([])
        for value in values:
            selected = selected.add(grids.select(**{attr: value}))
            if isinstance(values, list) and selected:
                break
        return selected

    @staticmethod
    def _select_by_scale_priority[T](grids: SelectedGrids[T], order: Sequence[int]) -> SelectedGrids[T]:
        for candidate_scale in order:
            selected = grids.select(enemy_scale=candidate_scale)
            if selected:
                return selected
        return grids

    @staticmethod
    def select_grids[T](
        grids: SelectedGrids[T],
        selection: GridSelection[T] | None = None,
    ) -> SelectedGrids[T]:
        if selection is None:
            selection = GridSelection()

        grids = Map._select_basic_grids(
            grids,
            nearby=selection.nearby,
            is_accessible=selection.is_accessible,
            ignore=selection.ignore,
        )
        if len(selection.scale):
            grids = Map._select_by_ordered_values(grids, "enemy_scale", selection.scale)
        if len(selection.genre):
            normalized_genre = [Map._normalize_enemy_genre(item) for item in selection.genre]
            grids = Map._select_by_ordered_values(grids, "enemy_genre", normalized_genre)
        if selection.strongest:
            grids = Map._select_by_scale_priority(grids, [3, 2, 1, 0])
        if selection.weakest:
            grids = Map._select_by_scale_priority(grids, [1, 2, 3, 0])

        if grids:
            grids = grids.sort(*selection.sort)

        return grids

    @staticmethod
    def _selection_settings_with_enemy_priority(
        settings: Mapping[str, object], target: str, *, clear_all: bool
    ) -> dict[str, object]:
        settings = dict(settings)
        if target == "S3_enemy_first":
            settings["strongest"] = True
        elif target == "S1_enemy_first":
            settings["weakest"] = True
        elif clear_all:
            settings["strongest"] = True
        return settings

    @staticmethod
    def show_select_grids[T](grids: SelectedGrids[T], **kwargs: object) -> None:
        length = 3
        keys = list(kwargs.keys())
        for index in range(0, len(keys), length):
            text = [f"{key}={kwargs[key]}" for key in keys[index : index + length]]
            text = ", ".join(text)
            logger.info(text)

        logger.info(f"Grids: {grids}")

    def clear_all_mystery(self, **kwargs: object) -> bool:
        """拾取全部神秘事件；因未清敌固定返回 False。"""
        kwargs = {**kwargs, "sort": ("cost",)}
        while 1:
            grids = self.map.layout.select(is_mystery=True)
            grids = self.select_grids(grids, GridSelection.from_settings(kwargs))

            if not grids:
                break

            logger.hr("Clear all mystery")
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_mystery(grids[0])

        return False

    def clear_enemy(self, **kwargs: object) -> bool:
        """清理符合条件的敌人；没有目标时不操作，清敌后返回 True。"""
        grids = self.map.layout.select(is_enemy=True, is_boss=False)

        target = self.config.EnemyPriority_EnemyScaleBalanceWeight
        kwargs = self._selection_settings_with_enemy_priority(
            kwargs, target, clear_all=self.config.MAP_CLEAR_ALL_THIS_TIME
        )
        grids = self.select_grids(grids, GridSelection.from_settings(kwargs))

        if grids:
            logger.hr("Clear enemy")
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_roadblocks(self, roads: Iterable[RoadGrids[GridInfo]], **kwargs: object) -> bool:
        """清理 RoadGrids 路线上的阻挡敌人，清敌后返回 True。"""
        grids = SelectedGrids([])
        for road in roads:
            grids = grids.add(road.roadblocks())

        target = self.config.EnemyPriority_EnemyScaleBalanceWeight
        kwargs = self._selection_settings_with_enemy_priority(
            kwargs, target, clear_all=self.config.MAP_CLEAR_ALL_THIS_TIME
        )
        grids = self.select_grids(grids, GridSelection.from_settings(kwargs))

        if grids:
            logger.hr("Clear roadblock")
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_potential_roadblocks(self, roads: Iterable[RoadGrids[GridInfo]], **kwargs: object) -> bool:
        """提前清理仅剩一个空格的潜在阻挡路线，清敌后返回 True。"""
        grids = SelectedGrids([])
        for road in roads:
            grids = grids.add(road.potential_roadblocks())

        target = self.config.EnemyPriority_EnemyScaleBalanceWeight
        kwargs = self._selection_settings_with_enemy_priority(
            kwargs, target, clear_all=self.config.MAP_CLEAR_ALL_THIS_TIME
        )
        grids = self.select_grids(grids, GridSelection.from_settings(kwargs))

        if grids:
            logger.hr("Avoid potential roadblock")
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_first_roadblocks(self, roads: Iterable[RoadGrids[GridInfo]], **kwargs: object) -> bool:
        """确保每条阻挡路线至少有一个已清格，清敌后返回 True。"""
        grids = SelectedGrids([])
        for road in roads:
            grids = grids.add(road.first_roadblocks())

        grids = self.select_grids(grids, GridSelection.from_settings(kwargs))

        if grids:
            logger.hr("Clear first roadblock")
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_grids_for_faster(self, grids: SelectedGrids[GridInfo], **kwargs: object) -> bool:
        """清理指定格以缩短路径，清敌后返回 True。"""
        grids = grids.select(is_enemy=True)
        grids = self.select_grids(grids, GridSelection.from_settings(kwargs))

        if grids:
            logger.hr("Clear grids for faster")
            self.show_select_grids(grids, **kwargs)
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_boss(self) -> bool:
        """已弃用的简单 Boss 清理方法；复杂地图应使用 brute_clear_boss。"""
        grids = self.map.layout.select(is_boss=True, is_accessible=True)
        grids = grids.add(self.map.layout.select(may_boss=True, is_caught_by_siren=True))
        logger.info(f"Is boss: {grids}")
        if not grids.count:
            grids = grids.add(self.map.layout.select(may_boss=True, is_enemy=True, is_accessible=True))
            logger.warning("Boss not detected, using may_boss grids.")
            logger.info(f"May boss: {self.map.layout.select(may_boss=True)}")
            logger.info(f"May boss and is enemy: {self.map.layout.select(may_boss=True, is_enemy=True)}")

        if grids:
            self.submarine_move_near_boss(grids[0])
            logger.hr("Clear BOSS")
            grids = grids.sort("weight", "cost")
            logger.info(f"Grids: {grids}")
            self.clear_chosen_enemy(grids[0], expected="boss")

        logger.warning("BOSS not detected, trying all boss spawn point.")
        return self.clear_potential_boss()

    def capture_clear_boss(self) -> None:
        """已弃用的简单 Boss 清理方法，仅用于旧的大世界占领地图。"""
        grids = self.map.layout.select(is_boss=True, is_accessible=True)
        grids = grids.add(self.map.layout.select(may_boss=True, is_caught_by_siren=True))
        logger.info(f"Is boss: {grids}")
        if not grids.count:
            grids = grids.add(self.map.layout.select(may_boss=True, is_enemy=True, is_accessible=True))
            logger.warning("Boss not detected, using may_boss grids.")
            logger.info(f"May boss: {self.map.layout.select(may_boss=True)}")
            logger.info(f"May boss and is enemy: {self.map.layout.select(may_boss=True, is_enemy=True)}")

        if grids:
            logger.hr("Clear BOSS")
            grids = grids.sort("weight", "cost")
            logger.info(f"Grids: {grids}")
            self.clear_chosen_enemy(grids[0])

        logger.warning("Grand Capture detected, Withdrawing.")
        self.withdraw()

    def clear_potential_boss(self) -> bool:
        """未检测到 Boss 时依次踏遍所有 Boss 刷新点。"""
        grids = self.map.layout.select(may_boss=True, is_accessible=True).sort("weight", "cost")
        logger.info(f"May boss: {grids}")
        battle_count = self.battle_count
        is_single_boss = self.map.layout.select(may_boss=True).count == 1
        expected = "boss" if is_single_boss else ""

        for grid in grids:
            logger.hr("Clear potential BOSS")
            logger.info(f"Grid: {grid}")
            self.fleet_boss.clear_chosen_enemy(grid, expected=expected)
            if self.battle_count > battle_count:
                logger.info("Boss guessing correct.")
                return True
            logger.info("Boss guessing incorrect.")

        grids = self.map.layout.select(may_boss=True, is_accessible=False).sort("weight", "cost")
        logger.info(f"May boss: {grids}")

        for grid in grids:
            logger.hr("Clear potential BOSS roadblocks")
            roadblocks = self.brute_find_roadblocks(grid, fleet=self.fleet_boss_index)
            roadblocks = roadblocks.sort("weight", "cost")
            logger.info(f"Grids: {roadblocks}")
            self.fleet_1.clear_chosen_enemy(roadblocks[0], expected=expected)
            return True

        return False

    def brute_clear_boss(self) -> bool:
        """使用两支舰队暴力搜索并清理通往 Boss 的阻挡。"""
        boss = self.map.layout.select(is_boss=True)
        if boss:
            logger.info("Brute clear BOSS")
            grids = self.brute_find_roadblocks(boss[0], fleet=self.fleet_boss_index)
            if grids:
                if self.brute_fleet_meet():
                    return True
                logger.info("Brute clear BOSS roadblocks")
                grids = grids.sort("weight", "cost")
                logger.info(f"Grids: {grids}")
                self.clear_chosen_enemy(grids[0])
                return True
            return self.fleet_boss.clear_boss()
        if self.map.layout.select(may_boss=True, is_caught_by_siren=True):
            logger.info("BOSS appear on fleet grid")
            self.fleet_2.switch_to()
            return self.clear_chosen_enemy(self.map.layout.select(may_boss=True, is_caught_by_siren=True)[0])
        logger.warning("BOSS not detected, trying all boss spawn point.")
        return self.clear_potential_boss()

    def brute_fleet_meet(self) -> bool:
        """暴力搜索并清理两支舰队之间的阻挡。"""
        if self.fleet_boss_index != 2 or not self.fleet_2_location:
            return False
        grids = self.brute_find_roadblocks(self.map[self.fleet_2_location], fleet=1)
        if grids:
            logger.info("Brute clear roadblocks between fleets.")
            grids = grids.sort("weight", "cost")
            logger.info(f"Grids: {grids}")
            self.clear_chosen_enemy(grids[0])
            return True
        return False

    def clear_siren(self, **kwargs: object) -> bool:
        if not self.config.MAP_HAS_SIREN and not self.config.MAP_HAS_FORTRESS:
            return False

        if self.config.fleet_2:
            kwargs = {**kwargs, "sort": ("weight", "cost_2")}
        grids = self.map.layout.select(is_siren=True)
        if self.config.MAP_HAS_FORTRESS:
            grids = grids.add(self.map.layout.select(is_fortress=True))
        grids = self.select_grids(grids, GridSelection.from_settings(kwargs))

        if grids:
            logger.hr("Clear siren")
            self.show_select_grids(grids, **kwargs)
            expected = "fortress" if grids[0].is_fortress else "siren"
            self.clear_chosen_enemy(grids[0], expected=expected)
            return True

        return False

    def clear_any_enemy(self, **kwargs: object) -> bool:
        grids = self.map.layout.select(is_enemy=True, is_boss=False)

        if self.config.MAP_HAS_SIREN:
            grids = grids.add(self.map.layout.select(is_siren=True))
        if self.config.MAP_HAS_FORTRESS:
            grids = grids.add(self.map.layout.select(is_fortress=True))

        grids = self.select_grids(grids, GridSelection.from_settings(kwargs))

        if grids:
            logger.hr("Clear enemy")
            self.show_select_grids(grids, **kwargs)
            grid = grids[0]
            if grid.is_fortress:
                expected = "fortress"
            elif grid.is_siren:
                expected = "siren"
            else:
                expected = ""
            self.clear_chosen_enemy(grid, expected=expected)
            return True

        return False

    def fleet_2_step_on(self, grids: SelectedGrids[GridInfo], roadblocks: Iterable[RoadGrids[GridInfo]]) -> bool:
        """让二队踏上指定格以降低另一队伏击率，并处理沿途阻挡；清敌后返回 True。"""
        if not self.config.fleet_2:
            return False
        for grid in grids:
            if self.fleet_at(grid=grid, fleet=2):
                return False
        all_cleared = grids.select(is_cleared=True).count == grids.count

        logger.info("Fleet 2 step on")
        for grid in grids:
            if grid.is_enemy or (not all_cleared and grid.is_cleared):
                continue
            if self.check_accessibility(grid=grid, fleet=2):
                logger.info(f"Fleet_2 step on {grid}")
                self.fleet_2.goto(grid)
                self.fleet_1.switch_to()
                return False

        logger.info("Fleet_2 step on got roadblocks.")
        clear = self.fleet_1.clear_roadblocks(roadblocks)
        self.fleet_1.clear_all_mystery()
        return clear

    def fleet_2_break_siren_caught(self) -> bool:
        if self.fleet_boss_index != 2:
            return False
        if not self.config.MAP_HAS_SIREN or not self.config.MAP_HAS_MOVABLE_ENEMY:
            return False
        if not self.map.layout.select(is_caught_by_siren=True):
            logger.info("No fleet caught by siren.")
            return False
        if not self.fleet_2_location or not self.map[self.fleet_2_location].is_caught_by_siren:
            logger.warning("Appear caught by siren, but not fleet_2.")
            for grid in self.map:
                grid.is_caught_by_siren = False
            return False

        logger.info(f"Break siren caught, fleet_2: {self.fleet_2_location}")
        self.fleet_2.switch_to()
        self.ensure_edge_insight()
        self.clear_chosen_enemy(self.map[self.fleet_2_location])
        self.fleet_1.switch_to()
        for grid in self.map:
            grid.is_caught_by_siren = False
        return True

    def fleet_2_push_forward(self) -> bool:
        """把二队推向更低权重格，降低 7～9 章单行道中 Boss 队被敌人堵住的概率。"""
        if self.fleet_boss_index != 2:
            return False
        if self.fleet_1_location is None or self.fleet_2_location is None:
            logger.warning("Fleet location missing while pushing fleet 2")
            return False

        logger.info("Fleet_2 push forward")
        grids = self.map.layout.select(is_land=False).sort("weight", "cost")
        if self.map[self.fleet_2_location].weight <= grids[0].weight:
            logger.info("Fleet_2 pushed to destination")
            self.fleet_1.switch_to()
            return False

        fleets = SelectedGrids([self.map[self.fleet_1_location], self.map[self.fleet_2_location]])
        grids = grids.select(is_accessible_2=True, is_sea=True).delete(fleets)
        if not grids:
            logger.info("Fleet_2 has no where to push")
            return False
        if self.map[self.fleet_2_location].weight <= grids[0].weight:
            logger.info("Fleet_2 pushed to closest grid")
            return False

        logger.info(f"Grids: {grids}")
        logger.info(f"Push forward: {grids[0]}")
        self.fleet_2.goto(grids[0])
        self.fleet_1.switch_to()
        return True

    def fleet_2_rescue(self, grid: GridInfo) -> bool:
        """让道中队前往通常为 Boss 刷新点的目标格救援 Boss 队；清敌后返回 True。"""
        if self.fleet_boss_index != 2:
            return False

        grids = self.brute_find_roadblocks(grid, fleet=2)
        if not grids:
            return False
        logger.info("Fleet_2 rescue")
        grids = self.select_grids(grids)
        if not grids:
            return False

        self.clear_chosen_enemy(grids[0])
        return True

    def fleet_2_protect(self) -> bool:
        """让道中队环绕 Boss 队并清理接近的塞壬；清敌后返回 True。"""
        if not self.config.fleet_2 or not self.config.MAP_HAS_MOVABLE_ENEMY:
            return False

        # 使用两支舰队时。
        for _n in range(20):
            if not self.map.layout.select(is_siren=True):
                return False

            nearby = self.map.layout.select(cost_2=1).add(self.map.layout.select(cost_2=2))
            approaching = SelectedGrids([])
            if self.config.MAP_HAS_MOVABLE_ENEMY:
                approaching = approaching.add(nearby.select(is_siren=True))
            if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
                approaching = approaching.add(nearby.select(is_enemy=True))
            if approaching:
                grids = self.select_grids(approaching, GridSelection(sort=("cost_2", "cost_1")))
                self.clear_chosen_enemy(grids[0], expected="siren")
                return True
            grids = nearby.delete(self.map.layout.select(is_fleet=True))
            grids = self.select_grids(grids, GridSelection(sort=("cost_2", "cost_1")))
            self.goto(grids[0])
            continue

        logger.warning("fleet_2_protect no siren approaching")
        return False

    def clear_filter_enemy(self, string: str, preserve: int = 0) -> bool:
        """按由易到难的过滤串清敌；非默认权重或有普通移动敌人时忽略过滤，preserve 保留最易敌人供无弹药战斗。"""
        if self.config.MAP_HAS_MOVABLE_NORMAL_ENEMY:
            return bool(self.clear_any_enemy(sort=("cost_2",)))

        if self.config.EnemyPriority_EnemyScaleBalanceWeight == "S3_enemy_first":
            string = "3L > 3M > 3E > 3C > 2L > 2M > 2E > 2C > 1L > 1M > 1E > 1C"
            preserve = 0
        elif self.config.EnemyPriority_EnemyScaleBalanceWeight == "S1_enemy_first":
            string = "1L > 1M > 1E > 1C > 2L > 2M > 2E > 2C > 3L > 3M > 3E > 3C"

        ENEMY_FILTER.load(string)
        grids = self.map.layout.select(is_enemy=True, is_accessible=True)
        if not grids:
            return False

        grids = cast("list[GridInfo]", ENEMY_FILTER.apply(grids.sort("weight", "cost").grids))
        logger.info(f"Filter enemy: {grids}, preserve={preserve}")
        if preserve:
            grids = grids[preserve:]

        if grids:
            logger.hr("Clear filter enemy")
            self.clear_chosen_enemy(grids[0])
            return True

        return False

    def clear_bouncing_enemy(self) -> bool:
        """清理固定路线上的唯一弹跳敌人；成功后禁用该路线。"""
        if not self.config.MAP_HAS_BOUNCING_ENEMY:
            return False

        route = None
        for a_route in self.map.bouncing_enemy_data:
            if a_route.select(may_bouncing_enemy=True, is_accessible=True):
                route = a_route
                break
        if route is None:
            return False

        logger.hr("Clear bouncing enemy")
        logger.info(f"Clear bouncing enemy: {route}")
        self.show_fleet()
        prev = self.battle_count
        for n, grid in enumerate(itertools.cycle(route)):
            if self.emotion.is_calculate and self.config.Campaign_UseFleetLock:
                self.emotion.wait(fleet_index=self.fleet_current_index)
            self.goto(grid, expected="combat_nothing")

            if self.battle_count > prev:
                logger.info("Cleared an bouncing enemy")
                route.select(may_bouncing_enemy=True).set(may_bouncing_enemy=False)
                self.full_scan()
                self.find_path_initial()
                self.map.pathfinder.show_cost()
                return True
            if n >= 12:
                logger.warning("Failed to clear bouncing enemy after 12 trial")
                return False

        return False
