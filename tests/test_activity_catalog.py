from pathlib import Path

import pytest

from module.content.activity_catalog import ActivityCatalog, CoalitionActivity, EventStoryActivity, RaidActivity
from module.content.activity_profile import (
    CoalitionFleetMode,
    CoalitionStageId,
    RaidMode,
)
from module.content.errors import ActivityKindError, UnknownActivityError
from module.content.manifest import load_event_manifests


@pytest.fixture(scope="module")
def catalog() -> ActivityCatalog:
    return ActivityCatalog(load_event_manifests(Path("content/events")))


def test_catalog_resolves_typed_activity_definitions(catalog: ActivityCatalog) -> None:
    event_story = catalog.resolve_event_story("event_20260625_cn")
    raid = catalog.resolve_raid("raid_20260212")
    coalition = catalog.resolve_coalition("coalition_20260122")

    assert isinstance(event_story, EventStoryActivity)
    assert event_story.definition.available
    assert event_story.definition.profile_id is not None
    assert event_story.definition.profile_id.value == "standard"

    assert isinstance(raid, RaidActivity)
    assert raid.definition.profile_id.value == "changwu"
    assert raid.definition.modes == (RaidMode.EASY, RaidMode.NORMAL, RaidMode.HARD, RaidMode.EX)
    assert raid.definition.daily_modes == raid.definition.modes
    assert raid.definition.ticket_modes == (RaidMode.EX,)

    assert isinstance(coalition, CoalitionActivity)
    assert coalition.definition.profile_id.value == "fashion"
    sp = coalition.definition.get_stage(CoalitionStageId("sp"))
    assert sp is not None
    assert sp.battle_count == 4
    assert sp.fleet_rule.allows(CoalitionFleetMode.MULTI)
    assert not sp.fleet_rule.allows(CoalitionFleetMode.SINGLE)


def test_unavailable_event_story_is_declared_without_a_profile(catalog: ActivityCatalog) -> None:
    event_story = catalog.resolve_event_story("event_20260226_cn")

    assert not event_story.definition.available
    assert event_story.definition.profile_id is None


def test_catalog_rejects_unknown_content_and_wrong_activity_kind(catalog: ActivityCatalog) -> None:
    with pytest.raises(UnknownActivityError, match="unknown activity content"):
        catalog.resolve_raid("raid_missing")

    with pytest.raises(ActivityKindError, match="expected raid"):
        catalog.resolve_raid("event_20260625_cn")

    with pytest.raises(ActivityKindError, match="expected coalition"):
        catalog.resolve_coalition("campaign_main")
