import re
from pathlib import Path
from typing import TYPE_CHECKING, override

import pytest

from module.content import ActivityCatalog, ContentId, RaidDefinition, RaidMode, RaidProfileId
from module.content.activity_catalog import RaidActivity
from module.content.errors import ContentValidationError
from module.content.manifest import load_event_manifests
from module.ocr.ocr import Digit, DigitCounter
from module.raid import assets as raid_assets
from module.raid.ocr import HuanChangPointOcr, HuanChangRemainCounter, PaddedRaidCounter
from module.raid.profile import (
    CHANGWU_RAID_PROFILE,
    HUANCHANG_RAID_PROFILE,
    RAID_CLIENT_PROFILES,
    RPG_RAID_PROFILE,
    CounterOcrSpec,
    DigitOcrSpec,
    RaidAttemptSource,
    RaidNavigationStrategy,
    ResolvedRaidProfile,
    UnknownRaidProfileError,
)
from module.raid.raid import Raid
from module.raid.result import RaidExecutionResult
from module.raid.run import RaidRun
from module.ui.page import Page, page_raid, page_rpg_stage

if TYPE_CHECKING:
    from module.combat.combat import CombatEnd
    from module.raid.profile import RaidRunPlan


def _raid_activities() -> tuple[RaidActivity, ...]:
    catalog = ActivityCatalog(load_event_manifests(Path("content/events")))
    raid_ids = sorted(
        str(pack.pack_id)
        for pack in load_event_manifests(Path("content/events"))
        if isinstance(pack.activity, RaidDefinition)
    )
    return tuple(catalog.resolve_raid(raid_id) for raid_id in raid_ids)


def _activity(profile_id: str, *, daily_modes: tuple[RaidMode, ...] = ()) -> RaidActivity:
    modes = (RaidMode.EASY, RaidMode.NORMAL, RaidMode.HARD, RaidMode.EX)
    return RaidActivity(
        ContentId(f"test_{profile_id}"),
        RaidDefinition(
            profile_id=RaidProfileId(profile_id),
            modes=modes,
            daily_modes=daily_modes,
            ticket_modes=(),
        ),
    )


def test_builtin_profiles_cover_every_raid_manifest_and_validate_before_runtime() -> None:
    activities = _raid_activities()

    assert len(activities) == 11
    assert {activity.definition.profile_id for activity in activities} == RAID_CLIENT_PROFILES.profile_ids
    for activity in activities:
        resolved = RAID_CLIENT_PROFILES.bind(activity)
        assert resolved.activity is activity
        assert {mode.mode for mode in resolved.client.modes} == set(activity.definition.modes)


def test_unknown_profile_fails_during_binding() -> None:
    with pytest.raises(UnknownRaidProfileError, match="unknown raid client profile"):
        RAID_CLIENT_PROFILES.bind(_activity("unknown"))


def test_rpg_attempts_are_explicitly_unmetered_without_fabricated_ocr() -> None:
    activity = next(
        activity for activity in _raid_activities() if activity.definition.profile_id == RaidProfileId("rpg")
    )
    resolved = RAID_CLIENT_PROFILES.bind(activity)

    assert resolved.client is RPG_RAID_PROFILE
    assert resolved.client.navigation is RaidNavigationStrategy.RPG_CAROUSEL
    assert resolved.client.landing_page is page_rpg_stage
    assert all(mode.attempt_source is RaidAttemptSource.UNMETERED for mode in resolved.client.modes)
    assert all(mode.remain_ocr is None for mode in resolved.client.modes)


def test_daily_or_ticket_capability_requires_metered_ocr() -> None:
    with pytest.raises(ContentValidationError, match="daily/ticket modes must have remain OCR"):
        ResolvedRaidProfile(
            activity=_activity("rpg", daily_modes=(RaidMode.EASY,)),
            client=RPG_RAID_PROFILE,
        )


def test_ticket_can_only_be_enabled_for_the_selected_ticket_mode() -> None:
    activity = next(
        activity for activity in _raid_activities() if activity.definition.profile_id == RaidProfileId("changwu")
    )
    resolved = RAID_CLIENT_PROFILES.bind(activity)

    with pytest.raises(ContentValidationError, match="tickets are not supported"):
        resolved.plan(RaidMode.HARD, use_ticket=True)
    assert resolved.plan(RaidMode.EX, use_ticket=True).use_ticket is True


def test_daily_plan_requires_manifest_daily_capability() -> None:
    rpg = next(activity for activity in _raid_activities() if activity.definition.profile_id == RaidProfileId("rpg"))

    with pytest.raises(ContentValidationError, match="is not daily content"):
        RAID_CLIENT_PROFILES.bind(rpg).daily_plan(RaidMode.HARD)


