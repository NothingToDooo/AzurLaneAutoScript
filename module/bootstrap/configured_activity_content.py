from collections.abc import Callable, Mapping

from module.bootstrap.configuration_compiler import ConfigurationCompileError
from module.content.activity_catalog import ActivityCatalog
from module.content.errors import ContentValidationError
from module.gameplay.activity import (
    CoalitionOptions,
    CoalitionSettings,
    CoalitionSpSettings,
    EventStorySettings,
    RaidDailyOptions,
    RaidDailySettings,
    RaidOptions,
    RaidSettings,
)
from module.runtime import CompiledTaskSettings


def _configured_settings[SettingsT](
    tasks: Mapping[str, CompiledTaskSettings],
    task_id: str,
    expected_type: type[SettingsT],
) -> SettingsT | None:
    compiled = tasks.get(task_id)
    if compiled is None:
        return None
    if not isinstance(compiled, CompiledTaskSettings):
        message = f"$.tasks.{task_id} must be CompiledTaskSettings"
        raise TypeError(message)
    if not isinstance(compiled.settings, expected_type):
        message = f"$.tasks.{task_id} settings must be {expected_type.__name__}"
        raise TypeError(message)
    return compiled.settings


def _validate_at_path(task_id: str, validation: Callable[[], object]) -> None:
    try:
        validation()
    except (ContentValidationError, LookupError, ValueError) as error:
        message = f"$.tasks.{task_id} {error}"
        raise ConfigurationCompileError(message) from error


def _validate_raid_daily(settings: RaidDailySettings, catalog: ActivityCatalog) -> None:
    activity = catalog.resolve_raid(settings.content_id.value)
    if not activity.definition.supports_daily:
        message = "selected raid content has no daily modes"
        raise ContentValidationError(message)
    RaidDailyOptions(
        activity=activity,
        stages=settings.stages,
        use_ticket=settings.use_ticket,
        collect_daily_mission=settings.collect_daily_mission,
        policy=settings.policy,
    )


def _validate_raid(settings: RaidSettings, catalog: ActivityCatalog) -> None:
    activity = catalog.resolve_raid(settings.content_id.value)
    RaidOptions(
        activity=activity,
        mode=settings.mode,
        use_ticket=settings.use_ticket,
        policy=settings.policy,
    )
    if settings.use_ticket and settings.mode not in activity.definition.ticket_modes:
        message = f"tickets are not supported in raid mode {settings.mode.value!r}"
        raise ContentValidationError(message)


def _validate_coalition(
    settings: CoalitionSettings | CoalitionSpSettings,
    catalog: ActivityCatalog,
) -> None:
    CoalitionOptions(
        activity=catalog.resolve_coalition(settings.content_id.value),
        stage=settings.stage,
        fleet=settings.fleet,
        policy=settings.policy,
    )


def validate_configured_activity_content(
    tasks: Mapping[str, CompiledTaskSettings],
    catalog: ActivityCatalog,
) -> None:
    """只用 typed settings 和内容目录验证活动引用，不装配任何运行时对象。"""

    if not isinstance(tasks, Mapping):
        message = "tasks must be a mapping"
        raise TypeError(message)
    if not isinstance(catalog, ActivityCatalog):
        message = "catalog must be an ActivityCatalog"
        raise TypeError(message)

    event_story = _configured_settings(tasks, "event_story", EventStorySettings)
    if event_story is not None:
        _validate_at_path(
            "event_story",
            lambda: catalog.resolve_event_story(event_story.content_id.value),
        )

    raid_daily = _configured_settings(tasks, "raid_daily", RaidDailySettings)
    if raid_daily is not None:
        _validate_at_path("raid_daily", lambda: _validate_raid_daily(raid_daily, catalog))

    raid = _configured_settings(tasks, "raid", RaidSettings)
    if raid is not None:
        _validate_at_path("raid", lambda: _validate_raid(raid, catalog))

    coalition = _configured_settings(tasks, "coalition", CoalitionSettings)
    if coalition is not None:
        _validate_at_path("coalition", lambda: _validate_coalition(coalition, catalog))

    coalition_sp = _configured_settings(tasks, "coalition_sp", CoalitionSpSettings)
    if coalition_sp is not None:
        _validate_at_path("coalition_sp", lambda: _validate_coalition(coalition_sp, catalog))
