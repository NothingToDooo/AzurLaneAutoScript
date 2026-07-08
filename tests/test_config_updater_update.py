from module.config.config_updater import ConfigUpdater


def _arg(value, typ: str = "input", **kwargs):
    return {"value": value, "type": typ, **kwargs}


def _make_updater(args: dict):
    updater = object.__new__(ConfigUpdater)
    updater.args = args
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

    assert updated["Demo"]["Group"] == {
        "Visible": 10,
        "Blank": 2,
        "Hidden": 3,
        "StoredHidden": 40,
        "Locked": 5,
    }


def test_config_update_template_uses_defaults() -> None:
    updater = _make_updater({"Demo": {"Group": {"Value": _arg(1)}}})

    updated = updater.config_update({"Demo": {"Group": {"Value": "10"}}}, is_template=True)

    assert updated["Demo"]["Group"]["Value"] == 1


def test_config_update_keeps_old_hazard_leveling_enable_on_new_meowfficer_task() -> None:
    updater = _make_updater(
        {
            "OpsiHazard1Leveling": {"Scheduler": {"Enable": _arg(value=False, typ="checkbox")}},
            "OpsiMeowfficerFarming": {"Scheduler": {"Enable": _arg(value=False, typ="checkbox")}},
        }
    )

    updated = updater.config_update({"OpsiHazard1Leveling": {"Scheduler": {"Enable": True}}})

    assert updated["OpsiHazard1Leveling"]["Scheduler"]["Enable"] is True
    assert updated["OpsiMeowfficerFarming"]["Scheduler"]["Enable"] is True


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

    assert updated["Event"]["Campaign"] == {"Event": "event_2026", "Name": "D3"}
    assert updated["GemsFarming"]["Campaign"]["Event"] == "gems_event"
    assert updated["Coalition"]["Campaign"]["Name"] == "area1-normal"


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

    assert updated["WarArchives"]["Campaign"] == {"Event": "archive_2026", "Name": "D3"}
