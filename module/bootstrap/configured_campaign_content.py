from collections.abc import Mapping
from typing import TYPE_CHECKING

from module.bootstrap.configuration_compiler import ConfigurationCompileError
from module.content.campaign_session import CampaignRunVariant
from module.content.campaign_session_source import CompiledCampaignSessionSource
from module.content.errors import ContentValidationError
from module.gameplay.campaign import CAMPAIGN_JOB_KINDS, CampaignJobSettings
from module.gameplay.encounter import HardSettings
from module.runtime import CompiledTaskSettings

if TYPE_CHECKING:
    from module.content.models import StageRef


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


def _content_error(task_id: str, field: str, error: Exception) -> ConfigurationCompileError:
    return ConfigurationCompileError(f"$.tasks.{task_id}.{field} {error}")


def _validate_job(
    task_id: str,
    settings: CampaignJobSettings,
    sessions: CompiledCampaignSessionSource,
) -> None:
    primary_refs: list[StageRef] = []
    try:
        for ref in settings.stage_refs:
            primary_refs.extend(sessions.validate_candidates(ref))
    except (ContentValidationError, LookupError, ValueError) as error:
        raise _content_error(task_id, "stage_refs", error) from error

    if len(set(primary_refs)) != len(primary_refs):
        message = f"$.tasks.{task_id}.stage_refs must not resolve to duplicate canonical stages"
        raise ConfigurationCompileError(message)

    gems = settings.gems_farming
    if gems is None:
        return
    try:
        fallback = sessions.resolve(gems.fallback_ref, CampaignRunVariant.NORMAL)
    except (ContentValidationError, LookupError, ValueError) as error:
        raise _content_error(task_id, "gems_farming.fallback_ref", error) from error
    fallback_ref = fallback.definition.ref
    if fallback_ref in primary_refs and fallback_ref.pack_id != "campaign_main":
        message = f"$.tasks.{task_id}.gems_farming.fallback_ref must differ from the primary stage"
        raise ConfigurationCompileError(message)


def _validate_hard(
    settings: HardSettings,
    sessions: CompiledCampaignSessionSource,
) -> None:
    task_id = "hard"
    field = "stage"
    try:
        ref = sessions.resolve_hard_stage_ref(settings.stage)
        sessions.resolve(ref, CampaignRunVariant.LOOP)
    except (ContentValidationError, LookupError, ValueError) as error:
        raise _content_error(task_id, field, error) from error


def validate_configured_campaign_content(
    tasks: Mapping[str, CompiledTaskSettings],
    sessions: CompiledCampaignSessionSource,
) -> None:
    """确定性验证配置会触达的 Campaign 与困难图内容。"""

    if not isinstance(tasks, Mapping):
        message = "tasks must be a mapping"
        raise TypeError(message)
    if not isinstance(sessions, CompiledCampaignSessionSource):
        message = "sessions must be a CompiledCampaignSessionSource"
        raise TypeError(message)

    for task_id in CAMPAIGN_JOB_KINDS:
        command = task_id.value
        settings = _configured_settings(tasks, command, CampaignJobSettings)
        if settings is not None:
            _validate_job(command, settings, sessions)

    hard = _configured_settings(tasks, "hard", HardSettings)
    if hard is not None:
        _validate_hard(hard, sessions)
