import json
from datetime import timedelta
from pathlib import Path
from typing import cast

import pytest

from module.bootstrap.configuration_compiler import (
    CompiledConfiguration,
    CurrentConfigurationSchema,
    WebConfigurationCompiler,
)
from module.content.models import ContentId, StageRef
from module.gameplay.activity import CoalitionSpSettings, EventStorySettings
from module.gameplay.campaign import CampaignJobSettings
from module.gameplay.composite import FreebiesSettings, RewardSettings
from module.gameplay.encounter import DailySettings, ExerciseSettings, HardSettings
from module.gameplay.facility import CommissionSettings, ResearchSettings, TacticalSettings
from module.gameplay.market import ShopFrequentSettings, ShopOnceSettings
from module.gameplay.opsi import MeowfficerFarmingSettings
from module.maintenance.uncensored import UncensoredSettings
from module.notify.configuration import DisabledNotificationConfig
from module.task_registry import TASK_SPECS


def _template() -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads(Path("config/template.json").read_text(encoding="utf-8")),
    )


def _task_settings[SettingsT](
    compiled: CompiledConfiguration,
    task_id: str,
    expected_type: type[SettingsT],
) -> SettingsT:
    settings = compiled.tasks[task_id].settings
    assert isinstance(settings, expected_type)
    return settings


def _task_revisions(compiled: CompiledConfiguration) -> dict[str, int]:
    return {task_id: task.revision for task_id, task in compiled.tasks.items()}


def test_current_schema_rejects_duplicate_json_fields(tmp_path: Path) -> None:
    definition_path = tmp_path / "args.json"
    definition_path.write_text('{"Main": {}, "Main": {}}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="duplicate JSON field: Main"):
        CurrentConfigurationSchema(definition_path)


def test_template_compiles_to_exact_runtime_task_and_schedule_coverage() -> None:
    compiled = WebConfigurationCompiler().compile(_template())

    assert set(compiled.tasks) == set(TASK_SPECS)
    assert set(_task_revisions(compiled)) == set(TASK_SPECS)
    assert all(task.revision > 0 for task in compiled.tasks.values())
    assert compiled.device_serial == "127.0.0.1:16384"
    assert compiled.notification == DisabledNotificationConfig()


def test_compiled_task_revision_changes_only_for_the_changed_task() -> None:
    document = _template()
    original = WebConfigurationCompiler().compile(document)
    repeated = WebConfigurationCompiler().compile(document)
    main = cast("dict[str, object]", document["Main"])
    campaign = cast("dict[str, object]", main["Campaign"])
    campaign["Name"] = "12-3"
    changed = WebConfigurationCompiler().compile(document)

    repeated_revisions = _task_revisions(repeated)
    original_revisions = _task_revisions(original)
    changed_revisions = _task_revisions(changed)
    assert repeated_revisions == original_revisions
    assert changed_revisions["main"] != original_revisions["main"]
    assert {task_id: revision for task_id, revision in changed_revisions.items() if task_id != "main"} == {
        task_id: revision for task_id, revision in original_revisions.items() if task_id != "main"
    }


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("Fleet1Value", 73),
        ("Fleet1Record", "2026-07-15 12:34:56"),
        ("Fleet2Value", 91),
        ("Fleet2Record", "2026-07-15 12:34:56"),
    ],
)
def test_campaign_revision_ignores_runtime_emotion_ledger_updates(field_name: str, value: object) -> None:
    document = _template()
    original = WebConfigurationCompiler().compile(document)
    main = cast("dict[str, object]", document["Main"])
    emotion = cast("dict[str, object]", main["Emotion"])
    emotion[field_name] = value

    changed = WebConfigurationCompiler().compile(document)

    assert changed.tasks["main"] == original.tasks["main"]
    assert changed.tasks["main"].revision == original.tasks["main"].revision
    changed_main = cast("dict[str, object]", changed.runtime_document["Main"])
    changed_emotion = cast("dict[str, object]", changed_main["Emotion"])
    if isinstance(value, str):
        assert str(changed_emotion[field_name]) == value
    else:
        assert changed_emotion[field_name] == value


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("Fleet1Control", "prevent_yellow_face"),
        ("Fleet1Recover", "dormitory_floor_1"),
        ("Fleet1Oath", True),
    ],
)
def test_campaign_revision_tracks_emotion_policy_updates(field_name: str, value: object) -> None:
    document = _template()
    original = WebConfigurationCompiler().compile(document)
    main = cast("dict[str, object]", document["Main"])
    emotion = cast("dict[str, object]", main["Emotion"])
    emotion[field_name] = value

    changed = WebConfigurationCompiler().compile(document)

    assert changed.tasks["main"].revision != original.tasks["main"].revision


