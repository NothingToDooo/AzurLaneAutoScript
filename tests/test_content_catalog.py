from collections.abc import Iterable
from typing import TYPE_CHECKING, cast, get_type_hints

import pytest

from module.content import (
    CampaignPolicy,
    ContentCatalog,
    ContentCatalogError,
    ContentId,
    EventPack,
    StageProgressionRule,
    StageRef,
    StageSpec,
    UnknownPackError,
    UnknownStageError,
)
from module.content.manifest import load_default_event_manifests

if TYPE_CHECKING:
    from typing import Any


def _set_attribute(instance: object, name: str, value: object) -> None:
    setattr(instance, name, value)


def _stage(pack_id: str, stage_id: str) -> StageSpec:
    return StageSpec(
        ref=StageRef(pack_id=pack_id, stage_id=stage_id),
        source=f"campaign.{pack_id}.{stage_id}",
    )


def _pack(pack_id: str, *stage_ids: str) -> EventPack:
    return EventPack(
        pack_id=ContentId(pack_id),
        stages=tuple(_stage(pack_id, stage_id) for stage_id in stage_ids),
    )


def test_catalog_preserves_explicit_pack_order_and_resolves_stages() -> None:
    first = _pack("event_first", "t2", "t1")
    second = _pack("event_second", "sp")

    catalog = ContentCatalog(pack for pack in (first, second))

    assert catalog.packs == (first, second)
    assert catalog.get_pack("event_first") is first
    assert catalog.has_stage(StageRef("event_first", "t1"))
    assert catalog.resolve_stage(StageRef("event_first", "t1")) is first.stages[1]


def test_catalog_pack_view_cannot_be_rebound() -> None:
    catalog = ContentCatalog((_pack("event_first", "t1"),))

    with pytest.raises(AttributeError):
        _set_attribute(catalog, "packs", ())

    assert catalog.get_pack("event_first") is catalog.packs[0]


def test_catalog_public_annotations_are_runtime_resolvable() -> None:
    init_hints = get_type_hints(ContentCatalog.__init__)
    stages_hints = get_type_hints(ContentCatalog.__dict__["stages"].fget)
    get_pack_hints = get_type_hints(ContentCatalog.get_pack)
    has_stage_hints = get_type_hints(ContentCatalog.has_stage)
    resolve_stage_hints = get_type_hints(ContentCatalog.resolve_stage)

    assert init_hints["packs"] == Iterable[EventPack]
    assert stages_hints["return"] == tuple[StageSpec, ...]
    assert get_pack_hints["return"] is EventPack
    assert has_stage_hints == {"ref": StageRef, "return": bool}
    assert resolve_stage_hints == {"ref": StageRef, "return": StageSpec}


def test_catalog_rejects_objects_outside_content_model_contracts() -> None:
    invalid_pack = cast("Any", object())
    catalog = ContentCatalog((_pack("event_known", "t1"),))

    with pytest.raises(TypeError, match="EventPack"):
        ContentCatalog((invalid_pack,))
    with pytest.raises(TypeError, match="StageRef"):
        catalog.resolve_stage(cast("Any", object()))


def test_catalog_rejects_duplicate_pack_ids() -> None:
    with pytest.raises(ContentCatalogError, match=r"duplicate pack.*event_same"):
        ContentCatalog((_pack("event_same", "t1"), _pack("event_same", "t2")))


def test_catalog_rejects_duplicate_stage_ids_within_pack() -> None:
    duplicate_stage_pack = EventPack(
        pack_id=ContentId("event_same"),
        stages=(_stage("event_same", "t1"), _stage("event_same", "t1")),
    )

    with pytest.raises(ContentCatalogError, match=r"duplicate stage.*event_same.*t1"):
        ContentCatalog((duplicate_stage_pack,))


