import copy
from types import SimpleNamespace

import pytest

from module.config.config import AzurLaneConfig, name_to_function


def _config(data: dict, overridden: dict | None = None):
    config = object.__new__(AzurLaneConfig)
    config.data = data
    config.bound = {}
    config.overridden = overridden or {}
    config.modified = {}
    config.auto_update = False
    return config


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
    assert config.resolved.Shared_Value == "override"


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
    config.update = lambda: calls.append("update")

    config.Campaign_Name = "SP"

    assert config.modified == {"TaskA.Campaign.Name": "SP"}
    assert calls == ["update"]


def test_override_keeps_resolved_snapshot_in_sync() -> None:
    config = _config({"General": {"Shared": {"Value": "stored"}}})
    config.bind("Alas")
    config.is_task_enabled = lambda _task: True
    config.args = {}

    config.override(Shared_Value="runtime")

    assert config.Shared_Value == "runtime"
    assert config.resolved.Shared_Value == "runtime"
    assert config.resolved.fields["Shared_Value"].is_override is True


def test_deepcopy_merge_is_runtime_overlay_not_persistent_resolution() -> None:
    config = _config({"TaskA": {"Campaign": {"Name": "D3"}}})
    config.bind("TaskA")
    update_calls: list[str] = []
    config.auto_update = True
    config.update = lambda: update_calls.append("update")

    merged = copy.deepcopy(config).merge(SimpleNamespace(Campaign_Name="SP"))

    assert merged.Campaign_Name == "SP"
    assert merged.resolved.Campaign_Name == "D3"
    assert merged.modified == {}
    assert config.Campaign_Name == "D3"
    assert update_calls == []


def test_update_applies_config_override_only_once() -> None:
    config = _config({})
    config.config_name = "alas"
    config.task = name_to_function("Alas")
    calls: list[str] = []
    config.read_file = lambda _name: {}
    config.config_override = lambda: calls.append("override")
    config.bind = lambda _task: calls.append("bind")
    config.save = lambda: calls.append("save")

    config.update()

    assert calls == ["override", "bind", "save"]
