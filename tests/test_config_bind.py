from __future__ import annotations

import copy
import json
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import pytest

from module.config.config import AzurLaneConfig, name_to_function
from module.config.deep import deep_get
from module.config.resolved import ConfigIssue
from module.os.config import OSConfig

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping

    from module.config.config_generated import ConfigValue
    from module.config.deep import DeepValue
    from module.config.resolved import ResolvedTaskConfig


class _TestConfig(AzurLaneConfig):
    resolved: ResolvedTaskConfig
    Shared_Value: str
    Balancer_Enable: bool
    EventOnly_Value: str
    TaskBOnly_Value: str
    Runtime_First: str
    Runtime_Second: str

    def runtime_overlay(self) -> dict[str, ConfigValue]:
        return self._runtime_overlay_values()


def _config(
    data: Mapping[str, DeepValue],
    overridden: Mapping[str, str] | None = None,
) -> _TestConfig:
    config = object.__new__(_TestConfig)
    vars(config)["data"] = data
    config.bound = {}
    vars(config)["overridden"] = dict(overridden or {})
    config.modified = {}
    config.auto_update = False
    return config


def _runtime_overlay(config: _TestConfig) -> dict[str, ConfigValue]:
    return config.runtime_overlay()


def test_task_bind_chain_adds_event_defaults_in_existing_order() -> None:
    assert AzurLaneConfig.task_bind_chain("Event") == [
        "General",
        "Alas",
        "TaskBalancer",
        "EventGeneral",
        "Event",
    ]


def test_task_bind_chain_adds_opsi_defaults() -> None:
    assert AzurLaneConfig.task_bind_chain("OpsiExplore") == [
        "General",
        "Alas",
        "OpsiGeneral",
        "OpsiExplore",
    ]


def test_task_bind_chain_does_not_modify_callers_list() -> None:
    extra_scopes = ["CallerScope"]

    chain = AzurLaneConfig.task_bind_chain("Event", extra_scopes)

    assert extra_scopes == ["CallerScope"]
    assert chain[-1] == "CallerScope"


def test_bind_uses_first_task_path_for_shared_arguments_and_keeps_specific_arguments() -> None:
    config = _config(
        {
            "General": {"Shared": {"Value": "general"}},
            "Alas": {"Shared": {"Value": "alas"}},
            "TaskBalancer": {"Balancer": {"Enable": True}},
            "EventGeneral": {"EventOnly": {"Value": "event general"}},
            "Event": {
                "Shared": {"Value": "event"},
                "Campaign": {"Name": "D3"},
            },
        }
    )

    config.bind("Event")

    assert config.Shared_Value == "general"
    assert config.bound["Shared_Value"] == "General.Shared.Value"
    assert config.Balancer_Enable is True
    assert config.EventOnly_Value == "event general"
    assert config.Campaign_Name == "D3"
    assert config.bound["Campaign_Name"] == "Event.Campaign.Name"


def test_bind_applies_overridden_arguments_after_binding() -> None:
    config = _config(
        {"General": {"Shared": {"Value": "general"}}},
        overridden={"Shared_Value": "override"},
    )

    config.bind("Alas")

    assert config.Shared_Value == "override"
    assert config.bound["Shared_Value"] == "General.Shared.Value"
    assert config.resolved.fields["Shared_Value"].value == "override"


def test_rebind_removes_previous_task_values_and_reveals_class_default() -> None:
    config = _config(
        {
            "TaskA": {
                "Campaign": {"Name": "D3"},
                "TaskAOnly": {"Value": "old"},
            },
            "TaskB": {"TaskBOnly": {"Value": "new"}},
        }
    )
    config.bind("TaskA")

    config.bind("TaskB")

    assert config.Campaign_Name == "12-4"
    assert not hasattr(config, "TaskAOnly_Value")
    assert config.TaskBOnly_Value == "new"
    assert "Campaign_Name" not in config.bound


def test_failed_bind_keeps_previous_snapshot_bound_paths_and_attributes() -> None:
    config = _config({"TaskA": {"Campaign": {"Name": "D3"}}})
    config.bind("TaskA")
    previous_snapshot = config.resolved
    previous_bound = config.bound.copy()
    config.data = {"TaskB": {"Broken": []}}

    with pytest.raises(TypeError, match="mapping"):
        config.bind("TaskB")

    assert config.resolved is previous_snapshot
    assert config.bound == previous_bound
    assert config.Campaign_Name == "D3"