def test_catalog_rejects_stage_owned_by_another_pack() -> None:
    mismatched_pack = EventPack(
        pack_id=ContentId("event_owner"),
        stages=(_stage("event_other", "t1"),),
    )

    with pytest.raises(ContentCatalogError, match=r"event_other.*event_owner"):
        ContentCatalog((mismatched_pack,))


def test_catalog_reports_unknown_pack() -> None:
    catalog = ContentCatalog((_pack("event_known", "t1"),))

    with pytest.raises(UnknownPackError, match="event_missing"):
        catalog.get_pack("event_missing")


def test_catalog_distinguishes_unknown_stage_from_unknown_pack() -> None:
    catalog = ContentCatalog((_pack("event_known", "t1"),))

    with pytest.raises(UnknownStageError, match=r"event_known.*t2"):
        catalog.resolve_stage(StageRef("event_known", "t2"))

    with pytest.raises(UnknownPackError, match="event_missing"):
        catalog.resolve_stage(StageRef("event_missing", "t1"))


def test_catalog_stage_presence_is_alias_aware_and_total_for_unknown_content() -> None:
    pack = EventPack(
        pack_id=ContentId("event_known"),
        stages=(_stage("event_known", "t1"),),
        policy=CampaignPolicy(aliases=(("first", "t1"),)),
    )
    catalog = ContentCatalog((pack,))

    assert catalog.has_stage(StageRef("event_known", "first"))
    assert not catalog.has_stage(StageRef("event_known", "missing"))
    assert not catalog.has_stage(StageRef("event_missing", "t1"))
    with pytest.raises(TypeError, match="StageRef"):
        catalog.has_stage(cast("Any", object()))


def test_default_catalog_resolves_main_campaign_configuration_aliases() -> None:
    catalog = ContentCatalog(load_default_event_manifests())

    spec = catalog.resolve_stage(StageRef("campaign_main", "campaign_10_1"))

    assert spec.ref == StageRef("campaign_main", "10-1")


def test_catalog_resolves_alias_before_selecting_the_next_progression_stage() -> None:
    pack = EventPack(
        pack_id=ContentId("event_known"),
        stages=tuple(_stage("event_known", stage) for stage in ("t1", "t2", "t3")),
        policy=CampaignPolicy(
            aliases=(("first", "t1"),),
            progressions=(
                StageProgressionRule("t1", "t2"),
                StageProgressionRule("t2", "t3"),
                StageProgressionRule("t3", None),
            ),
        ),
    )
    catalog = ContentCatalog((pack,))

    assert catalog.next_ref(StageRef("event_known", "first")) == StageRef("event_known", "t2")
    assert catalog.next_ref(StageRef("event_known", "t2")) == StageRef("event_known", "t3")
    assert catalog.next_ref(StageRef("event_known", "t3")) is None


def test_default_catalog_preserves_main_and_event_progression_contracts() -> None:
    catalog = ContentCatalog(load_default_event_manifests())

    assert catalog.next_ref(StageRef("campaign_main", "campaign_10_1")) == StageRef(
        "campaign_main",
        "10-2",
    )
    assert catalog.next_ref(StageRef("event_20200917_cn", "t4")) == StageRef(
        "event_20200917_cn",
        "ts2",
    )
    assert catalog.next_ref(StageRef("event_20200917_cn", "t6")) is None
    assert catalog.next_ref(StageRef("war_archives_20190911_cn", "a1")) == StageRef(
        "war_archives_20190911_cn",
        "a2",
    )
    assert catalog.next_ref(StageRef("war_archives_20190911_cn", "as1")) == StageRef(
        "war_archives_20190911_cn",
        "a2",
    )
    assert catalog.next_ref(StageRef("war_archives_20210325_cn", "bs1")) == StageRef(
        "war_archives_20210325_cn",
        "b2",
    )
    assert catalog.next_ref(StageRef("war_archives_20211229_cn", "bs1")) == StageRef(
        "war_archives_20211229_cn",
        "b3",
    )
