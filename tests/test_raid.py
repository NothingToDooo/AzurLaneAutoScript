from typing import TYPE_CHECKING, override

import pytest

from module.content.activity_catalog import ActivityCatalog, RaidActivity
from module.content.activity_profile import RaidDefinition, RaidMode, RaidProfileId
from module.content.manifest import load_default_event_manifests
from module.content.models import ContentId
from module.raid.profile import (
    HUANCHANG_RAID_PROFILE,
    RAID_CLIENT_PROFILES,
    RPG_RAID_PROFILE,
    RaidAttemptSource,
    ResolvedRaidProfile,
    UnknownRaidProfileError,
)
from module.raid.raid import Raid
from module.raid.result import RaidExecutionResult
from module.raid.run import RaidRun

if TYPE_CHECKING:
    from module.combat.combat import CombatEnd
    from module.raid.profile import RaidRunPlan


@pytest.fixture(scope="module")
def raid_activities() -> tuple[RaidActivity, ...]:
    manifests = load_default_event_manifests()
    catalog = ActivityCatalog(manifests)
    raid_ids = sorted(str(pack.pack_id) for pack in manifests if isinstance(pack.activity, RaidDefinition))
    return tuple(catalog.resolve_raid(raid_id) for raid_id in raid_ids)


def _activity(profile_id: str) -> RaidActivity:
    modes = (RaidMode.EASY, RaidMode.NORMAL, RaidMode.HARD, RaidMode.EX)
    return RaidActivity(
        ContentId(f"test_{profile_id}"),
        RaidDefinition(
            profile_id=RaidProfileId(profile_id),
            modes=modes,
            daily_modes=(),
            ticket_modes=(),
        ),
    )


def test_builtin_profiles_cover_every_real_raid_manifest(
    raid_activities: tuple[RaidActivity, ...],
) -> None:
    assert {activity.definition.profile_id for activity in raid_activities} == RAID_CLIENT_PROFILES.profile_ids
    for activity in raid_activities:
        resolved = RAID_CLIENT_PROFILES.bind(activity)
        assert resolved.activity is activity
        assert {mode.mode for mode in resolved.client.modes} == set(activity.definition.modes)


def test_unknown_profile_fails_during_binding() -> None:
    with pytest.raises(UnknownRaidProfileError, match="unknown raid client profile"):
        RAID_CLIENT_PROFILES.bind(_activity("unknown"))


def test_rpg_attempts_are_explicitly_unmetered(
    raid_activities: tuple[RaidActivity, ...],
) -> None:
    activity = next(activity for activity in raid_activities if activity.definition.profile_id == RaidProfileId("rpg"))
    resolved = RAID_CLIENT_PROFILES.bind(activity)

    assert resolved.client is RPG_RAID_PROFILE
    assert all(mode.attempt_source is RaidAttemptSource.UNMETERED for mode in resolved.client.modes)
    assert all(mode.remain_ocr is None for mode in resolved.client.modes)


def test_special_raid_counter_ocr_preserves_profile_correction() -> None:
    mode = HUANCHANG_RAID_PROFILE.mode(RaidMode.HARD)

    assert mode is not None
    assert mode.remain_ocr is not None
    assert mode.remain_ocr.create().after_process("9") == (9, 0, 15)


class _NoIoRaidRun(RaidRun):
    def __init__(self, profile: ResolvedRaidProfile) -> None:
        self._raid_profile = profile
        self._active_plan = None


def test_unmetered_attempt_status_does_not_touch_device(
    raid_activities: tuple[RaidActivity, ...],
) -> None:
    activity = next(activity for activity in raid_activities if activity.definition.profile_id == RaidProfileId("rpg"))
    profile = RAID_CLIENT_PROFILES.bind(activity)
    runner = _NoIoRaidRun(profile)

    status = runner.get_attempt_status(profile.plan(RaidMode.EX))

    assert status.source is RaidAttemptSource.UNMETERED
    assert status.remaining is None
    assert status.exhausted is False


class _Config:
    def __init__(self) -> None:
        self.Submarine_Fleet = 3
        self.Submarine_Mode = "boss_only"
        self.overlays: list[dict[str, object]] = []

    def apply_runtime_overlay(self, **values: object) -> None:
        self.overlays.append(values)
        for key, value in values.items():
            setattr(self, key, value)


class _Emotion:
    def __init__(self) -> None:
        self.checks: list[int] = []

    def check_reduce(self, fleet_index: int) -> None:
        self.checks.append(fleet_index)


class _ExecutionRaid(Raid):
    config: _Config

    def __init__(self, profile: ResolvedRaidProfile) -> None:
        self._raid_profile = profile
        self._active_plan = None
        self.config = _Config()
        self._emotion = _Emotion()
        self.entered: list[RaidRunPlan] = []
        self.combat_calls = 0

    @property
    def emotion(self) -> _Emotion:
        return self._emotion

    @override
    def raid_enter(self, plan: RaidRunPlan, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        assert self._active_plan is plan
        self.entered.append(plan)

    @override
    def combat(
        self,
        *,
        balance_hp: bool | None = None,
        emotion_reduce: bool | None = None,
        submarine_mode: str | None = None,
        expected_end: CombatEnd | None = None,
        fleet_index: int = 1,
    ) -> None:
        del balance_hp, emotion_reduce, submarine_mode, expected_end, fleet_index
        assert self._active_plan is not None
        self.combat_calls += 1


def test_atomic_ex_execution_returns_fact_and_restores_submarine_overlay(
    raid_activities: tuple[RaidActivity, ...],
) -> None:
    activity = next(
        activity for activity in raid_activities if activity.definition.profile_id == RaidProfileId("changwu")
    )
    profile = RAID_CLIENT_PROFILES.bind(activity)
    plan = profile.plan(RaidMode.EX, use_ticket=True)
    runner = _ExecutionRaid(profile)

    result = runner.execute_once(plan)

    assert result == RaidExecutionResult(mode=RaidMode.EX, runs_completed=1)
    assert runner.entered == [plan]
    assert runner.combat_calls == 1
    assert runner.emotion.checks == []
    assert runner.config.Submarine_Fleet == 3
    assert runner.config.Submarine_Mode == "boss_only"
    assert runner.config.overlays[-1] == {"Submarine_Fleet": 3, "Submarine_Mode": "boss_only"}
