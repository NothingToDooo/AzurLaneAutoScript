from module.config.config import AzurLaneConfig


def _config(data: dict, overridden: dict | None = None):
    config = object.__new__(AzurLaneConfig)
    config.data = data
    config.bound = {}
    config.overridden = overridden or {}
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
