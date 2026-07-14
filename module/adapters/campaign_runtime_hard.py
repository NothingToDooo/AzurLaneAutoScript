from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, cast

from module.base.timer import Timer
from module.content.runtime_profile import RuntimeExecutorKind, RuntimeImplementationId, RuntimeTuningValue
from module.exception import CampaignEnd
from module.logger import logger
from module.map.assets import FLEET_PREPARATION, MAP_PREPARATION
from module.ui.assets import CAMPAIGN_CHECK

from .campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    RuntimeExecutorBuildContext,
    RuntimeExecutorFactoryDescriptor,
    RuntimeExecutorInstance,
    RuntimeExecutorOptionsSchema,
    RuntimeOperation,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.map.map_grids import SelectedGrids

HARD_BOSS_CLEAR_MESSAGE = "BOSS Clear."

_OPERATIONS = frozenset(
    {
        "_expected_end",
        "clear_boss",
        "equipment_take_off_when_finished",
    }
)


class _HardConfig(Protocol):
    ENABLE_EMOTION_REDUCE: bool
    ENABLE_HP_BALANCE: bool
    FLEET_HARD_EQUIPMENT: object | None
    MAP_HAS_AMBUSH: bool

    def apply_runtime_overlay(self, **kwargs: object) -> None: ...


class _HardDevice(Protocol):
    def screenshot(self) -> object: ...

    def click(self, button: object) -> object: ...


class _HardMap(Protocol):
    def select(self, **kwargs: object) -> SelectedGrids[object]: ...


class _HardRuntimeHost(Protocol):
    config: _HardConfig
    device: _HardDevice
    map: _HardMap
    ENTRANCE: object
    equipment_has_take_on: bool

    def _goto(self, location: object, expected: str = "") -> None: ...

    def appear(self, button: object, *, offset: tuple[int, int]) -> bool: ...

    def clear_potential_boss(self) -> bool: ...

    def equipment_take_off(self) -> bool: ...

    def handle_retirement(self) -> bool: ...

    def is_in_stage(self) -> bool: ...

    def ui_back(self, *, check_button: object, appear_button: object) -> object: ...


def _host(runtime: object) -> _HardRuntimeHost:
    return cast("_HardRuntimeHost", runtime)


def _strings(options: Mapping[str, RuntimeTuningValue], name: str) -> tuple[str, ...]:
    value = options[name]
    if not isinstance(value, tuple) or any(not isinstance(item, str) or not item for item in value):
        message = f"runtime hard option {name} must contain strings"
        raise CampaignRuntimeProfileError(message)
    return cast("tuple[str, ...]", value)


