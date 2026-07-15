import json
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from module.bootstrap.configuration_compiler import (
    ConfigurationCompileError,
    ConfigurationDocument,
    CurrentConfigurationSchema,
    WebConfigurationCompiler,
)
from module.notify.configuration import (
    DisabledNotificationConfig,
    NotificationConfigError,
    SmtpNotificationConfig,
    SmtpTransport,
)
from module.task_registry import TASK_CATALOG

if TYPE_CHECKING:
    from module.config.deep import MutableDeepData
    from module.runtime.settings import JsonValue


def _template() -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads(Path("config/template.json").read_text(encoding="utf-8")),
    )


def test_current_schema_rejects_duplicate_json_fields(tmp_path: Path) -> None:
    definition_path = tmp_path / "args.json"
    definition_path.write_text('{"Main": {}, "Main": {}}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="duplicate JSON field: Main"):
        CurrentConfigurationSchema(definition_path)


def test_template_compiles_to_exact_runtime_task_and_schedule_coverage() -> None:
    compiled = WebConfigurationCompiler().compile(_template())

    assert set(compiled.tasks) == set(TASK_CATALOG)
    assert set(compiled.task_revisions) == set(TASK_CATALOG)
    assert all(revision > 0 for revision in compiled.task_revisions.values())
    assert compiled.device_serial == "127.0.0.1:16384"
    assert compiled.notification == DisabledNotificationConfig()


def test_compiler_parses_the_source_document_once(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = 0
    original_parse = CurrentConfigurationSchema.parse

    def counted_parse(
        schema: CurrentConfigurationSchema,
        document: ConfigurationDocument,
    ) -> MutableDeepData:
        nonlocal calls
        calls += 1
        return original_parse(schema, document)

    monkeypatch.setattr(CurrentConfigurationSchema, "parse", counted_parse)

    WebConfigurationCompiler().compile(_template())

    assert calls == 1


def test_compiled_runtime_document_is_an_independent_snapshot_on_every_read() -> None:
    compiled = WebConfigurationCompiler().compile(_template())
    first = compiled.runtime_document
    main = cast("dict[str, object]", first["Main"])
    campaign = cast("dict[str, object]", main["Campaign"])
    campaign["Name"] = "mutated"

    second = compiled.runtime_document
    second_main = cast("dict[str, object]", second["Main"])
    second_campaign = cast("dict[str, object]", second_main["Campaign"])
    assert second_campaign["Name"] == "12-4"


def test_compiler_projects_explicit_smtp_fields_to_typed_notification_config() -> None:
    credential = "local-smtp-password"
    document = _template()
    baseline = WebConfigurationCompiler().compile(document)
    alas = cast("dict[str, object]", document["Alas"])
    error = cast("dict[str, object]", alas["Error"])
    error.update(
        {
            "SmtpEnabled": True,
            "SmtpHost": "smtp.example.com",
            "SmtpPort": 465,
            "SmtpTransport": "implicit_tls",
            "SmtpUser": "sender@example.com",
            "SmtpPassword": credential,
            "SmtpRecipients": "receiver@example.com",
        }
    )

    compiled = WebConfigurationCompiler().compile(document)

    assert compiled.notification == SmtpNotificationConfig(
        host="smtp.example.com",
        user="sender@example.com",
        password=credential,
        recipients=("receiver@example.com",),
        port=465,
        transport=SmtpTransport.IMPLICIT_TLS,
    )
    assert compiled.task_revisions == baseline.task_revisions
    assert credential in repr(compiled)
    assert credential not in repr(compiled.tasks)


def test_compiler_reports_invalid_smtp_field() -> None:
    document = _template()
    alas = cast("dict[str, object]", document["Alas"])
    error = cast("dict[str, object]", alas["Error"])
    error.update(
        {
            "SmtpEnabled": True,
            "SmtpHost": "",
            "SmtpUser": "sender@example.com",
            "SmtpPassword": "secret",
        }
    )

    with pytest.raises(ConfigurationCompileError) as caught:
        WebConfigurationCompiler().compile(document)

    assert str(caught.value) == "$.Alas.Error SMTP host must be trimmed and non-empty"
    assert isinstance(caught.value.__cause__, NotificationConfigError)


def test_compiled_task_revision_changes_only_for_the_changed_task() -> None:
    document = _template()
    original = WebConfigurationCompiler().compile(document)
    repeated = WebConfigurationCompiler().compile(document)
    main = cast("dict[str, object]", document["Main"])
    campaign = cast("dict[str, object]", main["Campaign"])
    campaign["Name"] = "12-3"
    changed = WebConfigurationCompiler().compile(document)

    assert repeated.task_revisions == original.task_revisions
    assert changed.task_revisions["main"] != original.task_revisions["main"]
    assert {task_id: revision for task_id, revision in changed.task_revisions.items() if task_id != "main"} == {
        task_id: revision for task_id, revision in original.task_revisions.items() if task_id != "main"
    }


def test_compiled_settings_are_deeply_read_only_and_detached_from_source() -> None:
    document = _template()
    compiled = WebConfigurationCompiler().compile(document)
    main_source = cast("dict[str, object]", document["Main"])
    campaign_source = cast("dict[str, object]", main_source["Campaign"])
    campaign_source["Name"] = "12-3"

    main = compiled.tasks["main"]
    assert main["stage_ids"] == ("12-4",)
    with pytest.raises(TypeError):
        cast("dict[str, object]", compiled.tasks)["main"] = {}
    with pytest.raises(TypeError):
        cast("dict[str, object]", main)["stage_ids"] = ()


def test_compiler_projects_campaign_opsi_and_direct_command_settings() -> None:
    tasks = WebConfigurationCompiler().compile(_template()).tasks

    main = cast("dict[str, JsonValue]", tasks["main"])
    assert main["pack_id"] == "campaign_main"
    assert main["stage_ids"] == ("12-4",)
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
        "hp_balance_weight": (1_000, 1_000, 1_000),
        "repair_use_single_threshold": 0.3,
        "repair_use_multi_threshold": 0.6,
        "low_hp_retreat_threshold": 0.3,
    }
    assert execution["enemy_priority"] == {"scale_balance_weight": "default_mode"}
    assert "formation" not in cast("dict[str, JsonValue]", execution["fleets"])
    event_a = cast("dict[str, JsonValue]", tasks["event_a"])
    assert event_a["stage_ids"] == ("t1", "t2", "t3")
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
    assert "equipment_code_config" not in gems_policy
    opsi = cast("dict[str, JsonValue]", tasks["opsi_meowfficer_farming"])
    assert opsi["hazard_level"] == 5
    event_story = cast("dict[str, JsonValue]", tasks["event_story"])
    assert isinstance(event_story["event"], str)
    assert event_story["skip_battle"] is True
    assert cast("dict[str, JsonValue]", tasks["coalition_sp"])["fleet"] == "multi"
    assert tasks["azur_lane_uncensored"] == {"package_name": "com.bilibili.azurlane"}


def test_compiler_projects_encounter_facility_composite_and_market_settings() -> None:
    tasks = WebConfigurationCompiler().compile(_template()).tasks
    daily = cast("dict[str, JsonValue]", tasks["daily"])
    assert daily["use_daily_skip"] is True
    daily_missions = cast("dict[str, JsonValue]", daily["missions"])
    assert daily_missions["escort"] == {"stage": "first", "fleet": 1}
    assert daily_missions["supply_line_disruption"] == {"stage": "second", "fleet": None}
    assert tasks["hard"] == {
        "schedule": {"timezone": "Asia/Shanghai", "triggers": ("00:00",)},
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
    tasks = WebConfigurationCompiler().compile(_template()).tasks

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


def test_compiler_accepts_single_interval_for_range_default() -> None:
    document = _template()
    tactical = cast("dict[str, object]", document["Tactical"])
    scheduler = cast("dict[str, object]", tactical["Scheduler"])
    scheduler["FailureInterval"] = 120

    tasks = WebConfigurationCompiler().compile(document).tasks
    tactical_settings = cast("dict[str, JsonValue]", tasks["tactical"])

    assert tactical_settings["failure_retry_seconds"] == {
        "lower_seconds": 7_200,
        "upper_seconds": 7_200,
    }


def test_compiler_accepts_range_for_integer_interval_default() -> None:
    document = _template()
    hard = cast("dict[str, object]", document["Hard"])
    scheduler = cast("dict[str, object]", hard["Scheduler"])
    scheduler["FailureInterval"] = "120-240"

    tasks = WebConfigurationCompiler().compile(document).tasks
    hard_settings = cast("dict[str, JsonValue]", tasks["hard"])

    assert hard_settings["failure_retry_seconds"] == {
        "lower_seconds": 7_200,
        "upper_seconds": 14_400,
    }


@pytest.mark.parametrize(
    ("task_name", "field_name", "value", "expected_type"),
    [
        ("Hard", "FailureInterval", "17", "int"),
        ("Restart", "Enable", "true", "bool"),
    ],
)
def test_compiler_rejects_legacy_scalar_string_coercion(
    task_name: str,
    field_name: str,
    value: str,
    expected_type: str,
) -> None:
    document = _template()
    task = cast("dict[str, object]", document[task_name])
    scheduler = cast("dict[str, object]", task["Scheduler"])
    scheduler[field_name] = value

    path = rf"\$\.{task_name}\.Scheduler\.{field_name} must be a {expected_type}"
    with pytest.raises(ConfigurationCompileError, match=path):
        WebConfigurationCompiler().compile(document)


def test_compiler_rejects_reversed_scheduler_interval() -> None:
    document = _template()
    tactical = cast("dict[str, object]", document["Tactical"])
    scheduler = cast("dict[str, object]", tactical["Scheduler"])
    scheduler["FailureInterval"] = "240-120"

    with pytest.raises(ConfigurationCompileError, match="lower bound must not exceed upper bound"):
        WebConfigurationCompiler().compile(document)


@pytest.mark.parametrize("triggers", ["04:00,04:00", "12:00,04:00"])
def test_compiler_rejects_duplicate_or_unsorted_server_updates(triggers: str) -> None:
    document = _template()
    research = cast("dict[str, object]", document["Research"])
    scheduler = cast("dict[str, object]", research["Scheduler"])
    scheduler["ServerUpdate"] = triggers

    with pytest.raises(ConfigurationCompileError, match="strictly increasing without duplicates"):
        WebConfigurationCompiler().compile(document)


@pytest.mark.parametrize("value", [0, -1])
def test_compiler_rejects_non_positive_scheduler_interval(value: int) -> None:
    document = _template()
    hard = cast("dict[str, object]", document["Hard"])
    scheduler = cast("dict[str, object]", hard["Scheduler"])
    scheduler["FailureInterval"] = value

    with pytest.raises(ConfigurationCompileError, match="must be positive"):
        WebConfigurationCompiler().compile(document)


def test_compiler_rejects_non_finite_float() -> None:
    document = _template()
    alas = cast("dict[str, object]", document["Alas"])
    optimization = cast("dict[str, object]", alas["Optimization"])
    optimization["ScreenshotInterval"] = float("nan")

    with pytest.raises(ConfigurationCompileError, match="must be a finite number"):
        WebConfigurationCompiler().compile(document)


def test_compiler_normalizes_integer_json_numbers_for_float_settings() -> None:
    document = _template()
    exercise = cast("dict[str, object]", document["Exercise"])
    exercise_settings = cast("dict[str, object]", exercise["Exercise"])
    exercise_settings["LowHpThreshold"] = 0

    compiled = WebConfigurationCompiler().compile(document)
    runtime_document = compiled.runtime_document

    tasks = compiled.tasks
    compiled_exercise = cast("dict[str, JsonValue]", tasks["exercise"])
    assert compiled_exercise["low_hp_threshold"] == 0.0
    assert type(compiled_exercise["low_hp_threshold"]) is float
    runtime_exercise = cast("dict[str, object]", runtime_document["Exercise"])
    runtime_settings = cast("dict[str, object]", runtime_exercise["Exercise"])
    assert runtime_settings["LowHpThreshold"] == 0.0
    assert type(runtime_settings["LowHpThreshold"]) is float


def test_compiler_preserves_explicit_numeric_text() -> None:
    document = _template()
    alas = cast("dict[str, object]", document["Alas"])
    error = cast("dict[str, object]", alas["Error"])
    error["SmtpPassword"] = "1234"
    general = cast("dict[str, object]", document["General"])
    enhance = cast("dict[str, object]", general["Enhance"])
    enhance["Filter"] = "1234"

    runtime_document = WebConfigurationCompiler().parse_runtime_document(document)
    parsed_alas = cast("dict[str, object]", runtime_document["Alas"])
    parsed_error = cast("dict[str, object]", parsed_alas["Error"])
    parsed_general = cast("dict[str, object]", runtime_document["General"])
    parsed_enhance = cast("dict[str, object]", parsed_general["Enhance"])

    assert parsed_error["SmtpPassword"] == "1234"
    assert parsed_enhance["Filter"] == "1234"


@pytest.mark.parametrize(
    ("group_name", "field_name", "value", "match"),
    [
        ("Emulator", "Serial", "127.0.0.1:7555", "MuMu12 TCP serial"),
        ("Error", "ScreenshotLength", 0, "between 1 and 300"),
        ("Error", "ScreenshotLength", 301, "between 1 and 300"),
        ("Optimization", "ScreenshotInterval", 0.09, "between 0.1 and 0.3"),
        ("Optimization", "ScreenshotInterval", 0.31, "between 0.1 and 0.3"),
        ("Optimization", "CombatScreenshotInterval", 0.29, "between 0.3 and 1.0"),
        ("Optimization", "CombatScreenshotInterval", 1.01, "between 0.3 and 1.0"),
    ],
)
def test_compiler_rejects_invalid_personal_device_settings(
    group_name: str,
    field_name: str,
    value: object,
    match: str,
) -> None:
    document = _template()
    alas = cast("dict[str, object]", document["Alas"])
    group = cast("dict[str, object]", alas[group_name])
    group[field_name] = value

    with pytest.raises(ConfigurationCompileError, match=match):
        WebConfigurationCompiler().compile(document)


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

    tasks = WebConfigurationCompiler().compile(document).tasks
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


@pytest.mark.parametrize(
    ("path", "expected_path"),
    [
        (("LegacyTask",), r"\$\.LegacyTask"),
        (("Main", "LegacyGroup"), r"\$\.Main\.LegacyGroup"),
        (("Main", "Campaign", "LegacyField"), r"\$\.Main\.Campaign\.LegacyField"),
    ],
)
def test_compiler_rejects_unknown_current_schema_fields(
    path: tuple[str, ...],
    expected_path: str,
) -> None:
    document = _template()
    owner = document
    for key in path[:-1]:
        owner = cast("dict[str, object]", owner[key])
    owner[path[-1]] = {}

    with pytest.raises(
        ConfigurationCompileError,
        match=rf"{expected_path} is not part of the current configuration schema",
    ):
        WebConfigurationCompiler().compile(document)


@pytest.mark.parametrize(
    "path",
    [
        ("Main",),
        ("Main", "Campaign"),
        ("Main", "Campaign", "Name"),
    ],
)
def test_compiler_rejects_missing_current_schema_fields(path: tuple[str, ...]) -> None:
    document = _template()
    owner = document
    for key in path[:-1]:
        owner = cast("dict[str, object]", owner[key])
    del owner[path[-1]]

    with pytest.raises(ConfigurationCompileError, match="is required by the current configuration schema"):
        WebConfigurationCompiler().compile(document)


def test_compiler_rejects_invalid_current_option_instead_of_falling_back() -> None:
    document = _template()
    research = cast("dict[str, object]", document["Research"])
    settings = cast("dict[str, object]", research["Research"])
    settings["UseCube"] = "legacy-option"

    with pytest.raises(
        ConfigurationCompileError,
        match=r"\$\.Research\.Research\.UseCube must be one of",
    ):
        WebConfigurationCompiler().compile(document)
