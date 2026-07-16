from dataclasses import FrozenInstanceError
from pathlib import Path
from typing import cast

import pytest

from module.content.campaign_policy import CampaignPolicy, StageProgressionRule
from module.content.errors import ContentValidationError
from module.content.models import ContentId, EventPack, EventRelease, StageRef, StageSpec
from module.content.validation import ValidationIssue


def _set_attribute(instance: object, attribute: str, value: object) -> None:
    setattr(instance, attribute, value)


def _event_pack_with_invalid_member(field: str, value: object) -> EventPack:
    if field == "stages":
        return EventPack(pack_id=ContentId("event_pack"), stages=cast("tuple[StageSpec, ...]", value))
    if field == "releases":
        return EventPack(pack_id=ContentId("event_pack"), releases=cast("tuple[EventRelease, ...]", value))
    return EventPack(pack_id=ContentId("event_pack"), policy=cast("CampaignPolicy", value))


@pytest.mark.parametrize("value", ["", " ", "\t\n"])
def test_content_id_rejects_empty_or_whitespace_value(value: str) -> None:
    with pytest.raises(ValueError, match="value"):
        ContentId(value)


@pytest.mark.parametrize(
    ("pack_id", "stage_id"),
    [
        ("", "t1"),
        ("  ", "t1"),
        ("event_20260625_cn", ""),
        ("event_20260625_cn", "\t"),
    ],
)
def test_stage_ref_rejects_empty_pack_or_stage(pack_id: str, stage_id: str) -> None:
    with pytest.raises(ValueError, match=r"pack_id|stage_id"):
        StageRef(pack_id=pack_id, stage_id=stage_id)


def test_event_pack_owns_stage_specs_as_a_tuple_in_declared_order() -> None:
    pack_id = ContentId("event_20260625_cn")
    stage_t2 = StageSpec(ref=StageRef(str(pack_id), "t2"), source="campaign.event_20260625_cn.t2")
    stage_t1 = StageSpec(ref=StageRef(str(pack_id), "t1"), source="campaign.event_20260625_cn.t1")
    stages = [stage_t2, stage_t1]

    pack = EventPack(pack_id=pack_id, stages=cast("tuple[StageSpec, ...]", stages))
    stages.reverse()

    assert pack.stages == (stage_t2, stage_t1)


def test_event_pack_converts_string_pack_id() -> None:
    pack = EventPack(pack_id="event_compatible")

    assert pack.pack_id == ContentId("event_compatible")


@pytest.mark.parametrize("pack_id", [None, 1, Path("event")])
def test_event_pack_rejects_invalid_pack_id_type(pack_id: object) -> None:
    with pytest.raises(TypeError, match="pack_id"):
        EventPack(pack_id=cast("ContentId | str", pack_id))


def test_event_pack_rejects_unknown_kind() -> None:
    with pytest.raises(ContentValidationError, match="kind"):
        EventPack(pack_id=ContentId("event_pack"), kind="unknown")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stages", (object(),)),
        ("releases", (object(),)),
        ("policy", object()),
    ],
)
def test_event_pack_rejects_members_outside_public_contract(field: str, value: object) -> None:
    with pytest.raises(TypeError, match=field):
        _event_pack_with_invalid_member(field, value)


def test_campaign_policy_rejects_duplicate_keys_and_empty_loops() -> None:
    with pytest.raises(ContentValidationError, match="duplicate alias"):
        CampaignPolicy(aliases=(("a1", "t1"), ("a1", "t2")))
    with pytest.raises(ContentValidationError, match="loop stages"):
        CampaignPolicy(loops=(("t", ()),))


def test_campaign_policy_rejects_invalid_or_duplicate_progression_rules() -> None:
    with pytest.raises(TypeError, match="StageProgressionRule"):
        CampaignPolicy(progressions=cast("tuple[StageProgressionRule, ...]", (object(),)))
    with pytest.raises(ContentValidationError, match="unique stages"):
        CampaignPolicy(
            progressions=(
                StageProgressionRule("t1", "t2"),
                StageProgressionRule("t1", "t3"),
            )
        )


def test_campaign_policy_returns_only_the_declared_immediate_successor() -> None:
    policy = CampaignPolicy(
        progressions=(
            StageProgressionRule("t1", "t2"),
            StageProgressionRule("t2", "t3"),
            StageProgressionRule("t3", None),
            StageProgressionRule("sp1", "sp2"),
        )
    )

    assert policy.next_stage("t1") == "t2"
    assert policy.next_stage("t2") == "t3"
    assert policy.next_stage("t3") is None
    assert policy.next_stage("missing") is None


def test_stage_spec_requires_stage_ref() -> None:
    with pytest.raises(TypeError, match="ref"):
        StageSpec(ref=cast("StageRef", "t1"), source="stages/t1.yaml")


@pytest.mark.parametrize(
    "fallbacks",
    [
        (("completionist", "map_3_stars"),),
        (("threat_safe", "completionist"),),
    ],
)
def test_campaign_policy_rejects_unsupported_map_achievement_fallbacks(
    fallbacks: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ContentValidationError, match="MapAchievement"):
        CampaignPolicy(map_achievement_fallbacks=fallbacks)


@pytest.mark.parametrize(
    "fallbacks",
    [
        (("threat_safe", "map_3_stars"), ("threat_safe", "100_percent_clear")),
        (("threat_safe", "map_3_stars"), ("map_3_stars", "100_percent_clear")),
        (("threat_safe", "map_3_stars"), ("map_3_stars", "threat_safe")),
        (("threat_safe", "threat_safe"),),
    ],
)
def test_campaign_policy_rejects_ambiguous_or_multistep_map_achievement_fallbacks(
    fallbacks: tuple[tuple[str, str], ...],
) -> None:
    with pytest.raises(ContentValidationError, match="map_achievement_fallbacks"):
        CampaignPolicy(map_achievement_fallbacks=fallbacks)


def test_content_models_are_immutable() -> None:
    content_id = ContentId("event_20260625_cn")
    issue = ValidationIssue(location="stages.t1", message="source is missing")

    with pytest.raises(FrozenInstanceError):
        _set_attribute(content_id, "value", "changed")
    with pytest.raises(FrozenInstanceError):
        _set_attribute(issue, "message", "changed")
