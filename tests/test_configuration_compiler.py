import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from module.bootstrap import ConfigurationCompileError, WebConfigurationCompiler
from module.notify import DisabledNotificationConfig, SmtpNotificationConfig, SmtpTransport
from module.task_registry import TASK_CATALOG

if TYPE_CHECKING:
    from module.state import JsonValue


def _template() -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads(Path("config/template.json").read_text(encoding="utf-8")),
    )


def test_template_compiles_to_exact_runtime_task_and_schedule_coverage() -> None:
    compiled = WebConfigurationCompiler().compile(_template())

    payload = cast("dict[str, JsonValue]", compiled.payload)
    tasks = cast("dict[str, JsonValue]", payload["tasks"])
    scheduled = {task_id for task_id, definition in TASK_CATALOG.items() if definition.priority is not None}
    assert payload["schema_version"] == 1
    assert set(tasks) == set(TASK_CATALOG)
    assert {schedule.task_id for schedule in compiled.schedules} == scheduled
    assert [schedule.priority for schedule in compiled.schedules] == [
        definition.priority for definition in TASK_CATALOG.values() if definition.priority is not None
    ]
    assert compiled.device_serial == "127.0.0.1:16384"
    assert compiled.notification == DisabledNotificationConfig()
    assert compiled.source_revision.startswith("sha256:")
    assert compiled.assembly_revision.startswith("sha256:")


def test_compiler_projects_legacy_notification_key_to_typed_assembly_config() -> None:
    credential = "smtp-password-must-not-leak"
    document = _template()
    baseline = WebConfigurationCompiler().compile(document)
    alas = cast("dict[str, object]", document["Alas"])
    error = cast("dict[str, object]", alas["Error"])
    error["OnePushConfig"] = f"""
provider: smtp
host: smtp.example.com
user: sender@example.com
password: {credential}
receiver: receiver@example.com
port: 465
"""

    compiled = WebConfigurationCompiler().compile(document)

    assert compiled.notification == SmtpNotificationConfig(
        host="smtp.example.com",
        user="sender@example.com",
        password=credential,
        recipients=("receiver@example.com",),
        port=465,
        transport=SmtpTransport.IMPLICIT_TLS,
    )
    assert compiled.source_revision == baseline.source_revision
    assert compiled.assembly_revision != baseline.assembly_revision
    assert credential not in repr(compiled)
    assert credential not in json.dumps(compiled.payload)


def test_notification_can_be_compiled_even_when_an_unrelated_task_setting_is_invalid() -> None:
    document = _template()
    alas = cast("dict[str, object]", document["Alas"])
    emulator = cast("dict[str, object]", alas["Emulator"])
    emulator["Serial"] = 123

    notification = WebConfigurationCompiler().compile_notification(document)

    assert notification == DisabledNotificationConfig()


def test_compiler_rejects_invalid_legacy_notification_without_exposing_password() -> None:
    credential = "invalid-yaml-password-must-not-leak"
    document = _template()
    alas = cast("dict[str, object]", document["Alas"])
    error = cast("dict[str, object]", alas["Error"])
    error["OnePushConfig"] = f"provider: smtp\npassword: {credential}\nreceiver: ["

    with pytest.raises(ConfigurationCompileError) as caught:
        WebConfigurationCompiler().compile(document)

    assert str(caught.value) == "$.Alas.Error.OnePushConfig SMTP config must be valid YAML"
    assert credential not in str(caught.value)
    assert credential not in repr(caught.value)


def test_compiled_revision_changes_only_when_the_persisted_runtime_snapshot_changes() -> None:
    document = _template()
    original = WebConfigurationCompiler().compile(document)
    repeated = WebConfigurationCompiler().compile(document)
    main = cast("dict[str, object]", document["Main"])
    scheduler = cast("dict[str, object]", main["Scheduler"])
    scheduler["Enable"] = not cast("bool", scheduler["Enable"])
    changed = WebConfigurationCompiler().compile(document)

    assert repeated.source_revision == original.source_revision
    assert changed.source_revision != original.source_revision
    assert repeated.assembly_revision == original.assembly_revision
    assert changed.assembly_revision == original.assembly_revision


