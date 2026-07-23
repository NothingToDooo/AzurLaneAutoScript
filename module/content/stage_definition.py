import math
from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from module.content.battle_policy import BattlePolicy, StagePolicy
from module.content.battle_program import BattleProgram, BossApproachPlan
from module.content.cell import CellId
from module.content.errors import ContentValidationError
from module.content.hard_mode_policy import HardModeRuntimePolicy
from module.content.mechanic_rules import StageMechanicRules
from module.content.models import StageRef
from module.content.runtime_profile import CampaignRuntimeProfile
from module.content.stage_rules import StageRules
from module.content.war_archives_profile import WarArchivesDefinition

if TYPE_CHECKING:
    from collections.abc import Mapping

# SI 是历史关卡由自定义 map_data_init 补状态的已知占位。
MAP_CELL_TOKENS = frozenset({"--", "++", "SP", "ME", "MB", "MS", "MM", "MA", "__", "SI"})


@dataclass(frozen=True, slots=True)
class GridShape:
    columns: int
    rows: int

    def __post_init__(self) -> None:
        if type(self.columns) is not int or self.columns <= 0:
            message = "grid columns must be a positive integer"
            raise ContentValidationError(message)
        if type(self.rows) is not int or self.rows <= 0:
            message = "grid rows must be a positive integer"
            raise ContentValidationError(message)

    def contains(self, cell: CellId) -> bool:
        return 0 <= cell.x < self.columns and 0 <= cell.y < self.rows

    def cell_ids(self) -> tuple[CellId, ...]:
        return tuple(CellId(x, y) for y in range(self.rows) for x in range(self.columns))


@dataclass(frozen=True, slots=True)
class CellSpec:
    cell_id: CellId
    token: str
    weight: float

    def __post_init__(self) -> None:
        if not isinstance(self.cell_id, CellId):
            message = "cell_id must be a CellId"
            raise TypeError(message)
        if not isinstance(self.token, str) or self.token.upper() not in MAP_CELL_TOKENS:
            message = f"unknown map cell token: {self.token!r}"
            raise ContentValidationError(message)
        if type(self.weight) is not float or not math.isfinite(self.weight):
            message = "cell weight must be a finite float"
            raise ContentValidationError(message)


@dataclass(frozen=True, slots=True)
class SpawnWave:
    battle: int
    enemy: int = 0
    siren: int = 0
    mystery: int = 0
    boss: int = 0

    def __post_init__(self) -> None:
        values = {
            "battle": self.battle,
            "enemy": self.enemy,
            "siren": self.siren,
            "mystery": self.mystery,
            "boss": self.boss,
        }
        for name, value in values.items():
            if type(value) is not int or value < 0:
                message = f"spawn wave {name} must be a non-negative integer"
                raise ContentValidationError(message)
        if self.boss > 1:
            message = "spawn wave boss count must not exceed 1"
            raise ContentValidationError(message)

    @property
    def is_boss(self) -> bool:
        return self.boss == 1


@dataclass(frozen=True, slots=True)
class RunVariant:
    cells: tuple[CellSpec, ...]
    spawn_waves: tuple[SpawnWave, ...]

    def __post_init__(self) -> None:
        cells = tuple(self.cells)
        spawn_waves = tuple(self.spawn_waves)
        if any(not isinstance(cell, CellSpec) for cell in cells):
            message = "run variant cells must contain CellSpec values"
            raise TypeError(message)
        if any(not isinstance(wave, SpawnWave) for wave in spawn_waves):
            message = "run variant spawn_waves must contain SpawnWave values"
            raise TypeError(message)
        if tuple(wave.battle for wave in spawn_waves) != tuple(range(len(spawn_waves))):
            message = "run variant battles must be contiguous and ordered from zero"
            raise ContentValidationError(message)
        object.__setattr__(self, "cells", cells)
        object.__setattr__(self, "spawn_waves", spawn_waves)

    @property
    def battles(self) -> frozenset[int]:
        return frozenset(wave.battle for wave in self.spawn_waves)

    @property
    def boss_battles(self) -> frozenset[int]:
        return frozenset(wave.battle for wave in self.spawn_waves if wave.is_boss)


