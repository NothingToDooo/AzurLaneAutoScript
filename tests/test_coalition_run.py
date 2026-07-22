from typing import override

import pytest

from module.coalition.coalition import Coalition, CoalitionExecutionResult
from module.coalition.profile import COALITION_CLIENT_PROFILES, CoalitionClientSession
from module.content.activity_catalog import ActivityCatalog
from module.content.activity_profile import CoalitionFleetMode, CoalitionStageId
from module.content.manifest import load_default_event_manifests


def _session(content_id: str, stage_id: str, fleet: CoalitionFleetMode) -> CoalitionClientSession:
    catalog = ActivityCatalog(load_default_event_manifests())
    return COALITION_CLIENT_PROFILES.resolve(
        catalog.resolve_coalition(content_id),
        CoalitionStageId(stage_id),
        fleet,
    )


class _Config:
    def __init__(self, emotion_control: str = "ignore") -> None:
        self.Emotion_Fleet1Control = emotion_control
        self.overlays: list[dict[str, object]] = []

    def apply_runtime_overlay(self, **values: object) -> None:
        self.overlays.append(values)
        for name, value in values.items():
            setattr(self, name, value)


class _Coalition(Coalition):
    config: _Config

    def __init__(self, client: CoalitionClientSession, *, emotion_control: str = "ignore") -> None:
        self.client = client
        self.config = _Config(emotion_control)
        self.calls: list[str] = []

    @override
    def enter_coalition_map(self) -> None:
        self.calls.append("enter_coalition_map")

    @override
    def coalition_combat(self) -> None:
        self.calls.append("coalition_combat")


def test_execute_once_uses_typed_session_and_returns_content_result() -> None:
    session = _session("coalition_20230323", "tc3", CoalitionFleetMode.MULTI)
    coalition = _Coalition(session)

    result = coalition.coalition_execute_once()

    assert result == CoalitionExecutionResult(session.activity.content_id, CoalitionStageId("tc3"), 3)
    assert coalition.calls == ["enter_coalition_map", "coalition_combat"]
    assert coalition.config.overlays == [
        {
            "Campaign_Name": "coalition_20230323_tc3",
            "Campaign_UseAutoSearch": False,
            "Coalition_Fleet": "multi",
            "Fleet_FleetOrder": "fleet1_all_fleet2_standby",
        }
    ]


def test_single_fleet_execution_applies_only_the_runtime_emotion_guard() -> None:
    session = _session("coalition_20260122", "hard", CoalitionFleetMode.SINGLE)
    coalition = _Coalition(session, emotion_control="prevent_red_face")

    coalition.coalition_execute_once()

    assert coalition.config.overlays[-1] == {"Emotion_Fleet1Control": "prevent_yellow_face"}
    assert coalition.config.Emotion_Fleet1Control == "prevent_yellow_face"


def test_execution_result_rejects_non_positive_battle_count() -> None:
    session = _session("coalition_20230323", "tc1", CoalitionFleetMode.SINGLE)

    with pytest.raises(ValueError, match="battle_count must be a positive integer"):
        CoalitionExecutionResult(session.activity.content_id, session.stage.stage_id, 0)
