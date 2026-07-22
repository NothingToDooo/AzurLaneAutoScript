import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from module.bootstrap.configuration_compiler import ConfigurationCompileError, WebConfigurationCompiler
from module.bootstrap.configured_campaign_content import validate_configured_campaign_content
from module.content.campaign_session import CampaignRunVariant, CampaignSession
from module.content.campaign_session_source import CompiledCampaignSessionSource
from module.content.errors import UnknownStageError
from module.content.models import StageRef
from module.gameplay.campaign import CAMPAIGN_JOB_KINDS, CampaignJobSettings
from module.runtime import CompiledTaskSettings

if TYPE_CHECKING:
    from module.gameplay.encounter import HardSettings


def _template() -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads(Path("config/template.json").read_text(encoding="utf-8")),
    )


@dataclass(frozen=True, slots=True)
class _Definition:
    ref: StageRef


@dataclass(frozen=True, slots=True)
class _Session:
    definition: _Definition


class _Sessions(CompiledCampaignSessionSource):
    def __init__(self) -> None:
        self.candidates: dict[StageRef, tuple[StageRef, ...]] = {}
        self.validated: list[StageRef] = []
        self.resolved: list[tuple[StageRef, CampaignRunVariant]] = []
        self.hard_ref = StageRef("campaign_main", "11-4")
        self.rejected_ref: StageRef | None = None

    def validate_candidates(self, ref: StageRef) -> tuple[StageRef, ...]:
        self.validated.append(ref)
        if ref == self.rejected_ref:
            message = f"unknown stage: {ref.pack_id}/{ref.stage_id}"
            raise UnknownStageError(message)
        return self.candidates.get(ref, (ref,))

    def resolve_hard_stage_ref(self, stage_id: str) -> StageRef:
        if stage_id == "missing-hard-stage":
            message = f"unknown hard stage: {stage_id}"
            raise UnknownStageError(message)
        return self.hard_ref

    def resolve(self, ref: StageRef, variant: CampaignRunVariant) -> CampaignSession:
        self.resolved.append((ref, variant))
        if ref == self.rejected_ref:
            message = f"unknown stage: {ref.pack_id}/{ref.stage_id}"
            raise UnknownStageError(message)
        return cast("CampaignSession", _Session(_Definition(ref)))


def _compiled() -> dict[str, CompiledTaskSettings]:
    return dict(WebConfigurationCompiler().compile(_template()).tasks)


def test_configured_campaign_content_validates_every_job_gems_fallback_and_hard() -> None:
    tasks = _compiled()
    sessions = _Sessions()

    validate_configured_campaign_content(tasks, sessions)

    expected_requests = [
        ref
        for task_id in CAMPAIGN_JOB_KINDS
        for ref in cast("CampaignJobSettings", tasks[task_id.value].settings).stage_refs
    ]
    gems = cast("CampaignJobSettings", tasks["gems_farming"].settings).gems_farming
    assert gems is not None
    assert sessions.validated == expected_requests
    assert (gems.fallback_ref, CampaignRunVariant.NORMAL) in sessions.resolved
    assert (sessions.hard_ref, CampaignRunVariant.LOOP) in sessions.resolved


def test_configured_campaign_content_rejects_duplicate_canonical_stages() -> None:
    tasks = _compiled()
    event_a = cast("CampaignJobSettings", tasks["event_a"].settings)
    first = StageRef("campaign_main", "first-alias")
    second = StageRef("campaign_main", "second-alias")
    canonical = StageRef("campaign_main", "12-4")
    tasks["event_a"] = CompiledTaskSettings(
        replace(event_a, stage_refs=(first, second)),
        tasks["event_a"].revision,
    )
    sessions = _Sessions()
    sessions.candidates = {first: (canonical,), second: (canonical,)}

    with pytest.raises(
        ConfigurationCompileError,
        match=r"\$\.tasks\.event_a\.stage_refs must not resolve to duplicate canonical stages",
    ):
        validate_configured_campaign_content(tasks, sessions)


def test_configured_campaign_content_reports_campaign_reference_path() -> None:
    tasks = _compiled()
    main = cast("CampaignJobSettings", tasks["main"].settings)
    sessions = _Sessions()
    sessions.rejected_ref = main.stage_refs[0]

    with pytest.raises(ConfigurationCompileError, match=r"\$\.tasks\.main\.stage_refs.*unknown stage"):
        validate_configured_campaign_content(tasks, sessions)


def test_configured_campaign_content_reports_gems_fallback_path() -> None:
    tasks = _compiled()
    gems = cast("CampaignJobSettings", tasks["gems_farming"].settings)
    assert gems.gems_farming is not None
    sessions = _Sessions()
    sessions.rejected_ref = gems.gems_farming.fallback_ref

    with pytest.raises(
        ConfigurationCompileError,
        match=r"\$\.tasks\.gems_farming\.gems_farming\.fallback_ref.*unknown stage",
    ):
        validate_configured_campaign_content(tasks, sessions)


def test_configured_campaign_content_rejects_non_main_fallback_equal_to_primary() -> None:
    tasks = _compiled()
    gems = cast("CampaignJobSettings", tasks["gems_farming"].settings)
    assert gems.gems_farming is not None
    primary = StageRef("event_20260625_cn", "d3")
    tasks["gems_farming"] = CompiledTaskSettings(
        replace(
            gems,
            stage_refs=(primary,),
            gems_farming=replace(gems.gems_farming, fallback_ref=primary),
        ),
        tasks["gems_farming"].revision,
    )

    with pytest.raises(
        ConfigurationCompileError,
        match=r"\$\.tasks\.gems_farming\.gems_farming\.fallback_ref must differ",
    ):
        validate_configured_campaign_content(tasks, _Sessions())


def test_configured_campaign_content_allows_main_fallback_equal_to_primary() -> None:
    tasks = _compiled()
    gems = cast("CampaignJobSettings", tasks["gems_farming"].settings)
    assert gems.gems_farming is not None
    fallback = gems.gems_farming.fallback_ref
    tasks["gems_farming"] = CompiledTaskSettings(
        replace(gems, stage_refs=(fallback,)),
        tasks["gems_farming"].revision,
    )

    validate_configured_campaign_content(tasks, _Sessions())


def test_configured_campaign_content_reports_hard_stage_path() -> None:
    tasks = _compiled()
    hard = cast("HardSettings", tasks["hard"].settings)
    tasks["hard"] = CompiledTaskSettings(
        replace(hard, stage="missing-hard-stage"),
        tasks["hard"].revision,
    )

    with pytest.raises(ConfigurationCompileError, match=r"\$\.tasks\.hard\.stage.*missing-hard-stage"):
        validate_configured_campaign_content(tasks, _Sessions())


def test_configured_campaign_content_rejects_wrong_settings_type() -> None:
    tasks = _compiled()
    tasks["main"] = CompiledTaskSettings(object(), tasks["main"].revision)

    with pytest.raises(TypeError, match=r"\$\.tasks\.main settings must be CampaignJobSettings"):
        validate_configured_campaign_content(tasks, _Sessions())
