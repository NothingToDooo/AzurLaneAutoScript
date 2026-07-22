import pytest

from module.adapters.war_archives_profiles import validate_mumu12_war_archives_profiles
from module.content.catalog import ContentCatalog
from module.content.manifest import load_default_event_manifests
from module.content.models import EventPack
from module.content.stage_loader import StageSpecLoader
from module.content.war_archives_profile import WarArchivesDefinition, WarArchivesProfileId
from module.war_archives.profile import WarArchivesClientProfileError


def test_all_war_archives_manifests_resolve_semantic_client_profiles() -> None:
    catalog = ContentCatalog(load_default_event_manifests())

    validate_mumu12_war_archives_profiles(catalog)

    archive_packs = tuple(pack for pack in catalog.packs if pack.kind == "war_archives")
    assert archive_packs

    archive_pack = archive_packs[0]
    stage_definition = StageSpecLoader().load(archive_pack.stages[0])
    assert stage_definition.war_archives == archive_pack.war_archives


def test_war_archives_profile_validation_rejects_unknown_client_profile() -> None:
    catalog = ContentCatalog(
        (
            EventPack(
                "war_archives_future_cn",
                kind="war_archives",
                war_archives=WarArchivesDefinition(WarArchivesProfileId("future_archive")),
            ),
        )
    )

    with pytest.raises(WarArchivesClientProfileError, match=r"unknown=.*future_archive"):
        validate_mumu12_war_archives_profiles(catalog)


def test_war_archives_profile_validation_rejects_client_profile_without_manifest() -> None:
    packs = load_default_event_manifests()
    archive_profile_counts = {
        profile_id: sum(pack.war_archives is not None and pack.war_archives.profile_id == profile_id for pack in packs)
        for profile_id in {pack.war_archives.profile_id for pack in packs if pack.war_archives is not None}
    }
    removed = next(
        pack
        for pack in packs
        if pack.war_archives is not None and archive_profile_counts[pack.war_archives.profile_id] == 1
    )
    catalog = ContentCatalog(pack for pack in packs if pack is not removed)
    removed_definition = removed.war_archives
    assert removed_definition is not None

    with pytest.raises(
        WarArchivesClientProfileError,
        match=rf"unused=.*{removed_definition.profile_id.value}",
    ):
        validate_mumu12_war_archives_profiles(catalog)
