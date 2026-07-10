import random
from dataclasses import dataclass
from typing import Protocol

from module.logger import logger


class PolicyConfig(Protocol):
    def override(self, **kwargs: object) -> None: ...


class StageLoopConfig(PolicyConfig, Protocol):
    StopCondition_RunCount: int


class StagePolicyConfig(PolicyConfig, Protocol):
    StopCondition_MapAchievement: str


@dataclass(frozen=True, slots=True)
class CampaignPolicy:
    """单个活动包允许声明的有限运行策略。"""

    aliases: tuple[tuple[str, str], ...] = ()
    loops: tuple[tuple[str, tuple[str, ...]], ...] = ()
    force_threat_safe_stages: tuple[str, ...] = ()
    resource_free_stages: tuple[str, ...] = ()
    map_achievement_fallbacks: tuple[tuple[str, str], ...] = ()

    def __post_init__(self) -> None:
        object.__setattr__(self, "aliases", tuple((source, target) for source, target in self.aliases))
        object.__setattr__(
            self,
            "loops",
            tuple((alias, tuple(stages)) for alias, stages in self.loops),
        )
        object.__setattr__(self, "force_threat_safe_stages", tuple(self.force_threat_safe_stages))
        object.__setattr__(self, "resource_free_stages", tuple(self.resource_free_stages))
        object.__setattr__(self, "map_achievement_fallbacks", tuple(self.map_achievement_fallbacks))

    def resolve_alias(self, stage: str) -> str:
        return dict(self.aliases).get(stage, stage)

    def loop_stages(self, alias: str) -> tuple[str, ...] | None:
        return dict(self.loops).get(alias)


def resolve_stage_loop(
    stage: str,
    pack_id: str,
    policy: CampaignPolicy,
    config: StageLoopConfig,
) -> tuple[str, bool]:
    """按剩余次数选择循环关卡，随机和倒序取模语义保持不变。"""
    stages = policy.loop_stages(stage)
    if stages is None:
        return stage, False

    cycle = len(stages)
    count = int(config.StopCondition_RunCount)
    if count == 0:
        selected = random.choice(stages)
        logger.info(f"Loop stages in {stage.upper()} of {pack_id}, run random stage: {selected}")
    else:
        index = count % cycle
        index = 0 if index == 0 else cycle - index
        selected = stages[index]
        logger.info(
            f"Loop stages in {stage.upper()} of {pack_id} with remain run_count={count}, run ordered stage: {selected}"
        )

    logger.info("disable continuous clear")
    config.override(StopCondition_MapAchievement="non_stop")
    config.override(StopCondition_StageIncrease=False)
    return selected, True


def apply_stage_policy(
    stage: str,
    pack_id: str,
    policy: CampaignPolicy,
    config: StagePolicyConfig,
) -> None:
    """应用只依赖精确关卡名的有限配置覆盖。"""
    if stage in policy.force_threat_safe_stages and config.StopCondition_MapAchievement != "non_stop":
        logger.info(f"In {pack_id}/{stage}, MapAchievement is forced to threat_safe")
        config.override(StopCondition_MapAchievement="threat_safe")

    if stage in policy.resource_free_stages:
        logger.info(f"Apply resource-free stage policy for {pack_id}/{stage}")
        config.override(
            StopCondition_OilLimit=0,
            StopCondition_MapAchievement="100_percent_clear",
            StopCondition_StageIncrease=True,
            Emotion_Mode="ignore",
            Fleet_Fleet2=0,
            Submarine_Fleet=0,
        )


def apply_pack_policy(
    pack_id: str,
    policy: CampaignPolicy,
    config: StagePolicyConfig,
) -> None:
    """应用只依赖活动包的有限配置值回退。"""
    fallback = dict(policy.map_achievement_fallbacks).get(config.StopCondition_MapAchievement)
    if fallback is None:
        return
    logger.info(f"In {pack_id}, MapAchievement={config.StopCondition_MapAchievement} fallback to {fallback}")
    config.override(StopCondition_MapAchievement=fallback)
