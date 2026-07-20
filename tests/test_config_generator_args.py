from copy import deepcopy
from datetime import datetime
from typing import TYPE_CHECKING, get_type_hints

import pytest

from module.config import config_updater
from module.config.config_generated import ConfigOverrides
from module.config.config_manual import FindPeaksParameter
from module.config.config_updater import ConfigGenerator, build_template
from module.config.deep import DeepValue, deep_exist, deep_get

if TYPE_CHECKING:
    from collections.abc import Mapping


def _arg(
    value: DeepValue,
    typ: str = "input",
    *,
    option: list[DeepValue] | None = None,
    valuetype: str | None = None,
    display: str | None = None,
) -> dict[str, DeepValue]:
    argument: dict[str, DeepValue] = {"value": value, "type": typ}
    if option is not None:
        argument["option"] = option
    if valuetype is not None:
        argument["valuetype"] = valuetype
    if display is not None:
        argument["display"] = display
    return argument


def _storage_group() -> dict[str, DeepValue]:
    return {"Storage": _arg({}, typ="storage", valuetype="ignore", display="disabled")}


def _generator(
    task: Mapping[str, DeepValue],
    argument: Mapping[str, DeepValue],
    default: Mapping[str, DeepValue] | None = None,
    override: Mapping[str, DeepValue] | None = None,
) -> ConfigGenerator:
    generator = object.__new__(ConfigGenerator)
    vars(generator)["task"] = task
    vars(generator)["argument"] = argument
    vars(generator)["default"] = default or {}
    vars(generator)["override"] = override or {}
    return generator


def test_args_adds_storage_without_mutating_task_groups() -> None:
    task = {"Main": {"tasks": {"Main": {"command": "main", "groups": ["Scheduler"]}}}}
    original_task = deepcopy(task)
    generator = _generator(
        task=task,
        argument={
            "Scheduler": {
                "Command": _arg("", option=["Main"]),
                "Enable": _arg(value=False, typ="checkbox"),
            },
            "Storage": _storage_group(),
        },
    )

    args = generator.args

    assert task == original_task
    assert deep_get(args, keys="Main.Storage") is not None
    assert deep_get(args, keys="Main.Scheduler.Command.value") == "Main"
    assert deep_get(args, keys="Main.Scheduler.Command.display") == "hide"


def test_args_applies_default_and_plain_override_values() -> None:
    generator = _generator(
        task={"Main": {"tasks": {"General": {"groups": ["Settings"]}}}},
        argument={
            "Settings": {
                "Mode": _arg("a", typ="select", option=["a", "b"]),
                "Hidden": _arg(1),
            },
            "Storage": _storage_group(),
        },
        default={"General": {"Settings": {"Mode": "b"}}},
        override={"General": {"Settings": {"Hidden": 2}}},
    )

    args = generator.args

    assert deep_get(args, keys="General.Settings.Mode.value") == "b"
    assert deep_get(args, keys="General.Settings.Hidden.value") == 2
    assert deep_get(args, keys="General.Settings.Hidden.display") == "hide"


def test_args_applies_dict_override_without_mutating_override_data() -> None:
    override = {"General": {"Settings": {"Mode": {"value": "b", "option": ["b"]}}}}
    original_override = deepcopy(override)
    generator = _generator(
        task={"Main": {"tasks": {"General": {"groups": ["Settings"]}}}},
        argument={
            "Settings": {
                "Mode": _arg("a", typ="select", option=["a", "b"]),
            },
            "Storage": _storage_group(),
        },
        override=override,
    )

    args = generator.args

    assert override == original_override
    assert deep_get(args, keys="General.Settings.Mode.value") == "b"
    assert deep_get(args, keys="General.Settings.Mode.option") == ["b"]
    assert deep_get(args, keys="General.Settings.Mode.display") == "hide"


def test_args_rejects_default_value_outside_options() -> None:
    generator = _generator(
        task={"Main": {"tasks": {"General": {"groups": ["Settings"]}}}},
        argument={
            "Settings": {
                "Choice": _arg("a", typ="select", option=["a", "b"]),
            },
            "Storage": _storage_group(),
        },
        default={"General": {"Settings": {"Choice": "unknown"}}},
    )

    with pytest.raises(ValueError, match=r"General\.Settings\.Choice"):
        _ = generator.args


