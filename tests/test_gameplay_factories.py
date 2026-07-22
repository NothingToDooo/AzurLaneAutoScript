from datetime import UTC, datetime, time, timedelta
from typing import TYPE_CHECKING, cast

import pytest

from module.application import (
    AbortToken,
    DailySchedule,
    DelayRange,
    ExecutionMode,
    RunMetadata,
    TaskContext,
    TaskId,
)
from module.gameplay.composite import (
    DormFeedPlan,
    DormFurniturePlan,
    DormReport,
    DormRunRequest,
    DormSettings,
    FurnitureBuyOption,
)
from module.gameplay.composite_factories import CompositeWorkflows, build_composite_factories
from module.gameplay.encounter import (
    ExerciseOpponentMode,
    ExerciseProgress,
    ExerciseReport,
    ExerciseSettings,
    ExerciseStrategy,
)
from module.gameplay.encounter_factories import EncounterWorkflows, build_encounter_factories
from module.gameplay.market import (
    GachaPlan,
    GachaPool,
    GachaReport,
    GachaSettings,
)
from module.gameplay.market_factories import MarketWorkflows, build_market_factories
from module.runtime import TaskBuildContext, TaskFactory, TaskStateDocument
from module.task_registry import TASK_SPECS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.application import CancellationSource
    from module.gameplay.composite import (
        DataKeyWorkflow,
        DormWorkflow,
        FreebieCollectionWorkflow,
        GuildWorkflow,
        MailCollectionWorkflow,
        MeowfficerWorkflow,
        PrivateQuartersWorkflow,
        RewardWorkflow,
        SupplyPackWorkflow,
    )
    from module.gameplay.encounter import DailyWorkflow, ExerciseWorkflow, HardWorkflow
    from module.gameplay.market import (
        AwakenWorkflow,
        GachaWorkflow,
        ShipyardWorkflow,
        ShopFrequentWorkflow,
        ShopOnceWorkflow,
    )

_OBSERVED_AT = datetime(2026, 7, 15, 1, tzinfo=UTC)
_DAILY_SCHEDULE_VALUE = DailySchedule("Asia/Hong_Kong", (time(8),))
_SERVER_UPDATE_SCHEDULE_VALUE = DailySchedule("Asia/Hong_Kong", (time(12),))


class _RecordingPort[ReportT]:
    def __init__(self, report: ReportT) -> None:
        self._report = report
        self.received: list[tuple[object, ...]] = []

    def execute(self, *args: object) -> ReportT:
        cancellation = cast("CancellationSource", args[-1])
        cancellation.raise_if_requested()
        self.received.append(args[:-1])
        return self._report

    def collect(self, *args: object) -> ReportT:
        return self.execute(*args)


def _composite_factories(dorm: _RecordingPort[DormReport] | None = None) -> Mapping[str, TaskFactory]:
    port = _RecordingPort(object())
    workflows = CompositeWorkflows(
        dorm=cast("DormWorkflow", port if dorm is None else dorm),
        meowfficer=cast("MeowfficerWorkflow", port),
        guild=cast("GuildWorkflow", port),
        reward=cast("RewardWorkflow", port),
        battle_pass=cast("FreebieCollectionWorkflow", port),
        data_key=cast("DataKeyWorkflow", port),
        mail=cast("MailCollectionWorkflow", port),
        supply_pack=cast("SupplyPackWorkflow", port),
        private_quarters=cast("PrivateQuartersWorkflow", port),
    )
    return build_composite_factories(workflows)


def _market_factories(gacha: _RecordingPort[GachaReport] | None = None) -> Mapping[str, TaskFactory]:
    port = _RecordingPort(object())
    workflows = MarketWorkflows(
        awaken=cast("AwakenWorkflow", port),
        shipyard=cast("ShipyardWorkflow", port),
        gacha=cast("GachaWorkflow", port if gacha is None else gacha),
        shop_frequent=cast("ShopFrequentWorkflow", port),
        shop_once=cast("ShopOnceWorkflow", port),
    )
    return build_market_factories(workflows)