def test_bound_assignment_records_source_path_and_updates_once() -> None:
    config = _config({"TaskA": {"Campaign": {"Name": "D3"}}})
    config.bind("TaskA")
    calls: list[str] = []
    config.auto_update = True
    vars(config)["update"] = lambda: calls.append("update")

    config.Campaign_Name = "SP"

    assert config.modified == {"TaskA.Campaign.Name": "SP"}
    assert calls == ["update"]


def test_override_keeps_resolved_snapshot_in_sync() -> None:
    config = _config({"General": {"Shared": {"Value": "stored"}}})
    config.bind("Alas")
    vars(config)["is_task_enabled"] = lambda _task: True
    config.args = {}

    config.override(Shared_Value="runtime")

    assert config.Shared_Value == "runtime"
    assert config.resolved.fields["Shared_Value"].value == "runtime"
    assert config.resolved.fields["Shared_Value"].is_override is True


def test_deepcopy_merge_is_runtime_overlay_not_persistent_resolution() -> None:
    config = _config({"TaskA": {"Campaign": {"Name": "D3"}}})
    config.bind("TaskA")
    update_calls: list[str] = []
    config.auto_update = True
    vars(config)["update"] = lambda: update_calls.append("update")

    merged = copy.deepcopy(config).merge(SimpleNamespace(Campaign_Name="SP"))

    assert merged.Campaign_Name == "SP"
    assert merged.resolved.fields["Campaign_Name"].value == "D3"
    assert merged.modified == {}
    assert config.Campaign_Name == "D3"
    assert update_calls == []


def test_runtime_overlay_survives_multiple_force_overrides() -> None:
    config = _config({"TaskA": {"Campaign": {"Name": "D3"}}})
    config.bind("TaskA")
    merged = copy.deepcopy(config).merge(SimpleNamespace(Campaign_Name="SP"))
    vars(merged)["is_task_enabled"] = lambda _task: True
    merged.args = {}

    merged.override(Runtime_First="first")
    merged.override(Runtime_Second="second")

    assert merged.Campaign_Name == "SP"
    assert merged.resolved.fields["Campaign_Name"].value == "D3"
    assert merged.Runtime_First == "first"
    assert merged.Runtime_Second == "second"
    assert _runtime_overlay(merged)["Campaign_Name"] == "SP"
    assert merged.modified == {}


def test_runtime_overlay_survives_update_and_rebind_without_writing() -> None:
    stored = {"TaskA": {"Campaign": {"Name": "D3"}}}
    config = _config(copy.deepcopy(stored))
    config.bind("TaskA")
    config.merge(SimpleNamespace(Campaign_Name="SP"))
    config.config_name = "alas"
    config.task = name_to_function("TaskA")
    issue = ConfigIssue(path="TaskA.Campaign.Name", raw="12-4", resolved="D3", reason="migration")
    vars(config)["read_file_with_issues"] = lambda _name: (copy.deepcopy(stored), (issue,))
    vars(config)["config_override"] = lambda: None
    vars(config)["write_file"] = lambda *_args, **_kwargs: pytest.fail("runtime overlay must not write config")

    config.update()
    config.bind("TaskA")

    assert config.Campaign_Name == "SP"
    assert config.resolved.fields["Campaign_Name"].value == "D3"
    assert config.config_issues == (issue,)
    assert config.modified == {}


def test_runtime_overlay_api_never_mutates_persistent_or_scheduler_state() -> None:
    stored = {
        "TaskA": {"Campaign": {"Name": "D3"}},
        "Research": {"Scheduler": {"Enable": False, "NextRun": "2099-01-01 00:00:00"}},
    }
    config = _config(copy.deepcopy(stored))
    config.bind("TaskA")
    config.modified["Existing.Value"] = "pending"
    modified = config.modified.copy()
    overridden = config.overridden.copy()

    config.apply_runtime_overlay(Campaign_Name="SP")

    assert config.Campaign_Name == "SP"
    assert config.data == stored
    assert config.modified == modified
    assert config.overridden == overridden


