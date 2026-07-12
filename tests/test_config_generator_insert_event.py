from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING, override

from module.config.config_updater import ConfigGenerator
from module.config.deep import deep_get
from module.config.utils import filepath_args, read_file
from module.content.manifest import load_event_manifests
from module.content.models import ContentId, EventPack, EventRelease

if TYPE_CHECKING:
    from module.config.deep import MutableDeepData


class _Generator(ConfigGenerator):
    def __init__(self, packs: list[EventPack]) -> None:
        self._args: MutableDeepData = {}
        self._event_packs = tuple(packs)

    @property
    @override
    def args(self) -> MutableDeepData:
        return self._args

    @property
    @override
    def event_packs(self) -> tuple[EventPack, ...]:
        return self._event_packs


def _release(opened_on: str, order: int, name_cn: str | None = "活动") -> EventRelease:
    return EventRelease(date.fromisoformat(opened_on), name_cn, order)


def _pack(pack_id: str, kind: str, *releases: EventRelease) -> EventPack:
    return EventPack(
        pack_id=ContentId(pack_id),
        kind=kind,
        ui_profile="legacy_python",
        releases=releases,
    )


def _generator(packs: list[EventPack]) -> _Generator:
    return _Generator(packs)


def _option_names(generator: ConfigGenerator, task: str) -> list[str]:
    return deep_get(generator.args, keys=f"{task}.Campaign.Event.option", default=[])


def _bold_option_names(generator: ConfigGenerator, task: str) -> list[str]:
    return deep_get(generator.args, keys=f"{task}.Campaign.Event.option_bold", default=[])


def test_insert_event_adds_latest_regular_event_to_event_and_gems_tasks() -> None:
    generator = _generator(
        [
            _pack("event_old", "event", _release("2025-01-01", 10)),
            _pack("event_latest", "event", _release("2026-01-01", 20)),
        ]
    )

    generator.insert_event()

    assert _option_names(generator, "Event") == ["event_latest"]
    assert _option_names(generator, "GemsFarming") == ["event_latest"]
    assert _bold_option_names(generator, "Event") == ["event_latest"]


def test_insert_event_keeps_only_latest_raid_and_coalition_events() -> None:
    generator = _generator(
        [
            _pack("raid_old", "raid", _release("2025-01-01", 10)),
            _pack("raid_latest", "raid", _release("2026-01-01", 20)),
            _pack("coalition_old", "coalition", _release("2025-02-01", 30)),
            _pack("coalition_latest", "coalition", _release("2026-02-01", 40)),
        ]
    )

    generator.insert_event()

    assert _option_names(generator, "Raid") == ["raid_latest"]
    assert _option_names(generator, "RaidDaily") == ["raid_latest"]
    assert _option_names(generator, "Coalition") == ["coalition_latest"]
    assert _option_names(generator, "CoalitionSp") == ["coalition_latest"]


def test_insert_event_adds_all_war_archives_in_latest_release_order_without_bold() -> None:
    generator = _generator(
        [
            _pack("war_archives_old", "war_archives", _release("2025-01-01", 10)),
            _pack(
                "war_archives_latest",
                "war_archives",
                _release("2024-01-01", 20),
                _release("2026-01-01", 30),
            ),
        ]
    )

    generator.insert_event()

    assert _option_names(generator, "WarArchives") == ["war_archives_latest", "war_archives_old"]
    assert deep_get(generator.args, keys="WarArchives.Campaign.Event.option_bold") is None


def test_insert_event_latest_selection_ignores_unnamed_release() -> None:
    generator = _generator(
        [
            _pack("event_named", "event", _release("2026-01-01", 10)),
            _pack("event_unreleased", "event", _release("2027-01-01", 20, None)),
        ]
    )

    generator.insert_event()

    assert _option_names(generator, "Event") == ["event_named"]


def test_insert_event_same_date_uses_descending_release_order_and_deduplicates_pack() -> None:
    packs = [
        _pack(
            "event_reopened",
            "event",
            _release("2026-01-01", 20),
            _release("2026-01-01", 40),
        ),
        _pack("event_other", "event", _release("2026-01-01", 30)),
    ]
    generator = _generator(list(reversed(packs)))

    generator.insert_event()

    assert _option_names(generator, "Event") == ["event_reopened", "event_other"]


def test_insert_event_replaces_stale_campaign_main_and_duplicate_options() -> None:
    generator = _generator([_pack("event_latest", "event", _release("2026-01-01", 10))])
    generator.args.update(
        {
            "Event": {
                "Campaign": {
                    "Event": {
                        "option": ["campaign_main", "event_stale", "event_stale"],
                        "option_bold": ["event_stale"],
                    }
                }
            }
        }
    )

    generator.insert_event()

    assert _option_names(generator, "Event") == ["event_latest"]
    assert _bold_option_names(generator, "Event") == ["event_latest"]


def test_real_manifest_options_match_checked_in_args() -> None:
    generator = _generator(list(load_event_manifests(Path("content/events"))))
    generator.insert_event()
    expected = read_file(filepath_args())

    for task in [
        "Event",
        "Event2",
        "EventA",
        "EventB",
        "EventC",
        "EventD",
        "EventSp",
        "GemsFarming",
        "Raid",
        "RaidDaily",
        "Coalition",
        "CoalitionSp",
        "WarArchives",
    ]:
        assert _option_names(generator, task) == deep_get(expected, keys=f"{task}.Campaign.Event.option")
        assert _bold_option_names(generator, task) == deep_get(
            expected,
            keys=f"{task}.Campaign.Event.option_bold",
            default=[],
        )
