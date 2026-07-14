from __future__ import annotations

from datetime import datetime
from types import MappingProxyType
from typing import TYPE_CHECKING, cast

from module.adapters.facility_live import (
    CommissionEvidence,
    FacilityClock,
    LiveCommissionWorkflow,
    LiveResearchWorkflow,
    LiveTacticalWorkflow,
    ResearchQueueEvidence,
    SystemFacilityClock,
    TacticalEvidence,
)
from module.adapters.mumu12 import CancellationAwareMumu12Device
from module.commission.commission import RewardCommission
from module.config.config import AzurLaneConfig, name_to_function
from module.device.device import Device
from module.gameplay.facility import CommissionSettings, ResearchSettings, TacticalSettings
from module.gameplay.facility_factories import FacilityWorkflows
from module.research.research import RewardResearch
from module.tactical.tactical_class import RewardTacticalClass
from module.ui.page import page_research, page_reward

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.config.config_generated import ConfigOverrides
    from module.interaction import CancellationSignal


def _activate(
    config: AzurLaneConfig,
    device: Device,
    task_name: str,
    gameplay_fields: Mapping[str, object],
    cancellation: CancellationSignal,
) -> Device:
    cancellation.raise_if_requested()
    config.replace_runtime_overlay()
    task = name_to_function(task_name)
    config.task = task
    config.bind(task)
    overlay = cast("ConfigOverrides", dict(gameplay_fields))
    config.apply_runtime_overlay(**overlay)
    device.config = config
    return cast("Device", CancellationAwareMumu12Device(device, cancellation))


def _require_datetime(value: object, *, field_name: str) -> datetime:
    if not isinstance(value, datetime):
        message = f"{field_name} must be a datetime"
        raise TypeError(message)
    return value


def _clock_now(clock: FacilityClock) -> datetime:
    value = _require_datetime(clock.now(), field_name="facility clock value")
    if value.tzinfo is None or value.utcoffset() is None:
        message = "facility clock value must be timezone-aware"
        raise ValueError(message)
    return value


def _finish_is_due(finish_at: datetime, observed_at: datetime) -> bool:
    if finish_at.tzinfo is None or finish_at.utcoffset() is None:
        return finish_at <= observed_at.astimezone().replace(tzinfo=None)
    return finish_at <= observed_at.astimezone(finish_at.tzinfo)


def project_research_settings(settings: ResearchSettings) -> Mapping[str, object]:
    if not isinstance(settings, ResearchSettings):
        message = "settings must be ResearchSettings"
        raise TypeError(message)
    selection = settings.selection
    return MappingProxyType(
        {
            "Research_UseCube": selection.use_cube.value,
            "Research_UseCoin": selection.use_coin.value,
            "Research_UsePart": selection.use_part.value,
            "Research_AllowDelay": selection.allow_delay,
            "Research_PresetFilter": selection.preset_filter,
            "Research_CustomFilter": selection.custom_filter,
        }
    )


def project_commission_settings(settings: CommissionSettings) -> Mapping[str, object]:
    if not isinstance(settings, CommissionSettings):
        message = "settings must be CommissionSettings"
        raise TypeError(message)
    selection = settings.selection
    return MappingProxyType(
        {
            "Commission_PresetFilter": selection.preset_filter.value,
            "Commission_CustomFilter": selection.custom_filter,
            "Commission_DoMajorCommission": selection.do_major_commission,
        }
    )


def project_tactical_settings(settings: TacticalSettings) -> Mapping[str, object]:
    if not isinstance(settings, TacticalSettings):
        message = "settings must be TacticalSettings"
        raise TypeError(message)
    overflow = settings.experience_overflow
    student = settings.student
    return MappingProxyType(
        {
            "Tactical_TacticalFilter": settings.tactical_filter,
            "Tactical_RapidTrainingSlot": settings.rapid_training_slot.value,
            "ControlExpOverflow_Enable": overflow.enabled,
            "ControlExpOverflow_T1Allow": overflow.t1_allow,
            "ControlExpOverflow_T2Allow": overflow.t2_allow,
            "ControlExpOverflow_T3Allow": overflow.t3_allow,
            "ControlExpOverflow_T4Allow": overflow.t4_allow,
            "AddNewStudent_Enable": student.enabled,
            "AddNewStudent_Favorite": student.favorite,
            "AddNewStudent_MinLevel": student.minimum_level,
        }
    )