def test_args_rejects_missing_override_path() -> None:
    generator = _generator(
        task={"Main": {"tasks": {"General": {"groups": ["Settings"]}}}},
        argument={"Settings": {"Count": _arg(1)}, "Storage": _storage_group()},
        override={"General": {"Settings": {"Missing": 2}}},
    )

    with pytest.raises(KeyError, match=r"General\.Settings\.Missing"):
        _ = generator.args


def test_args_rejects_plain_override_type_mismatch() -> None:
    generator = _generator(
        task={"Main": {"tasks": {"General": {"groups": ["Settings"]}}}},
        argument={"Settings": {"Count": _arg(1)}, "Storage": _storage_group()},
        override={"General": {"Settings": {"Count": "wrong type"}}},
    )

    with pytest.raises(TypeError, match=r"General\.Settings\.Count"):
        _ = generator.args


@pytest.mark.parametrize(
    ("metadata", "error"),
    [
        ({"unknown": True}, ValueError),
        ({"value": "wrong type"}, TypeError),
        ({"option": "not a list"}, TypeError),
        ({"value": 3, "option": [1, 2]}, ValueError),
    ],
)
def test_args_rejects_invalid_dict_override_metadata_or_value(
    metadata: dict[str, DeepValue],
    error: type[Exception],
) -> None:
    generator = _generator(
        task={"Main": {"tasks": {"General": {"groups": ["Settings"]}}}},
        argument={"Settings": {"Count": _arg(1)}, "Storage": _storage_group()},
        override={"General": {"Settings": {"Count": metadata}}},
    )

    with pytest.raises(error, match=r"General\.Settings\.Count"):
        _ = generator.args


def _interval_generator(field: str, value: DeepValue) -> ConfigGenerator:
    return _generator(
        task={"Main": {"tasks": {"Main": {"command": "main", "groups": ["Scheduler"]}}}},
        argument={
            "Scheduler": {
                "Command": _arg("", option=["Main"]),
                "Enable": _arg(value=False, typ="checkbox", option=[True, False]),
                "SuccessInterval": _arg(0),
                "FailureInterval": _arg(120),
            },
            "Storage": _storage_group(),
        },
        override={"Main": {"Scheduler": {field: value}}},
    )


@pytest.mark.parametrize("field", ["SuccessInterval", "FailureInterval"])
@pytest.mark.parametrize("value", [0, 30, "0-0", "30-60"])
def test_args_accepts_non_negative_scheduler_intervals(field: str, value: int | str) -> None:
    args = _interval_generator(field, value).args

    assert deep_get(args, keys=f"Main.Scheduler.{field}.value") == value


@pytest.mark.parametrize("value", [-1, 1.5, True, "30", "60-30", "30-x"])
def test_args_rejects_invalid_scheduler_intervals(value: DeepValue) -> None:
    generator = _interval_generator("SuccessInterval", value)

    with pytest.raises((TypeError, ValueError), match=r"Main\.Scheduler\.SuccessInterval"):
        _ = generator.args


def test_generated_values_preserve_explicit_strings_and_only_parse_datetime() -> None:
    generator = _generator(
        task={},
        argument={
            "Error": {"SmtpUser": _arg("", valuetype="str")},
            "Scheduler": {"NextRun": _arg("2026-07-15 12:30:00", typ="datetime")},
        },
    )

    generated = {
        ".".join(path): value
        for path, _descriptor, value in generator._code_arguments()  # ruff:ignore[private-member-access] - 验证代码生成的值边界。
    }

    assert generated["Error.SmtpUser"] == ""
    assert generated["Scheduler.NextRun"] == datetime(2026, 7, 15, 12, 30)


