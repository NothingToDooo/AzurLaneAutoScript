from module.config.config_updater import ConfigUpdater


def test_drop_record_upload_options_migrate_to_local_recording() -> None:
    updated = ConfigUpdater().config_update(
        {
            "Alas": {
                "DropRecord": {
                    "ResearchRecord": "save_and_upload",
                    "CommissionRecord": "upload",
                }
            }
        }
    )

    drop_record = updated["Alas"]["DropRecord"]
    assert drop_record["ResearchRecord"] == "save"
    assert drop_record["CommissionRecord"] == "do_not"
    assert "AzurStatsID" not in drop_record
    assert "API" not in drop_record