def test_assembly_revision_tracks_only_process_bound_configuration() -> None:
    document = _template()
    original = WebConfigurationCompiler().compile(document)
    alas = cast("dict[str, object]", document["Alas"])
    optimization = cast("dict[str, object]", alas["Optimization"])
    optimization["ScreenshotInterval"] = 0.5
    changed = WebConfigurationCompiler().compile(document)

    assert changed.source_revision == original.source_revision
    assert changed.assembly_revision != original.assembly_revision


def test_compiler_projects_campaign_opsi_and_direct_command_settings() -> None:
    payload = cast("dict[str, JsonValue]", WebConfigurationCompiler().compile(_template()).payload)
    tasks = cast("dict[str, JsonValue]", payload["tasks"])

    main = cast("dict[str, JsonValue]", tasks["main"])
    assert main["pack_id"] == "campaign_main"
    assert main["stage_ids"] == ["12-4"]
    assert main["difficulty"] == "normal"
    execution = cast("dict[str, JsonValue]", main["execution"])
    assert execution["automation"] == {
        "ambush_evade": True,
        "use_2x_book": False,
        "use_auto_search": True,
        "use_clear_mode": True,
        "use_fleet_lock": True,
    }
    assert execution["fleets"] == {
        "fleet1": 1,
        "fleet1_mode": "combat_auto",
        "fleet1_step": 3,
        "fleet2": 2,
        "fleet2_mode": "combat_auto",
        "fleet2_step": 2,
        "order": "fleet1_mob_fleet2_boss",
    }
    assert execution["submarine"] == {
        "fleet": 0,
        "mode": "do_not_use",
        "auto_search_mode": "sub_standby",
        "distance_to_boss": "2_grid_to_boss",
    }
    emotion = cast("dict[str, JsonValue]", execution["emotion"])
    assert emotion["mode"] == "calculate"
    assert emotion["fleet1"] == {
        "value": 119,
        "recorded_at": "2019-12-31T16:00:00+00:00",
        "control": "prevent_green_face",
        "recover": "not_in_dormitory",
        "oath": False,
    }
    assert execution["hp_control"] == {
        "use_hp_balance": False,
        "use_emergency_repair": False,
        "use_low_hp_retreat": False,
        "hp_balance_threshold": 0.2,
        "hp_balance_weight": [1_000, 1_000, 1_000],
        "repair_use_single_threshold": 0.3,
        "repair_use_multi_threshold": 0.6,
        "low_hp_retreat_threshold": 0.3,
    }
    assert execution["enemy_priority"] == {"scale_balance_weight": "default_mode"}
    assert "formation" not in cast("dict[str, JsonValue]", execution["fleets"])
    event_a = cast("dict[str, JsonValue]", tasks["event_a"])
    assert event_a["stage_ids"] == ["a1", "a2", "a3"]
    gems_execution = cast(
        "dict[str, JsonValue]",
        cast("dict[str, JsonValue]", tasks["gems_farming"])["execution"],
    )
    assert gems_execution["hp_control"] == execution["hp_control"]
    assert gems_execution["enemy_priority"] == execution["enemy_priority"]
    gems = cast("dict[str, JsonValue]", tasks["gems_farming"])
    gems_policy = cast("dict[str, JsonValue]", gems["gems_farming"])
    assert gems_policy["fallback"] == {"pack_id": "campaign_main", "stage_id": "2-4"}
    assert gems_policy["flagship_change"] == "ship"
    assert gems_policy["common_carrier"] == "any"
    assert gems_policy["vanguard_change"] == "ship"
    assert gems_policy["common_destroyer"] == "any"
    assert cast("str", gems_policy["equipment_code_config"]).startswith("DD:")
    opsi = cast("dict[str, JsonValue]", tasks["opsi_meowfficer_farming"])
    assert opsi["hazard_level"] == 5
    assert tasks["event_story"] == {"event": "event_20260625_cn", "skip_battle": True}
    assert cast("dict[str, JsonValue]", tasks["coalition_sp"])["fleet"] == "multi"
    assert tasks["azur_lane_uncensored"] == {"package_name": "com.bilibili.azurlane"}


