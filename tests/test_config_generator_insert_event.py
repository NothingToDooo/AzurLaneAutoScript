from module.config.config_updater import ConfigGenerator, Event
from module.config.deep import deep_get


def _event(date: str, directory: str, name: str = "活动") -> Event:
    return Event(f"| {date} | {directory} | {name} |")


def _generator(events: list[Event]):
    generator = object.__new__(ConfigGenerator)
    generator.args = {}
    generator.event = events
    return generator


def _option_names(generator: ConfigGenerator, task: str) -> list[str]:
    return [str(option) for option in deep_get(generator.args, keys=f"{task}.Campaign.Event.option", default=[])]


def _bold_option_names(generator: ConfigGenerator, task: str) -> list[str]:
    return [str(option) for option in deep_get(generator.args, keys=f"{task}.Campaign.Event.option_bold", default=[])]


def test_insert_event_adds_latest_regular_event_to_event_and_gems_tasks() -> None:
    generator = _generator(
        [
            _event("20260101", "event_latest"),
            _event("20250101", "event_old"),
        ]
    )

    generator.insert_event()

    assert _option_names(generator, "Event") == ["event_latest"]
    assert _option_names(generator, "GemsFarming") == ["event_latest"]
    assert _bold_option_names(generator, "Event") == ["event_latest"]


def test_insert_event_keeps_only_latest_raid_and_coalition_events() -> None:
    generator = _generator(
        [
            _event("20260101", "raid_latest"),
            _event("20250101", "raid_old"),
            _event("20260201", "coalition_latest"),
            _event("20250201", "coalition_old"),
        ]
    )

    generator.insert_event()

    assert _option_names(generator, "Raid") == ["raid_latest"]
    assert _option_names(generator, "RaidDaily") == ["raid_latest"]
    assert _option_names(generator, "Coalition") == ["coalition_latest"]
    assert _option_names(generator, "CoalitionSp") == ["coalition_latest"]


def test_insert_event_adds_all_war_archives_without_bold_options() -> None:
    generator = _generator(
        [
            _event("20260101", "war_archives_latest"),
            _event("20250101", "war_archives_old"),
        ]
    )

    generator.insert_event()

    assert _option_names(generator, "WarArchives") == ["war_archives_latest", "war_archives_old"]
    assert deep_get(generator.args, keys="WarArchives.Campaign.Event.option_bold") is None


def test_insert_event_removes_campaign_main_and_duplicate_options() -> None:
    duplicate = _event("20260101", "event_latest")
    generator = _generator([duplicate])
    generator.args = {
        "Event": {
            "Campaign": {
                "Event": {
                    "option": [
                        "campaign_main",
                        duplicate,
                    ]
                }
            }
        }
    }

    generator.insert_event()

    assert _option_names(generator, "Event") == ["event_latest"]
