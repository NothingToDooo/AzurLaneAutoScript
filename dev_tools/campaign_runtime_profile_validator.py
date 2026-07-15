"""显式验证全部 Campaign 内容与生产运行时契约。"""

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from module.adapters.campaign_profiles import validate_mumu12_campaign_runtime_profiles
from module.content.campaign_session_source import CompiledCampaignSessionSource
from module.content.catalog import ContentCatalog
from module.content.manifest import load_event_manifests
from module.content.runtime_profile_catalog import (
    compile_campaign_runtime_profile_registry,
)
from module.content.stage_loader import StageSpecLoader

if TYPE_CHECKING:
    from collections.abc import Iterable


def validate_campaign_content(root: Path) -> None:
    """从当前事实源验证每个 stage、profile 和 production executor。"""

    if not isinstance(root, Path):
        message = "runtime profile validation root must be a Path"
        raise TypeError(message)
    legacy_sources = tuple(sorted((root / "campaign").rglob("*.py")))
    if legacy_sources:
        message = f"legacy campaign Python source still exists: {legacy_sources[0].relative_to(root)}"
        raise ValueError(message)

    content_root = root / "content" / "events"
    catalog = ContentCatalog(load_event_manifests(content_root))
    registry = compile_campaign_runtime_profile_registry(root / "content" / "campaign-runtime-profiles.json")
    validate_mumu12_campaign_runtime_profiles(catalog.stages, registry)
    CompiledCampaignSessionSource(
        catalog,
        StageSpecLoader(content_root, runtime_profile_registry=registry),
    ).validate_all()


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
    )
    return parser


def main(argv: Iterable[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    validate_campaign_content(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