def test_replace_runtime_overlay_removes_fields_from_previous_session() -> None:
    config = _config({"TaskA": {"Campaign": {"Name": "D3"}}})
    config.bind("TaskA")
    config.apply_runtime_overlay(Campaign_Name="SP", STORY_OPTION=2)

    config.replace_runtime_overlay(Campaign_Name="HT")

    assert config.Campaign_Name == "HT"
    assert config.STORY_OPTION == 0
    assert _runtime_overlay(config) == {"Campaign_Name": "HT"}


def test_runtime_overlay_rejects_unknown_fields_atomically() -> None:
    config = _config({"TaskA": {"Campaign": {"Name": "D3"}}})
    config.bind("TaskA")
    config.apply_runtime_overlay(Campaign_Name="SP")
    apply_overlay = cast("Callable[..., None]", config.apply_runtime_overlay)

    with pytest.raises(KeyError, match="unknown runtime config field"):
        apply_overlay(Not_A_Config_Field=True)

    assert config.Campaign_Name == "SP"
    assert _runtime_overlay(config) == {"Campaign_Name": "SP"}


def test_force_override_has_priority_over_same_runtime_overlay_field() -> None:
    config = _config({"TaskA": {"Campaign": {"Name": "D3"}}})
    config.bind("TaskA")
    config.merge(SimpleNamespace(Campaign_Name="SP"))
    vars(config)["is_task_enabled"] = lambda _task: True
    config.args = {}

    config.override(Campaign_Name="FORCED")
    config.merge(SimpleNamespace(Campaign_Name="HT"))

    assert config.Campaign_Name == "FORCED"
    assert config.resolved.fields["Campaign_Name"].value == "FORCED"
    assert _runtime_overlay(config)["Campaign_Name"] == "HT"
    assert config.modified == {}


def test_runtime_overlay_is_deepcopy_isolated() -> None:
    config = _config({"TaskA": {"Campaign": {"Name": "D3"}}})
    config.bind("TaskA")
    merged = copy.deepcopy(config).merge(SimpleNamespace(Campaign_Name=["SP"]))

    cloned = copy.deepcopy(merged)
    merged_overlay = _runtime_overlay(merged)
    cloned_overlay = _runtime_overlay(cloned)
    cloned_campaign_name = cloned_overlay["Campaign_Name"]
    assert isinstance(cloned_campaign_name, list)
    cloned_campaign_name.append("clone")

    assert merged.Campaign_Name == ["SP"]
    assert merged_overlay == {"Campaign_Name": ["SP"]}
    assert cloned_overlay == {"Campaign_Name": ["SP", "clone"]}
    assert cloned_overlay is not merged_overlay


def test_cleared_runtime_overlay_does_not_leave_stale_facade_fields() -> None:
    config = _config({"TaskA": {"Campaign": {"Name": "D3"}}})
    config.bind("TaskA")
    config.merge(OSConfig())
    assert config.MAP_HAS_SIREN is True

    _runtime_overlay(config).clear()
    config.bind("TaskA")

    assert config.MAP_HAS_SIREN is False


def test_update_applies_config_override_only_once() -> None:
    config = _config({})
    config.config_name = "alas"
    config.task = name_to_function("Alas")
    calls: list[str] = []
    vars(config)["read_file_with_issues"] = lambda _name: ({}, ())
    vars(config)["config_override"] = lambda: calls.append("override")
    vars(config)["bind"] = lambda _task: calls.append("bind")
    vars(config)["save"] = lambda: calls.append("save")

    config.update()

    assert calls == ["override", "bind", "save"]


def test_snapshot_config_uses_one_document_and_keeps_mutations_in_memory(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = json.loads(Path("config/template.json").read_text(encoding="utf-8"))
    document["Alas"]["Emulator"]["Serial"] = "snapshot-device"

    def fail_file_access(*_args: object, **_kwargs: object) -> None:
        message = "snapshot-backed config must not access configuration files"
        raise AssertionError(message)

    monkeypatch.setattr(AzurLaneConfig, "read_file_with_issues", fail_file_access)
    monkeypatch.setattr(AzurLaneConfig, "write_file", fail_file_access)

    config = AzurLaneConfig.from_snapshot("snapshot-instance", document)
    assert config.Emulator_Serial == "snapshot-device"

    config.Emulator_Serial = "runtime-device"

    assert config.Emulator_Serial == "runtime-device"
    assert deep_get(config.data, keys="Alas.Emulator.Serial") == "runtime-device"
    assert config.modified == {}