def test_compiler_projects_encounter_facility_composite_and_market_settings() -> None:
    payload = cast("dict[str, JsonValue]", WebConfigurationCompiler().compile(_template()).payload)
    tasks = cast("dict[str, JsonValue]", payload["tasks"])
    daily = cast("dict[str, JsonValue]", tasks["daily"])
    assert daily["use_daily_skip"] is True
    daily_missions = cast("dict[str, JsonValue]", daily["missions"])
    assert daily_missions["escort"] == {"stage": "first", "fleet": 1}
    assert daily_missions["supply_line_disruption"] == {"stage": "second", "fleet": None}
    assert tasks["hard"] == {
        "schedule": {"timezone": "Asia/Shanghai", "triggers": ["00:00"]},
        "failure_retry_seconds": {"lower_seconds": 1_800, "upper_seconds": 1_800},
        "resource_retry_seconds": 7_200,
        "stage": "11-4",
        "fleet": 1,
    }
    exercise = cast("dict[str, JsonValue]", tasks["exercise"])
    assert exercise["opponent_mode"] == "max_exp"
    assert exercise["opponent_trials"] == 1
    assert exercise["strategy"] == "aggressive"
    assert exercise["low_hp_threshold"] == 0.4
    assert exercise["low_hp_confirm_wait_seconds"] == 0.1

    research = cast("dict[str, JsonValue]", tasks["research"])
    research_selection = cast("dict[str, JsonValue]", research["selection"])
    assert research_selection | {"custom_filter": "<redacted>"} == {
        "use_cube": "only_05_hour",
        "use_coin": "always_use",
        "use_part": "always_use",
        "allow_delay": True,
        "preset_filter": "series_9_blueprint_ta152",
        "custom_filter": "<redacted>",
    }
    assert isinstance(research_selection["custom_filter"], str)
    commission = cast("dict[str, JsonValue]", tasks["commission"])
    assert cast("dict[str, JsonValue]", commission["selection"])["preset_filter"] == "cube"
    tactical = cast("dict[str, JsonValue]", tasks["tactical"])
    assert tactical["rapid_training_slot"] == "do_not_use"
    assert tactical["experience_overflow"] == {
        "enabled": True,
        "t1_allow": 200,
        "t2_allow": 200,
        "t3_allow": 100,
        "t4_allow": 100,
    }
    freebies = cast("dict[str, JsonValue]", tasks["freebies"])
    assert freebies["mail"] == {
        "claim_merit": True,
        "claim_maintenance": False,
        "claim_trade_license": False,
        "delete_collected": True,
    }
    assert freebies["supply_pack"] == {"collect": True, "day_of_week": 0}
    shop_frequent = cast("dict[str, JsonValue]", tasks["shop_frequent"])
    assert cast("dict[str, JsonValue]", shop_frequent["plan"])["filter"] is not None
    shop_once = cast("dict[str, JsonValue]", tasks["shop_once"])
    guild_shop = cast(
        "dict[str, JsonValue]",
        cast("dict[str, JsonValue]", shop_once["plan"])["guild"],
    )
    assert guild_shop["box_t3"] == "ironblood"
    assert guild_shop["pr3"] == "cheshire"


def test_compiler_preserves_scheduler_interval_bounds_in_canonical_seconds() -> None:
    payload = cast("dict[str, JsonValue]", WebConfigurationCompiler().compile(_template()).payload)
    tasks = cast("dict[str, JsonValue]", payload["tasks"])

    tactical = cast("dict[str, JsonValue]", tasks["tactical"])
    reward = cast("dict[str, JsonValue]", tasks["reward"])
    assert tactical["failure_retry_seconds"] == {
        "lower_seconds": 7_200,
        "upper_seconds": 14_400,
    }
    assert reward["success_delay_seconds"] == {
        "lower_seconds": 7_200,
        "upper_seconds": 14_400,
    }