def _encounter_factories(exercise: _RecordingPort[ExerciseReport] | None = None) -> Mapping[str, TaskFactory]:
    port = _RecordingPort(object())
    workflows = EncounterWorkflows(
        daily=cast("DailyWorkflow", port),
        hard=cast("HardWorkflow", port),
        exercise=cast("ExerciseWorkflow", port if exercise is None else exercise),
    )
    return build_encounter_factories(workflows)


def _context(command: str, settings: object) -> TaskBuildContext:
    return TaskBuildContext(
        spec=TASK_SPECS[command],
        settings_revision=2,
        content_revision="content-1",
        settings=settings,
        task_state=TaskStateDocument.empty(command),
    )


def _task_context(command: str) -> TaskContext:
    return TaskContext(
        task_id=TaskId(command),
        started_at=_OBSERVED_AT,
        mode=ExecutionMode.SCHEDULED_JOB,
        metadata=RunMetadata(settings_revision=2, content_revision="content-1"),
        abort=AbortToken(),
    )


def test_composite_factory_passes_typed_dorm_request_to_workflow() -> None:
    workflow = _RecordingPort(DormReport(_OBSERVED_AT, ships_in_dorm=2, furniture_checked=True))
    settings = DormSettings(
        feed=DormFeedPlan("Oil < 12000"),
        collect_enabled=False,
        furniture=DormFurniturePlan(FurnitureBuyOption.ALL, timedelta(seconds=5_400)),
        fallback_delay=DelayRange(601, 899),
    )
    task = _composite_factories(workflow)["dorm"].build(_context("dorm", settings))

    task.run(_task_context("dorm"))

    assert workflow.received == [(DormRunRequest(settings, furniture_due=True),)]


def test_market_factory_passes_typed_gacha_settings_to_workflow() -> None:
    workflow = _RecordingPort(GachaReport(submitted=True))
    settings = GachaSettings(
        GachaPlan(GachaPool.EVENT, amount=8, use_ticket=False, use_drill=True),
        _DAILY_SCHEDULE_VALUE,
    )
    task = _market_factories(workflow)["gacha"].build(_context("gacha", settings))

    task.run(_task_context("gacha"))

    assert workflow.received == [(settings,)]


def test_encounter_factory_passes_typed_exercise_settings_and_progress_to_workflow() -> None:
    workflow = _RecordingPort(ExerciseReport(_OBSERVED_AT, 0, 0, 1, 3))
    settings = ExerciseSettings(
        schedule=_SERVER_UPDATE_SCHEDULE_VALUE,
        failure_retry_delay=DelayRange(401, 997),
        opponent_refresh_limit=9,
        opponent_mode=ExerciseOpponentMode.EASIEST_ELSE_EXP,
        opponent_trials=4,
        strategy=ExerciseStrategy.SUN_18,
        low_hp_threshold=0.27,
        low_hp_confirm_wait_seconds=1.75,
    )
    task = _encounter_factories(workflow)["exercise"].build(_context("exercise", settings))

    task.run(_task_context("exercise"))

    assert workflow.received == [
        (
            settings,
            ExerciseProgress(),
        )
    ]


def test_encounter_factories_reject_wrong_settings_type() -> None:
    with pytest.raises(TypeError, match="daily settings must be DailySettings"):
        _encounter_factories()["daily"].build(_context("daily", object()))


def test_market_factories_reject_wrong_settings_type() -> None:
    settings = GachaSettings(
        GachaPlan(GachaPool.EVENT, amount=8, use_ticket=False, use_drill=True),
        _DAILY_SCHEDULE_VALUE,
    )

    with pytest.raises(TypeError, match="awaken settings must be AwakenSettings"):
        _market_factories()["awaken"].build(_context("awaken", settings))