@dataclass(frozen=True, slots=True)
class PortalSpec:
    source: CellId
    target: CellId

    def __post_init__(self) -> None:
        if not isinstance(self.source, CellId) or not isinstance(self.target, CellId):
            message = "portal endpoints must be CellId values"
            raise TypeError(message)


class LandBasedDirection(StrEnum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


@dataclass(frozen=True, slots=True)
class LandBasedSpec:
    cell_id: CellId
    direction: LandBasedDirection

    def __post_init__(self) -> None:
        if not isinstance(self.cell_id, CellId):
            message = "land-based cell_id must be a CellId"
            raise TypeError(message)
        if not isinstance(self.direction, LandBasedDirection):
            message = "land-based direction must be a LandBasedDirection"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class MapDefinition:
    name: str
    shape: GridShape
    camera_data: tuple[CellId, ...]
    camera_data_spawn_point: tuple[CellId, ...]
    normal: RunVariant
    loop: RunVariant
    map_covered: tuple[CellId, ...] = ()
    portals: tuple[PortalSpec, ...] = ()
    land_based: tuple[LandBasedSpec, ...] = ()
    normal_enemy_spawn_candidates: tuple[CellId, ...] | None = None

    def __post_init__(self) -> None:
        self._validate_root_types()
        camera_data = tuple(self.camera_data)
        camera_spawn = tuple(self.camera_data_spawn_point)
        map_covered = tuple(self.map_covered)
        portals = tuple(self.portals)
        land_based = tuple(self.land_based)
        candidates = None if self.normal_enemy_spawn_candidates is None else tuple(self.normal_enemy_spawn_candidates)
        self._validate_collection_types(camera_data, camera_spawn, map_covered, portals, land_based)
        self._validate_normal_enemy_spawn_candidates(candidates)
        self._validate_variants()
        self._validate_referenced_cells(camera_data, camera_spawn, map_covered, portals, land_based)

        object.__setattr__(self, "camera_data", camera_data)
        object.__setattr__(self, "camera_data_spawn_point", camera_spawn)
        object.__setattr__(self, "map_covered", map_covered)
        object.__setattr__(self, "portals", portals)
        object.__setattr__(self, "land_based", land_based)
        object.__setattr__(self, "normal_enemy_spawn_candidates", candidates)

    def _validate_root_types(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            message = "map name must be a non-empty string"
            raise ContentValidationError(message)
        if not isinstance(self.shape, GridShape):
            message = "map shape must be a GridShape"
            raise TypeError(message)
        if not isinstance(self.normal, RunVariant) or not isinstance(self.loop, RunVariant):
            message = "map variants must be RunVariant values"
            raise TypeError(message)

    @staticmethod
    def _validate_collection_types(
        camera_data: tuple[CellId, ...],
        camera_spawn: tuple[CellId, ...],
        map_covered: tuple[CellId, ...],
        portals: tuple[PortalSpec, ...],
        land_based: tuple[LandBasedSpec, ...],
    ) -> None:
        if any(not isinstance(cell, CellId) for cell in (*camera_data, *camera_spawn)):
            message = "camera data must contain CellId values"
            raise TypeError(message)
        if any(not isinstance(cell, CellId) for cell in map_covered):
            message = "map_covered must contain CellId values"
            raise TypeError(message)
        if any(not isinstance(portal, PortalSpec) for portal in portals):
            message = "portals must contain PortalSpec values"
            raise TypeError(message)
        if any(not isinstance(unit, LandBasedSpec) for unit in land_based):
            message = "land_based must contain LandBasedSpec values"
            raise TypeError(message)

    def _validate_normal_enemy_spawn_candidates(self, candidates: tuple[CellId, ...] | None) -> None:
        if candidates is None:
            return
        if any(not isinstance(cell, CellId) for cell in candidates):
            message = "normal_enemy_spawn_candidates must contain CellId values"
            raise TypeError(message)
        if not candidates:
            message = "normal_enemy_spawn_candidates must not be empty"
            raise ContentValidationError(message)
        if len(set(candidates)) != len(candidates):
            message = "normal_enemy_spawn_candidates must not contain duplicate cells"
            raise ContentValidationError(message)
        if any(not self.shape.contains(cell) for cell in candidates):
            message = "normal_enemy_spawn_candidates references a cell outside its shape"
            raise ContentValidationError(message)

    def _validate_variants(self) -> None:
        expected_cells = self.shape.cell_ids()
        for variant in (self.normal, self.loop):
            if tuple(cell.cell_id for cell in variant.cells) != expected_cells:
                message = "run variant cells must cover the map exactly in row-major order"
                raise ContentValidationError(message)
        if tuple(cell.weight for cell in self.normal.cells) != tuple(cell.weight for cell in self.loop.cells):
            message = "normal and loop variants must use the same cell weights"
            raise ContentValidationError(message)

    def _validate_referenced_cells(
        self,
        camera_data: tuple[CellId, ...],
        camera_spawn: tuple[CellId, ...],
        map_covered: tuple[CellId, ...],
        portals: tuple[PortalSpec, ...],
        land_based: tuple[LandBasedSpec, ...],
    ) -> None:
        referenced_cells = [*camera_data, *camera_spawn, *map_covered]
        referenced_cells.extend(endpoint for portal in portals for endpoint in (portal.source, portal.target))
        referenced_cells.extend(unit.cell_id for unit in land_based)
        if any(not self.shape.contains(cell) for cell in referenced_cells):
            message = "map references a cell outside its shape"
            raise ContentValidationError(message)

    @property
    def battles(self) -> frozenset[int]:
        return self.normal.battles | self.loop.battles

    @property
    def boss_battles(self) -> frozenset[int]:
        return self.normal.boss_battles | self.loop.boss_battles


@dataclass(frozen=True, slots=True)
class CampaignStageDefinition:
    ref: StageRef
    map: MapDefinition
    rules: StageRules
    enemy_filter: str
    battle_policies: Mapping[int, StagePolicy | BattlePolicy]
    runtime_profile: CampaignRuntimeProfile = field(default_factory=CampaignRuntimeProfile.core)
    mechanics: StageMechanicRules = field(default_factory=StageMechanicRules)
    battle_programs: Mapping[int, BattleProgram] = field(default_factory=dict)
    boss_approaches: Mapping[int, BossApproachPlan] = field(default_factory=dict)
    hard_mode: HardModeRuntimePolicy | None = None
    war_archives: WarArchivesDefinition | None = None

    def __post_init__(self) -> None:
        self._validate_root_types()
        policies = self._validated_policies()
        self._validate_mechanics()
        programs = self._validated_programs()
        approaches = self._validated_boss_approaches()
        if self.hard_mode is not None and not isinstance(self.hard_mode, HardModeRuntimePolicy):
            message = "hard_mode must be a HardModeRuntimePolicy or None"
            raise TypeError(message)
        if self.war_archives is not None and not isinstance(self.war_archives, WarArchivesDefinition):
            message = "war_archives must be a WarArchivesDefinition or None"
            raise TypeError(message)

        object.__setattr__(self, "battle_policies", MappingProxyType(policies))
        object.__setattr__(self, "battle_programs", MappingProxyType(programs))
        object.__setattr__(self, "boss_approaches", MappingProxyType(approaches))

    def _validate_root_types(self) -> None:
        if not isinstance(self.ref, StageRef):
            message = "ref must be a StageRef"
            raise TypeError(message)
        if not isinstance(self.map, MapDefinition):
            message = "map must be a MapDefinition"
            raise TypeError(message)
        if not isinstance(self.rules, StageRules):
            message = "rules must be StageRules"
            raise TypeError(message)
        if not isinstance(self.enemy_filter, str) or not self.enemy_filter.strip():
            message = "enemy_filter must be a non-empty string"
            raise ContentValidationError(message)
        if not isinstance(self.runtime_profile, CampaignRuntimeProfile):
            message = "runtime_profile must be a CampaignRuntimeProfile"
            raise TypeError(message)

    def _validated_policies(self) -> dict[int, StagePolicy]:
        policies = self._normalized_policies()
        self._validate_policy_battle_references(policies)
        self._validate_policy_boss_constraints(policies)
        self._validate_policy_cell_references(policies)
        return policies

    def _normalized_policies(self) -> dict[int, StagePolicy]:
        policies = {
            battle: policy.to_stage_policy() if isinstance(policy, BattlePolicy) else policy
            for battle, policy in self.battle_policies.items()
        }
        if any(type(battle) is not int or battle < 0 for battle in policies):
            message = "battle policy keys must be non-negative integers"
            raise TypeError(message)
        if any(not isinstance(policy, StagePolicy) for policy in policies.values()):
            message = "battle_policies must contain StagePolicy values"
            raise TypeError(message)
        return policies

    def _validate_policy_battle_references(self, policies: dict[int, StagePolicy]) -> None:
        if not set(policies) <= self.map.battles:
            message = "battle policies must reference declared spawn battles"
            raise ContentValidationError(message)
        if not self.map.boss_battles <= set(policies):
            message = "boss spawn battles require an explicit stage policy"
            raise ContentValidationError(message)

    def _validate_policy_boss_constraints(self, policies: dict[int, StagePolicy]) -> None:
        for battle in self.map.boss_battles:
            if not policies[battle].clears_boss:
                message = f"boss battle {battle} policy must end with ClearBoss"
                raise ContentValidationError(message)
        non_boss_policies = set(policies) - self.map.boss_battles
        if any(policies[battle].clears_boss for battle in non_boss_policies):
            message = "ClearBoss steps may only appear on boss spawn battles"
            raise ContentValidationError(message)

    def _validate_policy_cell_references(self, policies: dict[int, StagePolicy]) -> None:
        if any(not self.map.shape.contains(cell) for policy in policies.values() for cell in policy.referenced_cells):
            message = "battle policies reference a cell outside the map shape"
            raise ContentValidationError(message)

    def _validate_mechanics(self) -> None:
        if not isinstance(self.mechanics, StageMechanicRules):
            message = "mechanics must be StageMechanicRules"
            raise TypeError(message)
        if not self.mechanics.referenced_battles <= self.map.battles:
            message = "mechanic rules must reference declared spawn battles"
            raise ContentValidationError(message)
        if any(not self.map.shape.contains(cell) for cell in self.mechanics.referenced_cells):
            message = "mechanic rules reference a cell outside the map shape"
            raise ContentValidationError(message)

    def _validated_programs(self) -> dict[int, BattleProgram]:
        programs = dict(self.battle_programs)
        if any(type(battle) is not int or battle < 0 for battle in programs):
            message = "battle program keys must be non-negative integers"
            raise TypeError(message)
        if any(not isinstance(program, BattleProgram) for program in programs.values()):
            message = "battle_programs must contain BattleProgram values"
            raise TypeError(message)
        if any(program.battle != battle for battle, program in programs.items()):
            message = "battle program keys must match each program battle"
            raise ContentValidationError(message)
        if not set(programs) <= self.map.battles:
            message = "battle programs must reference declared spawn battles"
            raise ContentValidationError(message)
        if any(not self.map.shape.contains(cell) for program in programs.values() for cell in program.referenced_cells):
            message = "battle programs reference a cell outside the map shape"
            raise ContentValidationError(message)
        return programs

    def _validated_boss_approaches(self) -> dict[int, BossApproachPlan]:
        approaches = dict(self.boss_approaches)
        if any(type(battle) is not int or battle < 0 for battle in approaches):
            message = "boss approach keys must be non-negative integers"
            raise TypeError(message)
        if any(not isinstance(approach, BossApproachPlan) for approach in approaches.values()):
            message = "boss_approaches must contain BossApproachPlan values"
            raise TypeError(message)
        if any(approach.battle != battle for battle, approach in approaches.items()):
            message = "boss approach keys must match each plan battle"
            raise ContentValidationError(message)
        if not set(approaches) <= self.map.boss_battles:
            message = "boss approaches must reference declared boss spawn battles"
            raise ContentValidationError(message)
        if any(
            not self.map.shape.contains(cell) for approach in approaches.values() for cell in approach.referenced_cells
        ):
            message = "boss approaches reference a cell outside the map shape"
            raise ContentValidationError(message)
        return approaches