def test_manual_override_types_prefer_explicit_classvar_annotations() -> None:
    fields = {
        name: type_name
        for name, _value, type_name in config_updater._manual_override_fields()  # ruff:ignore[private-member-access] - 验证生成器内部类型源。
    }

    assert fields["COINCIDENT_POINT_ENCOURAGE_DISTANCE"] == "float"
    assert fields["EDGE_LINES_FIND_PEAKS_PARAMETERS"] == "dict[str, FindPeaksParameter]"
    assert fields["INTERNAL_LINES_FIND_PEAKS_PARAMETERS"] == "dict[str, FindPeaksParameter]"
    assert fields["MAP_ENEMY_GENRE_DETECTION_SCALING"] == "dict[str, float | tuple[float, ...]]"
    assert fields["HOMO_CORNER_OFFSET_LIST"] == "tuple[tuple[int, int], ...]"


def test_generated_override_annotations_resolve_at_runtime() -> None:
    annotations = get_type_hints(ConfigOverrides)

    assert annotations["EDGE_LINES_FIND_PEAKS_PARAMETERS"] == dict[str, FindPeaksParameter]
    assert annotations["INTERNAL_LINES_FIND_PEAKS_PARAMETERS"] == dict[str, FindPeaksParameter]


def test_build_template_has_no_campaign_name_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    args = {
        "Event": {"Campaign": {"Name": _arg("12-4")}},
        "Coalition": {"Campaign": {"Name": _arg("7-2")}},
        "Alas": {"Error": {"SmtpUser": _arg("", valuetype="str")}},
    }
    monkeypatch.setattr(config_updater, "read_file", lambda _path: args)

    template = build_template()

    assert deep_get(template, keys="Event.Campaign.Name") == "12-4"
    assert deep_get(template, keys="Coalition.Campaign.Name") == "7-2"
    assert deep_get(template, keys="Alas.Error.SmtpUser") == ""


def test_personal_argument_schema_owns_adb_path_and_has_no_inactive_queue_options() -> None:
    arguments = ConfigGenerator().argument

    assert deep_get(arguments, keys="Emulator.AdbExecutable.value") == (
        "./.venv/Lib/site-packages/adbutils/binaries/adb.exe"
    )
    assert not deep_exist(arguments, keys="Optimization.TaskHoardingDuration")
    assert not deep_exist(arguments, keys="Optimization.WhenTaskQueueEmpty")


def test_latest_activity_manifests_drive_generated_defaults() -> None:
    generator = ConfigGenerator()

    generator.insert_event()

    assert deep_get(generator.args, keys="Event.Campaign.Event.value") == "event_20260625_cn"
    assert deep_get(generator.args, keys="Event.Campaign.Name.value") == "t3"
    assert deep_get(generator.args, keys="Event2.Campaign.Name.value") == "ht3"
    assert deep_get(generator.args, keys="EventSp.Campaign.Name.value") == "sp"
    assert deep_get(generator.args, keys="EventA.EventDaily.StageFilter.value") == "t1 > t2 > t3"
    assert deep_get(generator.args, keys="EventD.EventDaily.StageFilter.value") == "ht1 > ht2 > ht3"
    assert deep_get(generator.args, keys="Raid.Campaign.Event.value") == "raid_20260212"
    assert deep_get(generator.args, keys="Raid.Raid.Mode.value") == "hard"
    assert deep_get(generator.args, keys="RaidDaily.RaidDaily.StageFilter.value") == "hard > normal > easy"
    assert deep_get(generator.args, keys="Coalition.Campaign.Event.value") == "coalition_20260122"
    assert deep_get(generator.args, keys="Coalition.Coalition.Mode.option") == ["easy", "normal", "hard", "ex"]
    assert deep_get(generator.args, keys="Coalition.Coalition.Mode.value") == "hard"
    assert deep_get(generator.args, keys="Coalition.Coalition.Fleet.value") == "single"
    assert deep_get(generator.args, keys="CoalitionSp.Coalition.Mode.value") == "sp"
    assert deep_get(generator.args, keys="CoalitionSp.Coalition.Mode.option") == ["sp"]
    assert deep_get(generator.args, keys="CoalitionSp.Coalition.Fleet.value") == "multi"
    assert deep_get(generator.args, keys="WarArchives.Campaign.Name.value") == "t3"