class CampaignClearModeExecutor(RuntimeExecutorInstance):
    """封装困难关卡的结束语义、Boss 清理和装备回收流程。"""

    __slots__ = ("_enable_emotion_reduce", "_enable_hp_balance", "_expected_end_value")

    def __init__(self, context: RuntimeExecutorBuildContext) -> None:
        options = context.options(RuntimeExecutorKind.HARD_MODE)
        operations = frozenset(_strings(options, "operations"))
        if operations != _OPERATIONS:
            message = f"runtime hard operations mismatch: expected={sorted(_OPERATIONS)}, actual={sorted(operations)}"
            raise CampaignRuntimeProfileError(message)
        enable_hp_balance = options["enable_hp_balance"]
        if enable_hp_balance is not False:
            message = "hard clear mode requires enable_hp_balance=false"
            raise CampaignRuntimeProfileError(message)
        enable_emotion_reduce = options["enable_emotion_reduce"]
        if enable_emotion_reduce is not False:
            message = "hard clear mode requires enable_emotion_reduce=false"
            raise CampaignRuntimeProfileError(message)
        expected_end = options["expected_end"]
        if expected_end != "in_stage":
            message = "hard clear mode expected_end must be 'in_stage'"
            raise CampaignRuntimeProfileError(message)
        self._enable_hp_balance = False
        self._enable_emotion_reduce = False
        self._expected_end_value = "in_stage"
        super().__init__(
            {RuntimeExecutorKind.HARD_MODE},
            methods={
                RuntimeExecutorKind.HARD_MODE: {
                    RuntimeOperation.EXPECTED_END: self._expected_end,
                    RuntimeOperation.CLEAR_BOSS: self._clear_boss,
                    RuntimeOperation.EQUIPMENT_TAKE_OFF_WHEN_FINISHED: (self._equipment_take_off_when_finished),
                    RuntimeOperation.RUNTIME_CREATED: self._runtime_created,
                }
            },
        )

    def _runtime_created(self, runtime: object) -> None:
        host = _host(runtime)
        host.config.apply_runtime_overlay(
            ENABLE_EMOTION_REDUCE=self._enable_emotion_reduce,
            ENABLE_HP_BALANCE=self._enable_hp_balance,
            MAP_HAS_AMBUSH=False,
        )

    def _expected_end(self, runtime: object, expected: object) -> str:
        del runtime, expected
        return self._expected_end_value

    @staticmethod
    def _clear_boss(runtime: object) -> bool:
        host = _host(runtime)
        grids = host.map.select(is_boss=True)
        grids = grids.add(host.map.select(may_boss=True, is_enemy=True))
        logger.info(f"May boss: {host.map.select(may_boss=True)}")
        logger.info(f"May boss and is enemy: {host.map.select(may_boss=True, is_enemy=True)}")
        logger.info(f"Is boss: {host.map.select(is_boss=True)}")
        if grids:
            logger.hr("Clear BOSS")
            grids = grids.sort("weight", "cost")
            logger.info(f"Grids: {grids}")
            # 困难模式的旧扩展契约以 `_goto` 作为唯一移动入口。
            host._goto(grids[0], expected="boss")  # noqa: SLF001
            raise CampaignEnd(HARD_BOSS_CLEAR_MESSAGE)

        logger.warning("BOSS not detected, trying all boss spawn point.")
        host.clear_potential_boss()
        return False

    @staticmethod
    def _equipment_take_off_when_finished(runtime: object) -> bool:
        host = _host(runtime)
        if host.config.FLEET_HARD_EQUIPMENT is None:
            return False
        if not host.equipment_has_take_on:
            return False

        logger.info("equipment_take_off_when_finished")
        campaign_timer = Timer(2)
        map_timer = Timer(1)
        fleet_timer = Timer(1)

        while True:
            host.device.screenshot()

            if campaign_timer.reached() and host.is_in_stage():
                host.device.click(host.ENTRANCE)
                campaign_timer.reset()
                continue

            if map_timer.reached() and host.appear(MAP_PREPARATION, offset=(20, 20)):
                host.device.click(MAP_PREPARATION)
                map_timer.reset()
                campaign_timer.reset()
                continue

            if fleet_timer.reached() and host.appear(FLEET_PREPARATION, offset=(20, 50)):
                host.equipment_take_off()
                host.ui_back(
                    check_button=CAMPAIGN_CHECK,
                    appear_button=FLEET_PREPARATION,
                )
                break

            if host.handle_retirement():
                continue

        return True


def _build_campaign_clear_mode(context: RuntimeExecutorBuildContext) -> RuntimeExecutorInstance:
    return CampaignClearModeExecutor(context)


def hard_runtime_executor_descriptors() -> tuple[RuntimeExecutorFactoryDescriptor, ...]:
    return (
        RuntimeExecutorFactoryDescriptor(
            RuntimeImplementationId("hard_mode/campaign_clear_mode"),
            {
                RuntimeExecutorKind.HARD_MODE: RuntimeExecutorOptionsSchema(
                    required=frozenset(
                        {
                            "operations",
                            "expected_end",
                            "enable_hp_balance",
                            "enable_emotion_reduce",
                        }
                    )
                )
            },
            _build_campaign_clear_mode,
        ),
    )
