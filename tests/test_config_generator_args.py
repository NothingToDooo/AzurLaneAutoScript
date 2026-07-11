from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

from module.config.config_updater import ConfigGenerator
from module.config.deep import DeepValue, deep_get

if TYPE_CHECKING:
    from collections.abc import Mapping


def _arg(
    value: DeepValue,
    typ: str = "input",
    *,
    option: list[str] | None = None,
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


def test_args_ignores_invalid_default_and_override_values() -> None:
    generator = _generator(
        task={"Main": {"tasks": {"General": {"groups": ["Settings"]}}}},
        argument={
            "Settings": {
                "Choice": _arg("a", typ="select", option=["a", "b"]),
                "Count": _arg(1),
            },
            "Storage": _storage_group(),
        },
        default={"General": {"Settings": {"Choice": "unknown"}}},
        override={"General": {"Settings": {"Count": "wrong type"}}},
    )

    args = generator.args

    assert deep_get(args, keys="General.Settings.Choice.value") == "a"
    assert deep_get(args, keys="General.Settings.Count.value") == 1