def test_profiles_bind_entrance_and_ocr_without_dynamic_asset_lookup() -> None:
    hard = CHANGWU_RAID_PROFILE.mode(RaidMode.HARD)
    ex = CHANGWU_RAID_PROFILE.mode(RaidMode.EX)

    assert hard is not None
    assert hard.entrance is raid_assets.CHANGWU_RAID_HARD
    assert isinstance(hard.remain_ocr, CounterOcrSpec)
    assert isinstance(hard.remain_ocr.create(), DigitCounter)
    assert ex is not None
    assert ex.entrance is raid_assets.CHANGWU_RAID_EX
    assert isinstance(ex.remain_ocr, DigitOcrSpec)
    assert isinstance(ex.remain_ocr.create(), Digit)


def test_special_ocr_strategies_are_bound_to_only_their_profiles() -> None:
    huanchang_hard = HUANCHANG_RAID_PROFILE.mode(RaidMode.HARD)

    assert huanchang_hard is not None
    assert isinstance(huanchang_hard.remain_ocr, CounterOcrSpec)
    assert huanchang_hard.remain_ocr.counter_type is HuanChangRemainCounter
    assert huanchang_hard.remain_ocr.alphabet == "0123456789IDSB"
    assert HuanChangRemainCounter(raid_assets.HUANCHANG_OCR_REMAIN_HARD).after_process("9") == (9, 0, 15)
    assert HUANCHANG_RAID_PROFILE.point_ocr is not None
    assert HUANCHANG_RAID_PROFILE.point_ocr.counter_type is HuanChangPointOcr

    essex = RAID_CLIENT_PROFILES.resolve(RaidProfileId("essex"))
    essex_easy = essex.mode(RaidMode.EASY)
    assert essex_easy is not None
    assert isinstance(essex_easy.remain_ocr, CounterOcrSpec)
    assert essex_easy.remain_ocr.counter_type is PaddedRaidCounter


class _NoIoRaidRun(RaidRun):
    def __init__(self, profile: ResolvedRaidProfile) -> None:
        self._raid_profile = profile
        self._active_plan = None


def test_unmetered_attempt_status_does_not_touch_device() -> None:
    activity = next(
        activity for activity in _raid_activities() if activity.definition.profile_id == RaidProfileId("rpg")
    )
    profile = RAID_CLIENT_PROFILES.bind(activity)
    runner = _NoIoRaidRun(profile)

    status = runner.get_attempt_status(profile.plan(RaidMode.EX))

    assert status.source is RaidAttemptSource.UNMETERED
    assert status.remaining is None
    assert status.exhausted is False


class _LandingRaid(Raid):
    def __init__(self, profile: ResolvedRaidProfile) -> None:
        self._raid_profile = profile
        self._active_plan = None
        self.pages: list[Page] = []
        self.carousel_seeks = 0

    @override
    def ui_ensure(self, destination: Page, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.pages.append(destination)
        return True

    @override
    def _seek_carousel_end(self, *, skip_first_screenshot: bool = True) -> None:
        del skip_first_screenshot
        self.carousel_seeks += 1


def test_navigation_strategy_is_profile_driven() -> None:
    activities = _raid_activities()
    standard = next(activity for activity in activities if activity.definition.profile_id == RaidProfileId("changwu"))
    rpg = next(activity for activity in activities if activity.definition.profile_id == RaidProfileId("rpg"))

    standard_runner = _LandingRaid(RAID_CLIENT_PROFILES.bind(standard))
    standard_runner.ensure_landing()
    assert standard_runner.pages == [page_raid]
    assert standard_runner.carousel_seeks == 0

    rpg_runner = _LandingRaid(RAID_CLIENT_PROFILES.bind(rpg))
    rpg_runner.ensure_landing()
    assert rpg_runner.pages == [page_rpg_stage]
    assert rpg_runner.carousel_seeks == 1


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


def test_atomic_ex_execution_returns_fact_and_restores_submarine_overlay() -> None:
    activity = next(
        activity for activity in _raid_activities() if activity.definition.profile_id == RaidProfileId("changwu")
    )
    profile = RAID_CLIENT_PROFILES.bind(activity)
    plan = profile.plan(RaidMode.EX, use_ticket=True)
    runner = _ExecutionRaid(profile)

    result = runner.execute_once(plan)

    assert result == RaidExecutionResult(mode=RaidMode.EX, runs_completed=1)
    assert runner.entered == [plan]
    assert runner.combat_calls == 1
    assert runner.emotion.checks == [1]
    assert runner.config.Submarine_Fleet == 3
    assert runner.config.Submarine_Mode == "boss_only"
    assert runner.config.overlays[-1] == {"Submarine_Fleet": 3, "Submarine_Mode": "boss_only"}


@pytest.mark.parametrize("filename", ["profile.py", "raid.py", "run.py", "result.py"])
def test_raid_domain_has_no_dated_dispatch_or_scheduler_mutation(filename: str) -> None:
    source = (Path("module/raid") / filename).read_text(encoding="utf-8")

    assert re.search(r"raid_[0-9]{8}", source) is None
    for forbidden in (
        "task_delay(",
        "task_stop(",
        "cross_set(",
        "Scheduler_Enable",
        "Campaign_Event",
        "RAID_NAME_PREFIX",
        "getattr(",
        "is_raid_rpg",
    ):
        assert forbidden not in source
