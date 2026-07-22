from dataclasses import replace
from datetime import time, timedelta

import pytest

from module.application import DailySchedule, DelayRange, TaskId
from module.bootstrap.configuration_compiler import ConfigurationCompileError
from module.bootstrap.configured_activity_content import validate_configured_activity_content
from module.content.activity_catalog import ActivityCatalog
from module.content.activity_profile import CoalitionFleetMode, CoalitionStageId, RaidMode
from module.content.manifest import load_default_event_manifests
from module.content.models import ContentId
from module.gameplay.activity import (
    CoalitionSettings,
    CoalitionSpSettings,
    EncounterBalancerPolicy,
    EncounterPolicy,
    EventStorySettings,
    RaidDailySettings,
    RaidSettings,
)
from module.runtime import CompiledTaskSettings

_CATALOG = ActivityCatalog(load_default_event_manifests())
_SCHEDULE = DailySchedule("Asia/Hong_Kong", (time(8),))
_POLICY = EncounterPolicy(
    failure_retry_delay=DelayRange(300, 300),
    resource_retry_delay=timedelta(hours=2),
    oil_limit=1_000,
)
_BALANCER = EncounterBalancerPolicy(TaskId("main"), coin_limit=10_000)


def _compiled(**settings: object) -> dict[str, CompiledTaskSettings]:
    return {
        task_id: CompiledTaskSettings(value, revision=index)
        for index, (task_id, value) in enumerate(settings.items(), start=1)
    }


def _raid_settings(**changes: object) -> RaidSettings:
    settings = RaidSettings(
        content_id=ContentId("raid_20260212"),
        mode=RaidMode.HARD,
        use_ticket=False,
        policy=_POLICY,
        run_limit=None,
        balancer=_BALANCER,
    )
    return replace(settings, **changes)


def _coalition_settings(**changes: object) -> CoalitionSettings:
    settings = CoalitionSettings(
        content_id=ContentId("coalition_20260122"),
        stage=CoalitionStageId("hard"),
        fleet=CoalitionFleetMode.SINGLE,
        policy=_POLICY,
        run_limit=None,
        balancer=_BALANCER,
    )
    return replace(settings, **changes)


def test_configured_activity_content_accepts_all_typed_content_references() -> None:
    validate_configured_activity_content(
        _compiled(
            event_story=EventStorySettings(ContentId("event_20260625_cn"), skip_battle=True),
            raid_daily=RaidDailySettings(
                content_id=ContentId("raid_20260212"),
                stages=(RaidMode.HARD, RaidMode.NORMAL),
                use_ticket=False,
                collect_daily_mission=True,
                policy=_POLICY,
                schedule=_SCHEDULE,
            ),
            raid=_raid_settings(),
            coalition=_coalition_settings(),
            coalition_sp=CoalitionSpSettings(
                content_id=ContentId("coalition_20260122"),
                stage=CoalitionStageId("sp"),
                fleet=CoalitionFleetMode.MULTI,
                policy=_POLICY,
                schedule=_SCHEDULE,
            ),
        ),
        _CATALOG,
    )


def test_configured_activity_content_ignores_tasks_without_content_references() -> None:
    validate_configured_activity_content(
        _compiled(hospital=object(), maritime_escort=object()),
        _CATALOG,
    )


@pytest.mark.parametrize(
    ("task_id", "settings", "message"),
    [
        (
            "event_story",
            EventStorySettings(ContentId("raid_20260212"), skip_battle=True),
            "expected event_story",
        ),
        (
            "raid_daily",
            RaidDailySettings(
                content_id=ContentId("raid_20210708"),
                stages=(RaidMode.EX,),
                use_ticket=False,
                collect_daily_mission=True,
                policy=_POLICY,
                schedule=_SCHEDULE,
            ),
            "stages must be supported daily modes",
        ),
        (
            "raid_daily",
            RaidDailySettings(
                content_id=ContentId("raid_20240328"),
                stages=(RaidMode.EX,),
                use_ticket=False,
                collect_daily_mission=True,
                policy=_POLICY,
                schedule=_SCHEDULE,
            ),
            "selected raid content has no daily modes",
        ),
        (
            "raid",
            _raid_settings(content_id=ContentId("raid_20210708"), mode=RaidMode.EX),
            "mode must be supported",
        ),
        (
            "raid",
            _raid_settings(
                content_id=ContentId("raid_20210708"),
                mode=RaidMode.HARD,
                use_ticket=True,
            ),
            "tickets are not supported",
        ),
        (
            "coalition",
            _coalition_settings(stage=CoalitionStageId("missing")),
            "stage must belong",
        ),
        (
            "coalition",
            _coalition_settings(
                stage=CoalitionStageId("easy"),
                fleet=CoalitionFleetMode.MULTI,
            ),
            "fleet must satisfy",
        ),
        (
            "coalition_sp",
            CoalitionSpSettings(
                content_id=ContentId("raid_20260212"),
                stage=CoalitionStageId("sp"),
                fleet=CoalitionFleetMode.MULTI,
                policy=_POLICY,
                schedule=_SCHEDULE,
            ),
            "expected coalition",
        ),
    ],
)
def test_configured_activity_content_reports_task_path(
    task_id: str,
    settings: object,
    message: str,
) -> None:
    with pytest.raises(ConfigurationCompileError, match=rf"\$\.tasks\.{task_id}.*{message}"):
        validate_configured_activity_content(_compiled(**{task_id: settings}), _CATALOG)


def test_configured_activity_content_rejects_wrong_compiled_settings_type() -> None:
    with pytest.raises(TypeError, match=r"\$\.tasks\.event_story settings must be EventStorySettings"):
        validate_configured_activity_content(_compiled(event_story=object()), _CATALOG)
