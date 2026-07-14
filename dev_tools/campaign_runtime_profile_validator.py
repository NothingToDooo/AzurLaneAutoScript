"""验证已提交的 campaign runtime profile 与生产执行器契约。"""

import argparse
from pathlib import Path
from typing import TYPE_CHECKING

from module.adapters.campaign_profiles import validate_mumu12_campaign_runtime_profiles
from module.content.manifest import load_event_manifests
from module.content.runtime_profile_catalog import (
    compile_campaign_runtime_profile_registry,
)

if TYPE_CHECKING:
    from collections.abc import Iterable


def check_campaign_runtime_profiles(root: Path) -> None:
    """从当前事实源验证每个 stage、profile 和 production executor。"""

    if not isinstance(root, Path):
        message = "runtime profile validation root must be a Path"
        raise TypeError(message)
    legacy_sources = tuple(sorted((root / "campaign").rglob("*.py")))
    if legacy_sources:
        message = f"legacy campaign Python source still exists: {legacy_sources[0].relative_to(root)}"
        raise ValueError(message)

    registry = compile_campaign_runtime_profile_registry(root / "content" / "campaign-runtime-profiles.json")
    stages = tuple(stage for pack in load_event_manifests(root / "content" / "events") for stage in pack.stages)
    validate_mumu12_campaign_runtime_profiles(stages, registry)


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
    check_campaign_runtime_profiles(args.root.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
