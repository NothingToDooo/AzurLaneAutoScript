import ast
from pathlib import Path
from types import SimpleNamespace

import pytest

from module.content import (
    LegacyStageContractError,
    LegacyStageModuleAdapter,
    LegacyStageReferenceError,
    LoadedCampaignModule,
    LoadedStage,
    StageRef,
)
from module.map.map_base import CampaignMap

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
CAMPAIGN_ROOT = REPOSITORY_ROOT / "campaign"
LEGACY_HELPER_MODULES = {
    Path("campaign/campaign_hard/campaign_hard.py"),
    Path("campaign/campaign_main/campaign_14_base.py"),
    Path("campaign/campaign_main/campaign_15_base.py"),
    Path("campaign/campaign_main/campaign_16_base_aircraft.py"),
    Path("campaign/campaign_main/campaign_16_base_submarine.py"),
    Path("campaign/campaign_main/campaign_2_base.py"),
    Path("campaign/campaign_main/campaign_3_base.py"),
    Path("campaign/campaign_main/campaign_support_fleet.py"),
    Path("campaign/event_20230525_cn/config_base.py"),
    Path("campaign/war_archives_20230525_cn/config_base.py"),
}


class _Config:
    pass


class _Campaign:
    pass


def _module_with_exports(**overrides: object) -> SimpleNamespace:
    exports: dict[str, object] = {
        "Config": _Config,
        "Campaign": _Campaign,
        "MAP": CampaignMap("TEST"),
    }
    exports.update(overrides)
    return SimpleNamespace(**exports)


def test_adapter_maps_stage_ref_to_legacy_module(monkeypatch: pytest.MonkeyPatch) -> None:
    imported: list[str] = []

    def import_module(name: str) -> SimpleNamespace:
        imported.append(name)
        return _module_with_exports()

    monkeypatch.setattr("module.content.legacy_stage.importlib.import_module", import_module)

    loaded = LegacyStageModuleAdapter().load(StageRef("event_20260625_cn", "t1"))

    assert imported == ["campaign.event_20260625_cn.t1"]
    assert loaded == LoadedStage(_Config, _Campaign, loaded.map)
    assert isinstance(loaded.map, CampaignMap)


@pytest.mark.parametrize(
    "ref",
    [
        StageRef("event.bad", "t1"),
        StageRef("event/bad", "t1"),
        StageRef("event\\bad", "t1"),
        StageRef("event_good", "../t1"),
        StageRef("event_good", "t1/path"),
        StageRef("event_good", "t1\\path"),
    ],
)
def test_adapter_rejects_module_path_escape_before_import(
    ref: StageRef,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def unexpected_import(name: str) -> None:
        pytest.fail(f"不应导入非法模块：{name}")

    monkeypatch.setattr("module.content.legacy_stage.importlib.import_module", unexpected_import)

    with pytest.raises(LegacyStageReferenceError):
        LegacyStageModuleAdapter().load(ref)


def test_adapter_preserves_module_not_found_error() -> None:
    with pytest.raises(ModuleNotFoundError) as exc_info:
        LegacyStageModuleAdapter().load(StageRef("event_missing", "t1"))

    assert exc_info.value.name == "campaign.event_missing"


@pytest.mark.parametrize(
    ("overrides", "missing_or_invalid"),
    [
        ({"Config": object()}, "Config"),
        ({"Campaign": object()}, "Campaign"),
        ({"MAP": object()}, "MAP"),
    ],
)
def test_adapter_rejects_exports_with_wrong_contract(
    overrides: dict[str, object],
    missing_or_invalid: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "module.content.legacy_stage.importlib.import_module",
        lambda _name: _module_with_exports(**overrides),
    )

    with pytest.raises(LegacyStageContractError, match=missing_or_invalid):
        LegacyStageModuleAdapter().load(StageRef("event_test", "t1"))


@pytest.mark.parametrize("missing_export", ["Config", "Campaign", "MAP"])
def test_adapter_rejects_missing_exports(
    missing_export: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = _module_with_exports()
    delattr(module, missing_export)
    monkeypatch.setattr("module.content.legacy_stage.importlib.import_module", lambda _name: module)

    with pytest.raises(LegacyStageContractError, match=missing_export):
        LegacyStageModuleAdapter().load(StageRef("event_test", "t1"))


def test_campaign_helper_contract_does_not_require_map(monkeypatch: pytest.MonkeyPatch) -> None:
    module = _module_with_exports()
    del module.MAP
    monkeypatch.setattr("module.content.legacy_stage.importlib.import_module", lambda _name: module)

    adapter = LegacyStageModuleAdapter()

    assert adapter.load_campaign_helper(StageRef("campaign_hard", "campaign_hard")) == LoadedCampaignModule(
        _Config,
        _Campaign,
    )
    with pytest.raises(LegacyStageContractError, match="MAP"):
        adapter.load(StageRef("campaign_hard", "campaign_hard"))


def test_adapter_loads_representative_real_stage() -> None:
    loaded = LegacyStageModuleAdapter().load(StageRef("event_20260625_cn", "t1"))

    assert loaded.config_class.__name__ == "Config"
    assert loaded.campaign_class.__name__ == "Campaign"
    assert isinstance(loaded.map, CampaignMap)


def test_adapter_loads_real_campaign_hard_helper_without_map() -> None:
    loaded = LegacyStageModuleAdapter().load_campaign_helper(StageRef("campaign_hard", "campaign_hard"))

    assert loaded.config_class.__name__ == "Config"
    assert loaded.campaign_class.__name__ == "Campaign"


def _bound_top_level_names(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, (ast.Import, ast.ImportFrom)):
            names.update(alias.asname or alias.name for alias in node.names)
        elif isinstance(node, ast.Assign):
            names.update(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            names.add(node.target.id)
    return names


def _legacy_stage_paths() -> tuple[Path, ...]:
    paths = []
    for path in sorted(CAMPAIGN_ROOT.glob("*/*.py")):
        relative = path.relative_to(REPOSITORY_ROOT)
        if path.name in {"__init__.py", "campaign_base.py"} or relative in LEGACY_HELPER_MODULES:
            continue
        paths.append(path)
    return tuple(paths)


def test_all_legacy_stage_modules_declare_static_exports() -> None:
    required = {"Config", "Campaign", "MAP"}
    stage_paths = _legacy_stage_paths()
    missing = {}
    for path in stage_paths:
        missing_exports = required - _bound_top_level_names(path)
        if missing_exports:
            missing[str(path.relative_to(REPOSITORY_ROOT))] = sorted(missing_exports)

    assert len(stage_paths) >= 1200
    assert missing == {}