@pytest.mark.parametrize("interval", [17, "17"])
def test_compiler_normalizes_single_scheduler_interval_to_equal_bounds(interval: int | str) -> None:
    document = _template()
    hard = cast("dict[str, object]", document["Hard"])
    scheduler = cast("dict[str, object]", hard["Scheduler"])
    scheduler["FailureInterval"] = interval

    payload = cast("dict[str, JsonValue]", WebConfigurationCompiler().compile(document).payload)
    tasks = cast("dict[str, JsonValue]", payload["tasks"])
    hard_settings = cast("dict[str, JsonValue]", tasks["hard"])

    assert hard_settings["failure_retry_seconds"] == {
        "lower_seconds": 1_020,
        "upper_seconds": 1_020,
    }


def test_compiler_rejects_reversed_scheduler_interval() -> None:
    document = _template()
    tactical = cast("dict[str, object]", document["Tactical"])
    scheduler = cast("dict[str, object]", tactical["Scheduler"])
    scheduler["FailureInterval"] = "240-120"

    with pytest.raises(ConfigurationCompileError, match="lower bound must not exceed upper bound"):
        WebConfigurationCompiler().compile(document)


def test_compiler_preserves_disabled_schedule_due_time_as_an_aware_fact() -> None:
    compiled = WebConfigurationCompiler().compile(_template())
    main = next(schedule for schedule in compiled.schedules if schedule.task_id == "main")

    assert not main.enabled
    assert main.due_at is not None
    assert main.due_at.utcoffset() is not None


def test_compiler_normalizes_disabled_shop_filters_to_null() -> None:
    document = _template()
    for config_name, group in (
        ("ShopFrequent", "GeneralShop"),
        ("ShopOnce", "MeritShop"),
        ("ShopOnce", "GuildShop"),
        ("ShopOnce", "CoreShop"),
        ("ShopOnce", "MedalShop2"),
    ):
        task = cast("dict[str, object]", document[config_name])
        settings = cast("dict[str, object]", task[group])
        settings["Filter"] = "  "

    payload = cast("dict[str, JsonValue]", WebConfigurationCompiler().compile(document).payload)
    tasks = cast("dict[str, JsonValue]", payload["tasks"])
    frequent = cast("dict[str, JsonValue]", tasks["shop_frequent"])
    assert cast("dict[str, JsonValue]", frequent["plan"])["filter"] is None
    once = cast("dict[str, JsonValue]", tasks["shop_once"])
    plan = cast("dict[str, JsonValue]", once["plan"])
    assert cast("dict[str, JsonValue]", plan["merit"])["filter"] is None
    assert cast("dict[str, JsonValue]", plan["guild"])["filter"] is None
    assert cast("dict[str, JsonValue]", plan["core"])["filter"] is None
    assert cast("dict[str, JsonValue]", plan["medal"])["filter"] is None


@pytest.mark.parametrize(
    ("path", "value", "match"),
    [
        (("Alas", "Emulator", "Serial"), 1, "must be a str"),
        (("Research", "Scheduler", "ServerUpdate"), "25:00", "HH:MM"),
        (("Main", "Scheduler", "NextRun"), "not-a-date", "ISO datetime"),
        (("Main", "Emotion", "Fleet1Record"), "not-a-date", "ISO datetime"),
        (("Main", "HpControl", "HpBalanceWeight"), "1000, 900", "exactly three"),
    ],
)
def test_compiler_rejects_invalid_source_values(
    path: tuple[str, str, str],
    value: object,
    match: str,
) -> None:
    document = _template()
    task = cast("dict[str, object]", document[path[0]])
    group = cast("dict[str, object]", task[path[1]])
    group[path[2]] = value

    with pytest.raises(ConfigurationCompileError, match=match):
        WebConfigurationCompiler().compile(document)
