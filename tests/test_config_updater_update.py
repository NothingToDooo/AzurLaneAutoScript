from __future__ import annotations

from typing import TYPE_CHECKING

from module.config.config_updater import ConfigUpdater
from module.config.deep import deep_get

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.config.deep import DeepValue


def _arg(
    value: DeepValue,
    typ: str = "input",
    *,
    option: list[str] | None = None,
    display: str | None = None,
) -> dict[str, DeepValue]:
    argument: dict[str, DeepValue] = {"value": value, "type": typ}
    if option is not None:
        argument["option"] = option
    if display is not None:
        argument["display"] = display
    return argument


def _make_updater(args: Mapping[str, DeepValue]) -> ConfigUpdater:
    updater = object.__new__(ConfigUpdater)
    vars(updater)["args"] = args
    return updater


def test_config_update_preserves_visible_values_and_resets_hidden_runtime_values() -> None:
    updater = _make_updater(
        {
            "Demo": {
                "Group": {
                    "Visible": _arg(1),
                    "Blank": _arg(2),
                    "Hidden": _arg(3, display="hide"),
                    "StoredHidden": _arg(4, typ="stored", display="hide"),
                    "Locked": _arg(5, typ="lock"),
                }
            }
        }
    )

    updated = updater.config_update(
        {
            "Demo": {
                "Group": {
                    "Visible": "10",
                    "Blank": "",
                    "Hidden": "30",
                    "StoredHidden": "40",
                    "Locked": "50",
                }
            }
        }
    )

    assert deep_get(updated, keys="Demo.Group") == {
        "Visible": 10,
        "Blank": 2,
        "Hidden": 3,
        "StoredHidden": 40,
        "Locked": 5,
    }


def test_config_update_template_uses_defaults() -> None:
    updater = _make_updater({"Demo": {"Group": {"Value": _arg(1)}}})

    updated = updater.config_update({"Demo": {"Group": {"Value": "10"}}}, is_template=True)

    assert deep_get(updated, keys="Demo.Group.Value") == 1


def test_config_update_keeps_old_hazard_leveling_enable_on_new_meowfficer_task() -> None:
    updater = _make_updater(
        {
            "OpsiHazard1Leveling": {"Scheduler": {"Enable": _arg(value=False, typ="checkbox")}},
            "OpsiMeowfficerFarming": {"Scheduler": {"Enable": _arg(value=False, typ="checkbox")}},
        }
    )

    updated = updater.config_update({"OpsiHazard1Leveling": {"Scheduler": {"Enable": True}}})

    assert deep_get(updated, keys="OpsiHazard1Leveling.Scheduler.Enable") is True
    assert deep_get(updated, keys="OpsiMeowfficerFarming.Scheduler.Enable") is True


def test_config_update_refreshes_event_campaign_and_stage_defaults() -> None:
    updater = _make_updater(
        {
            "Event": {
                "Campaign": {
                    "Event": _arg("campaign_main", option=["event_2026"]),
                    "Name": _arg("12-4"),
                }
            },
            "GemsFarming": {
                "Campaign": {
                    "Event": _arg("campaign_main", option=["gems_event"]),
                }
            },
            "Coalition": {
                "Campaign": {
                    "Name": _arg("12-4"),
                }
            },
        }
    )

    updated = updater.config_update(
        {
            "Event": {"Campaign": {"Event": "old_event", "Name": "12-4"}},
            "GemsFarming": {"Campaign": {"Event": "old_event"}},
            "Coalition": {"Campaign": {"Name": "7-2"}},
        }
    )

    assert deep_get(updated, keys="Event.Campaign") == {"Event": "event_2026", "Name": "D3"}
    assert deep_get(updated, keys="GemsFarming.Campaign.Event") == "gems_event"
    assert deep_get(updated, keys="Coalition.Campaign.Name") == "area1-normal"


def test_config_update_keeps_war_archives_away_from_campaign_main_even_for_template() -> None:
    updater = _make_updater(
        {
            "WarArchives": {
                "Campaign": {
                    "Event": _arg("campaign_main", option=["archive_2026"]),
                    "Name": _arg("12-4"),
                }
            }
        }
    )

    updated = updater.config_update({}, is_template=True)

    assert deep_get(updated, keys="WarArchives.Campaign") == {"Event": "archive_2026", "Name": "D3"}