def test_opsi_explore_revision_ignores_runtime_last_zone() -> None:
    document = _template()
    original = WebConfigurationCompiler().compile(document)
    explore = cast("dict[str, object]", document["OpsiExplore"])
    settings = cast("dict[str, object]", explore["OpsiExplore"])
    settings["LastZone"] = 44

    changed = WebConfigurationCompiler().compile(document)

    assert changed.tasks["opsi_explore"] == original.tasks["opsi_explore"]
    assert changed.tasks["opsi_explore"].revision == original.tasks["opsi_explore"].revision
    changed_explore = cast("dict[str, object]", changed.runtime_document["OpsiExplore"])
    changed_settings = cast("dict[str, object]", changed_explore["OpsiExplore"])
    assert changed_settings["LastZone"] == 44


def test_opsi_explore_revision_tracks_user_policy() -> None:
    document = _template()
    original = WebConfigurationCompiler().compile(document)
    explore = cast("dict[str, object]", document["OpsiExplore"])
    settings = cast("dict[str, object]", explore["OpsiExplore"])
    settings["SpecialRadar"] = True

    changed = WebConfigurationCompiler().compile(document)

    assert changed.tasks["opsi_explore"].revision != original.tasks["opsi_explore"].revision


def test_compiler_projects_campaign_opsi_and_direct_command_settings() -> None:
    compiled = WebConfigurationCompiler().compile(_template())
    main = _task_settings(compiled, "main", CampaignJobSettings)
    assert main.stage_refs == (StageRef("campaign_main", "12-4"),)
    assert main.difficulty.value == "normal"
    execution = main.execution
    assert execution.automation.ambush_evade is True
    assert execution.automation.use_2x_book is False
    assert execution.automation.use_auto_search is True
    assert execution.automation.use_clear_mode is True
    assert execution.automation.use_fleet_lock is True
    assert (
        execution.fleets.fleet1,
        execution.fleets.fleet1_mode.value,
        execution.fleets.fleet1_step,
        execution.fleets.fleet2,
        execution.fleets.fleet2_mode.value,
        execution.fleets.fleet2_step,
        execution.fleets.order.value,
    ) == (1, "combat_auto", 3, 2, "combat_auto", 2, "fleet1_mob_fleet2_boss")
    assert (
        execution.submarine.fleet,
        execution.submarine.mode.value,
        execution.submarine.auto_search_mode.value,
        execution.submarine.distance_to_boss.value,
    ) == (0, "do_not_use", "sub_standby", "2_grid_to_boss")
    assert execution.emotion.mode.value == "calculate"
    assert (
        execution.emotion.fleet1.control.value,
        execution.emotion.fleet1.recover.value,
        execution.emotion.fleet1.oath,
    ) == ("prevent_green_face", "not_in_dormitory", False)
    assert execution.hp_control.hp_balance_weight == (1_000, 1_000, 1_000)
    assert execution.hp_control.hp_balance_threshold == 0.2
    assert execution.hp_control.repair_use_multi_threshold == 0.6
    assert execution.enemy_priority.scale_balance_weight.value == "default_mode"

    event_a = _task_settings(compiled, "event_a", CampaignJobSettings)
    assert tuple(ref.stage_id for ref in event_a.stage_refs) == ("t1", "t2", "t3")
    gems = _task_settings(compiled, "gems_farming", CampaignJobSettings)
    assert gems.execution.hp_control == execution.hp_control
    assert gems.execution.enemy_priority == execution.enemy_priority
    assert gems.gems_farming is not None
    assert gems.gems_farming.fallback_ref == StageRef("campaign_main", "2-4")
    assert gems.gems_farming.flagship_change.value == "ship"
    assert gems.gems_farming.common_carrier.value == "any"
    assert gems.gems_farming.vanguard_change.value == "ship"
    assert gems.gems_farming.common_destroyer.value == "any"

    opsi = _task_settings(compiled, "opsi_meowfficer_farming", MeowfficerFarmingSettings)
    assert opsi.hazard_level == 5
    event_story = _task_settings(compiled, "event_story", EventStorySettings)
    assert event_story.content_id == ContentId("event_20260625_cn")
    assert event_story.skip_battle is True
    coalition_sp = _task_settings(compiled, "coalition_sp", CoalitionSpSettings)
    assert coalition_sp.fleet.value == "multi"
    uncensored = _task_settings(compiled, "azur_lane_uncensored", UncensoredSettings)
    assert uncensored.package_name == "com.bilibili.azurlane"


