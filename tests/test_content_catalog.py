import pytest

from module.content import (
    ContentCatalog,
    ContentCatalogError,
    ContentId,
    EventPack,
    StageRef,
    StageSpec,
    UnknownPackError,
    UnknownStageError,
)


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
    assert catalog.resolve_stage(StageRef("event_first", "t1")) is first.stages[1]


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
