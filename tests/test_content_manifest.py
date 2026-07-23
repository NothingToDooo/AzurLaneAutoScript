from datetime import date
from pathlib import Path
from typing import TYPE_CHECKING

from module.config import config_updater as config_updater_module
from module.config.config_updater import ConfigGenerator
from module.content.manifest import load_default_event_manifests, render_campaign_readme
from module.content.models import ContentId, EventPack, EventRelease

if TYPE_CHECKING:
    import pytest


def test_real_manifests_preserve_all_readme_releases_and_kinds() -> None:
    packs = load_default_event_manifests()

    assert len(packs) == 134
    assert sum(len(pack.releases) for pack in packs) == 270
    assert sum(pack.kind == "campaign" for pack in packs) == 2
    assert sum(pack.kind == "war_archives" for pack in packs) == 48
    assert sum(pack.kind == "event" for pack in packs) == 68
    assert sum(pack.kind == "raid" for pack in packs) == 11
    assert sum(pack.kind == "coalition" for pack in packs) == 5
    assert sum(len(pack.releases) > 1 for pack in packs) == 77


def test_20260625_manifest_registers_only_declarative_native_stages() -> None:
    packs = load_default_event_manifests()
    pack = next(pack for pack in packs if str(pack.pack_id) == "event_20260625_cn")

    assert tuple(stage.ref.stage_id for stage in pack.stages) == ("ht1", "ht2", "ht3", "sp", "t1", "t2", "t3")
    assert all(stage.source == f"stages/{stage.ref.stage_id}.yaml" for stage in pack.stages)


def test_readme_renderer_matches_checked_in_output() -> None:
    packs = load_default_event_manifests()

    assert render_campaign_readme(packs) == Path("campaign/Readme.md").read_text(encoding="utf-8")


def test_config_generator_writes_readme_through_atomic_boundary(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    writes: list[tuple[Path, str]] = []
    pack = EventPack(
        pack_id=ContentId("event_demo"),
        releases=(EventRelease(date(2026, 1, 1), "演示活动", 10),),
    )
    monkeypatch.setattr(
        config_updater_module,
        "atomic_write",
        lambda path, rendered: writes.append((Path(path), rendered)),
    )

    ConfigGenerator.write_campaign_readme((pack,))

    assert writes == [
        (
            config_updater_module.PROJECT_ROOT / "campaign" / "Readme.md",
            render_campaign_readme((pack,)),
        )
    ]