class Mumu12ResearchDriver:
    __slots__ = ("_clock", "_config", "_device")

    def __init__(self, config: AzurLaneConfig, device: Device, clock: FacilityClock) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        if isinstance(clock, type) or not callable(getattr(clock, "now", None)):
            message = "clock must implement now()"
            raise TypeError(message)
        self._config = config
        self._device = device
        self._clock = clock

    def execute(self, settings: ResearchSettings, cancellation: CancellationSignal) -> ResearchQueueEvidence:
        device = _activate(
            self._config,
            self._device,
            "Research",
            project_research_settings(settings),
            cancellation,
        )
        runner = RewardResearch(self._config, device=device)

        cancellation.raise_if_requested()
        runner.ui_ensure(page_research)
        cancellation.raise_if_requested()
        runner.queue_enter()
        cancellation.raise_if_requested()
        runner.queue_receive()
        cancellation.raise_if_requested()
        first_finish_at = runner.get_research_ended()
        cancellation.raise_if_requested()
        runner.queue_quit()

        cancellation.raise_if_requested()
        runner.receive_6th_research()
        cancellation.raise_if_requested()
        runner.research_fill_queue()
        cancellation.raise_if_requested()
        available_slots = runner.get_queue_slot()
        if available_slots == 5:
            return ResearchQueueEvidence(available_slots=5, first_finish_at=None)

        finish_at = _require_datetime(first_finish_at, field_name="first research finish time")
        if _finish_is_due(finish_at, _clock_now(self._clock)):
            cancellation.raise_if_requested()
            runner.queue_enter()
            cancellation.raise_if_requested()
            finish_at = _require_datetime(runner.get_research_ended(), field_name="refreshed research finish time")
            cancellation.raise_if_requested()
            runner.queue_quit()
        return ResearchQueueEvidence(available_slots=available_slots, first_finish_at=finish_at)


class Mumu12CommissionDriver:
    __slots__ = ("_config", "_device")

    def __init__(self, config: AzurLaneConfig, device: Device) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        self._config = config
        self._device = device

    def execute(self, settings: CommissionSettings, cancellation: CancellationSignal) -> CommissionEvidence:
        device = _activate(
            self._config,
            self._device,
            "Commission",
            project_commission_settings(settings),
            cancellation,
        )
        runner = RewardCommission(self._config, device=device)

        cancellation.raise_if_requested()
        runner.ui_ensure(page_reward)
        cancellation.raise_if_requested()
        runner.commission_receive()
        cancellation.raise_if_requested()
        runner.handle_info_bar()
        cancellation.raise_if_requested()
        runner.commission_start()

        total = runner.daily.add_by_eq(runner.urgent)
        raw_finish_times = total.get("finish_time")
        finish_times = tuple(
            sorted(
                _require_datetime(value, field_name="commission finish time")
                for value in raw_finish_times
                if value is not None
            )
        )
        daily_pending = runner.daily.select(category_str="daily", status="pending").count
        filtered_urgent_pending = runner.comm_choose.intersect_by_eq(runner.urgent.select(status="pending")).count
        return CommissionEvidence(
            finish_times=finish_times,
            daily_pending=daily_pending,
            filtered_urgent_pending=filtered_urgent_pending,
        )


class Mumu12TacticalDriver:
    __slots__ = ("_clock", "_config", "_device")

    def __init__(self, config: AzurLaneConfig, device: Device, clock: FacilityClock) -> None:
        if not isinstance(config, AzurLaneConfig):
            message = "config must be an AzurLaneConfig"
            raise TypeError(message)
        if not isinstance(device, Device):
            message = "device must be a Device"
            raise TypeError(message)
        if isinstance(clock, type) or not callable(getattr(clock, "now", None)):
            message = "clock must implement now()"
            raise TypeError(message)
        self._config = config
        self._device = device
        self._clock = clock

    def execute(self, settings: TacticalSettings, cancellation: CancellationSignal) -> TacticalEvidence:
        device = _activate(
            self._config,
            self._device,
            "Tactical",
            project_tactical_settings(settings),
            cancellation,
        )
        runner = RewardTacticalClass(self._config, device=device)

        cancellation.raise_if_requested()
        runner.ui_ensure(page_reward)
        cancellation.raise_if_requested()
        empty_finish_at = settings.server_update_schedule.next_after(_clock_now(self._clock))
        runner.tactical_class_receive(empty_finish_at=empty_finish_at)
        finish_times = tuple(
            _require_datetime(value, field_name="tactical finish time") for value in runner.tactical_finish
        )
        return TacticalEvidence(finish_times=finish_times)


def build_mumu12_facility_workflows(
    config: AzurLaneConfig,
    device: Device,
    *,
    clock: FacilityClock | None = None,
) -> FacilityWorkflows:
    """构造科研、委托和战术教室的 production workflow bundle。"""

    selected_clock = SystemFacilityClock() if clock is None else clock
    return FacilityWorkflows(
        research=LiveResearchWorkflow(Mumu12ResearchDriver(config, device, selected_clock), selected_clock),
        commission=LiveCommissionWorkflow(Mumu12CommissionDriver(config, device), selected_clock),
        tactical=LiveTacticalWorkflow(Mumu12TacticalDriver(config, device, selected_clock), selected_clock),
    )
