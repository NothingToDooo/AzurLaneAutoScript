from dataclasses import dataclass

from module.content.errors import ContentValidationError

MAP_ACHIEVEMENT_VALUES = (
    "non_stop",
    "100_percent_clear",
    "map_3_stars",
    "threat_safe",
    "threat_safe_without_3_stars",
)


@dataclass(frozen=True, slots=True)
class StageProgressionRule:
    """声明一个关卡的直接后继；`None` 表示该规则在当前包内终止。"""

    stage: str
    next_stage: str | None

    def __post_init__(self) -> None:
        if not isinstance(self.stage, str) or not self.stage:
            message = "progression rule stage must be a non-empty string"
            raise ContentValidationError(message)
        if self.next_stage is not None and (not isinstance(self.next_stage, str) or not self.next_stage):
            message = "progression rule next_stage must be a non-empty string or None"
            raise ContentValidationError(message)


@dataclass(frozen=True, slots=True)
class CampaignPolicy:
    """单个活动包允许声明的有限运行策略。"""

    aliases: tuple[tuple[str, str], ...] = ()
    progressions: tuple[StageProgressionRule, ...] = ()
    loops: tuple[tuple[str, tuple[str, ...]], ...] = ()
    force_threat_safe_stages: tuple[str, ...] = ()
    resource_free_stages: tuple[str, ...] = ()
    map_achievement_fallbacks: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        aliases = tuple((source, target) for source, target in self.aliases)
        if len({source for source, _ in aliases}) != len(aliases):
            message = "duplicate alias key"
            raise ContentValidationError(message)
        progressions = tuple(self.progressions)
        if any(not isinstance(rule, StageProgressionRule) for rule in progressions):
            message = "progressions must contain StageProgressionRule values"
            raise TypeError(message)
        if len({rule.stage for rule in progressions}) != len(progressions):
            message = "progression rules must have unique stages"
            raise ContentValidationError(message)
        loops = tuple((alias, tuple(stages)) for alias, stages in self.loops)
        if len({alias for alias, _ in loops}) != len(loops):
            message = "duplicate loop key"
            raise ContentValidationError(message)
        if any(not stages for _, stages in loops):
            message = "loop stages must not be empty"
            raise ContentValidationError(message)
        map_achievement_fallbacks = tuple((source, target) for source, target in self.map_achievement_fallbacks)
        if any(
            not isinstance(value, str) or value not in MAP_ACHIEVEMENT_VALUES
            for pair in map_achievement_fallbacks
            for value in pair
        ):
            message = f"map_achievement_fallbacks must use supported MapAchievement values: {MAP_ACHIEVEMENT_VALUES}"
            raise ContentValidationError(message)
        fallback_sources = {source for source, _ in map_achievement_fallbacks}
        if len(fallback_sources) != len(map_achievement_fallbacks):
            message = "map_achievement_fallbacks must have unique sources for single-step idempotence"
            raise ContentValidationError(message)
        fallback_targets = {target for _, target in map_achievement_fallbacks}
        if not fallback_sources.isdisjoint(fallback_targets):
            message = "map_achievement_fallbacks source and target sets must be disjoint for single-step idempotence"
            raise ContentValidationError(message)

        object.__setattr__(self, "aliases", aliases)
        object.__setattr__(self, "progressions", progressions)
        object.__setattr__(
            self,
            "loops",
            loops,
        )
        object.__setattr__(self, "force_threat_safe_stages", tuple(self.force_threat_safe_stages))
        object.__setattr__(self, "resource_free_stages", tuple(self.resource_free_stages))
        object.__setattr__(self, "map_achievement_fallbacks", map_achievement_fallbacks)

    def resolve_alias(self, stage: str) -> str:
        return dict(self.aliases).get(stage, stage)

    def loop_stages(self, alias: str) -> tuple[str, ...] | None:
        return dict(self.loops).get(alias)

    def next_stage(self, stage: str) -> str | None:
        return {rule.stage: rule.next_stage for rule in self.progressions}.get(stage)