def test_compiler_projects_encounter_facility_composite_and_market_settings() -> None:
    compiled = WebConfigurationCompiler().compile(_template())
    daily = _task_settings(compiled, "daily", DailySettings)
    assert daily.use_daily_skip is True
    assert (daily.missions.escort.stage.value, daily.missions.escort.fleet) == ("first", 1)
    assert (
        daily.missions.supply_line_disruption.stage.value,
        daily.missions.supply_line_disruption.fleet,
    ) == ("second", None)

    hard = _task_settings(compiled, "hard", HardSettings)
    assert hard.schedule.timezone_name == "Asia/Shanghai"
    assert hard.failure_retry_delay.lower_seconds == 1_800
    assert hard.resource_retry_delay == timedelta(seconds=7_200)
    assert (hard.stage, hard.fleet.value) == ("11-4", 1)
    exercise = _task_settings(compiled, "exercise", ExerciseSettings)
    assert exercise.opponent_mode.value == "max_exp"
    assert exercise.opponent_trials == 1
    assert exercise.strategy.value == "aggressive"
    assert exercise.low_hp_threshold == 0.4
    assert exercise.low_hp_confirm_wait_seconds == 0.1

    research = _task_settings(compiled, "research", ResearchSettings)
    assert research.selection.use_cube.value == "only_05_hour"
    assert research.selection.use_coin.value == "always_use"
    assert research.selection.allow_delay is True
    assert research.selection.preset_filter == "series_9_blueprint_ta152"
    assert isinstance(research.selection.custom_filter, str)
    commission = _task_settings(compiled, "commission", CommissionSettings)
    assert commission.selection.preset_filter.value == "cube"
    tactical = _task_settings(compiled, "tactical", TacticalSettings)
    assert tactical.rapid_training_slot.value == "do_not_use"
    assert (
        tactical.experience_overflow.enabled,
        tactical.experience_overflow.t1_allow,
        tactical.experience_overflow.t2_allow,
        tactical.experience_overflow.t3_allow,
        tactical.experience_overflow.t4_allow,
    ) == (True, 200, 200, 100, 100)
    freebies = _task_settings(compiled, "freebies", FreebiesSettings)
    assert (
        freebies.mail.claim_merit,
        freebies.mail.claim_maintenance,
        freebies.mail.claim_trade_license,
        freebies.mail.delete_collected,
    ) == (True, False, False, True)
    assert (freebies.supply_pack.collect, freebies.supply_pack.day_of_week) == (True, 0)
    shop_frequent = _task_settings(compiled, "shop_frequent", ShopFrequentSettings)
    assert shop_frequent.plan.filter is not None
    shop_once = _task_settings(compiled, "shop_once", ShopOnceSettings)
    assert shop_once.plan.guild.box_t3 == "ironblood"
    assert shop_once.plan.guild.pr3 == "cheshire"


def test_compiler_preserves_scheduler_interval_bounds_in_canonical_seconds() -> None:
    compiled = WebConfigurationCompiler().compile(_template())
    tactical = _task_settings(compiled, "tactical", TacticalSettings)
    reward = _task_settings(compiled, "reward", RewardSettings)

    assert tactical.failure_retry_delay.lower_seconds == 7_200
    assert tactical.failure_retry_delay.upper_seconds == 14_400
    assert reward.success_delay.lower_seconds == 7_200
    assert reward.success_delay.upper_seconds == 14_400
