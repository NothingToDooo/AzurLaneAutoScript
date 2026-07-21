from typing import TYPE_CHECKING, Literal, Protocol, cast

from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId
from module.exception import CampaignEnd
from module.logger import logger

from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
)

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.map.map_grids import SelectedGrids

HARD_BOSS_CLEAR_MESSAGE = "BOSS Clear."


class _HardConfig(Protocol):
    def apply_runtime_overlay(self, **kwargs: object) -> None: ...


class _HardMapLayout(Protocol):
    def select(self, **kwargs: object) -> SelectedGrids[object]: ...


class _HardMap(Protocol):
    @property
    def layout(self) -> _HardMapLayout: ...


class _HardRuntimeHost(Protocol):
    config: _HardConfig
    map: _HardMap

    def goto(
        self,
        location: object,
        expected: str = "",
        *,
        step_optimize: bool | None = None,
        turning_optimize: bool | None = None,
    ) -> None: ...

    def clear_potential_boss(self) -> bool: ...


def _host(runtime: object) -> _HardRuntimeHost:
    return cast("_HardRuntimeHost", runtime)


class CampaignClearModeExecutor(RuntimeExecutorInstance):
    """封装困难关卡固定的运行配置、结束语义与 Boss 清理流程。"""

    __slots__ = ()

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        _ = context.options(RuntimeExecutorKind.HARD_MODE)
        super().__init__({RuntimeExecutorKind.HARD_MODE})

    @staticmethod
    def apply_runtime_config(runtime: object) -> None:
        host = _host(runtime)
        host.config.apply_runtime_overlay(MAP_HAS_AMBUSH=False)

    @staticmethod
    def expected_end(expected: str) -> Literal["in_stage"]:
        del expected
        return "in_stage"

    @staticmethod
    def clear_boss(runtime: object) -> bool:
        host = _host(runtime)
        grids = host.map.layout.select(is_boss=True)
        grids = grids.add(host.map.layout.select(may_boss=True, is_enemy=True))
        logger.info(f"May boss: {host.map.layout.select(may_boss=True)}")
        logger.info(f"May boss and is enemy: {host.map.layout.select(may_boss=True, is_enemy=True)}")
        logger.info(f"Is boss: {host.map.layout.select(is_boss=True)}")
        if grids:
            logger.hr("Clear BOSS")
            grids = grids.sort("weight", "cost")
            logger.info(f"Grids: {grids}")
            # 困难模式直接点击 Boss 格，不启用路径与转向优化。
            host.goto(grids[0], expected="boss", step_optimize=False, turning_optimize=False)
            raise CampaignEnd(HARD_BOSS_CLEAR_MESSAGE)

        logger.warning("BOSS not detected, trying all boss spawn point.")
        host.clear_potential_boss()
        return False


def build_campaign_clear_mode_behavior(
    instances: Iterable[object],
) -> CampaignClearModeExecutor | None:
    values = tuple(instances)
    if not values:
        return None
    if len(values) > 1:
        message = "campaign runtime accepts at most one hard clear-mode behavior"
        raise CampaignRuntimeProfileError(message)
    behavior = values[0]
    if not isinstance(behavior, CampaignClearModeExecutor):
        message = "campaign hard-mode executor must provide CampaignClearModeExecutor"
        raise CampaignRuntimeProfileError(message)
    return behavior


def _build_campaign_clear_mode(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return CampaignClearModeExecutor(context)


def hard_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("hard_mode/campaign_clear_mode"),
            {RuntimeExecutorKind.HARD_MODE: RuntimeExecutorOptionsSchema()},
            _build_campaign_clear_mode,
        ),
    )
