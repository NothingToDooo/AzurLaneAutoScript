import importlib
import sys
from types import ModuleType
from typing import TYPE_CHECKING, cast

import pytest

from dev_tools import utils as dev_utils
from module.campaign.campaign_base import CampaignBase
from module.content.errors import ContentValidationError
from module.content.manifest import load_event_manifests
from module.content.models import StageRef, StageSpec
from module.content.stage_loader import StageSpecLoader

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any


def _import_extractor() -> ModuleType:
    return importlib.import_module("dev_tools.map_extractor")


def test_import_does_not_load_external_lua_files(monkeypatch: pytest.MonkeyPatch) -> None:
    sys.modules.pop("dev_tools.map_extractor", None)

    def unexpected_loader(*_args: object, **_kwargs: object) -> None:
        pytest.fail("导入 map_extractor 时不应读取外部 Lua 仓库")

    monkeypatch.setattr(dev_utils, "LuaLoader", unexpected_loader)

    module = _import_extractor()

    assert hasattr(module, "MapData")


def _map_data(monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, Any]:
    module = _import_extractor()
    monkeypatch.setattr(module, "camera_2d", lambda *_args, **_kwargs: [(0, 0)])
    monkeypatch.setattr(module, "camera_spawn_point", lambda *_args, **_kwargs: [(1, 1)])
    map_data_class = module.MapData
    stage = object.__new__(map_data_class)
    stage.chapter_name = "HT2"
    stage.shape = (1, 1)
    stage.map_data = {(0, 0): "--", (1, 0): "++", (0, 1): "SP", (1, 1): "MB"}
    stage.map_data_loop = None
    stage.portal = []
    stage.land_based = []
    stage.spawn_data = [
        {"battle": 0, "enemy": 2, "siren": 1},
        {"battle": 1},
        {"battle": 2},
        {"battle": 3},
        {"battle": 4},
        {"battle": 5},
        {"battle": 6, "boss": 1},
    ]
    stage.spawn_data_loop = None
    stage.MAP_SIREN_TEMPLATE = ["SirenOne"]
    stage.MOVABLE_ENEMY_TURN = {2}
    stage.MAP_HAS_SIREN = True
    stage.MAP_HAS_MOVABLE_ENEMY = True
    stage.MAP_HAS_MAP_STORY = False
    stage.MAP_HAS_FLEET_STEP = True
    stage.MAP_HAS_AMBUSH = False
    stage.MAP_HAS_MYSTERY = False
    stage.MAP_HAS_PORTAL = False
    stage.MAP_HAS_LAND_BASED = False
    stage.STAR_REQUIRE_1 = 1
    stage.STAR_REQUIRE_2 = 0
    stage.STAR_REQUIRE_3 = 3
    stage.data = {"boss_refresh": 6}
    return module, stage


def test_stage_renderer_is_exact_deterministic_and_uses_finite_policies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, stage = _map_data(monkeypatch)
    expected = """schema_version: 1
map:
  name: HT2
  shape: B2
  camera_data:
  - A1
  camera_data_spawn_point:
  - B2
  map_data: |-
    -- ++
    SP MB
  weight_data: |-
    50 50
    50 50
  spawn_data:
  - battle: 0
    enemy: 2
    siren: 1
  - battle: 1
  - battle: 2
  - battle: 3
  - battle: 4
  - battle: 5
  - battle: 6
    boss: 1
config:
  MAP_SIREN_TEMPLATE:
  - SirenOne
  MOVABLE_ENEMY_TURN:
  - 2
  MAP_HAS_SIREN: true
  MAP_HAS_MOVABLE_ENEMY: true
  MAP_HAS_MAP_STORY: false
  MAP_HAS_FLEET_STEP: true
  MAP_HAS_AMBUSH: false
  MAP_HAS_MYSTERY: false
  STAR_REQUIRE_2: 0
enemy_filter: 1L > 1M > 1E > 1C > 2L > 2M > 2E > 2C > 3L > 3M > 3E > 3C
battles:
  0:
    policy: siren_then_filtered_enemy
    preserve: 1
  5:
    policy: siren_then_filtered_enemy
    preserve: 0
  6:
    policy: fleet_boss
"""

    first = stage.render_stage_yaml()
    second = stage.render_stage_yaml()

    assert first == expected
    assert second == expected
    assert "strategy" not in stage.stage_document()


def test_stage_renderer_selects_filtered_policy_when_map_has_no_siren(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, stage = _map_data(monkeypatch)
    stage.MAP_SIREN_TEMPLATE = []

    document = stage.stage_document()

    assert document["battles"][0] == {"policy": "filtered_enemy_then_default", "preserve": 1}
    assert "MAP_HAS_SIREN" not in document["config"]


def test_stage_renderer_keeps_loop_portal_and_land_based_data(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, stage = _map_data(monkeypatch)
    stage.map_data_loop = {(0, 0): "--", (1, 0): "--", (0, 1): "SP", (1, 1): "MB"}
    stage.portal = [("A1", "B2")]
    stage.land_based = [("A1", "right")]
    stage.spawn_data_loop = [{"battle": 0, "boss": 1}]
    stage.MAP_HAS_PORTAL = True
    stage.MAP_HAS_LAND_BASED = True

    document = stage.stage_document()

    assert document["map"]["portal_data"] == [("A1", "B2")]
    assert document["map"]["map_data_loop"] == "-- --\nSP MB"
    assert document["map"]["land_based_data"] == [("A1", "right")]
    assert document["map"]["spawn_data_loop"] == [{"battle": 0, "boss": 1}]
    assert document["config"]["MAP_HAS_PORTAL"] is True
    assert document["config"]["MAP_HAS_LAND_BASED"] is True


def test_stage_writer_owns_only_yaml_and_check_never_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, stage = _map_data(monkeypatch)
    pack_root = tmp_path / "event_future_cn"
    stages_root = pack_root / "stages"
    strategy_path = pack_root / "strategy.py"
    strategy_bytes = b"# hand-written strategy\r\nSENTINEL = True\r\n"
    pack_root.mkdir()
    strategy_path.write_bytes(strategy_bytes)

    assert stage.write_stage(stages_root) is True
    stage_path = stages_root / "ht2.yaml"
    original = stage_path.read_bytes()
    assert b"\r\n" not in original
    assert strategy_path.read_bytes() == strategy_bytes

    stage_path.write_text("manual\n", encoding="utf-8", newline="\n")
    assert stage.write_stage(stages_root) is False
    assert stage_path.read_text(encoding="utf-8") == "manual\n"
    assert strategy_path.read_bytes() == strategy_bytes

    assert stage.write_stage(stages_root, overwrite=True) is True
    assert stage_path.read_bytes() == original
    before_mtime = stage_path.stat().st_mtime_ns
    assert stage.write_stage(stages_root, check=True) is True
    assert stage_path.stat().st_mtime_ns == before_mtime

    stage.MAP_HAS_AMBUSH = True
    assert stage.write_stage(stages_root, check=True) is False
    assert stage_path.stat().st_mtime_ns == before_mtime
    assert strategy_path.read_bytes() == strategy_bytes


def test_stage_writer_never_creates_strategy_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _module, stage = _map_data(monkeypatch)
    stages_root = tmp_path / "event_future_cn" / "stages"

    stage.write_stage(stages_root, overwrite=True)

    assert not (stages_root.parent / "strategy.py").exists()


def test_generated_stage_yaml_is_accepted_by_native_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, stage = _map_data(monkeypatch)
    events_root = tmp_path / "events"
    stages_root = events_root / "event_future_cn" / "stages"
    stage.write_stage(stages_root)
    spec = StageSpec(StageRef("event_future_cn", "ht2"), "stages/ht2.yaml")

    loaded = StageSpecLoader(content_root=events_root, campaign_root=tmp_path / "campaign").load(spec)

    assert loaded.map.name == "HT2"
    assert loaded.map.spawn_data[-1] == {"battle": 6, "boss": 1}
    assert vars(loaded.config_class)["MAP_SIREN_TEMPLATE"] == ("SirenOne",)


def _make_early_boss(stage) -> None:
    stage.chapter_name = "T1"
    stage.data["boss_refresh"] = 4
    stage.spawn_data = [
        {"battle": 0, "enemy": 2},
        {"battle": 1},
        {"battle": 2},
        {"battle": 3},
        {"battle": 4, "boss": 1},
    ]


def test_early_boss_generation_requires_explicit_pack_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, stage = _map_data(monkeypatch)
    _make_early_boss(stage)
    stages_root = tmp_path / "event_early_cn" / "stages"

    with pytest.raises(ContentValidationError, match=r"boss_refresh.*4.*strategy"):
        stage.stage_document()
    with pytest.raises(ContentValidationError, match=r"boss_refresh.*4.*strategy"):
        stage.render_stage_yaml()
    with pytest.raises(ContentValidationError, match=r"boss_refresh.*4.*strategy"):
        stage.write_stage(stages_root)

    assert not (stages_root / "t1.yaml").exists()
    assert not (stages_root.parent / "strategy.py").exists()


class _EarlyBossStrategy(CampaignBase):
    def battle_4(self):
        return self.clear_boss()


class _ClearBossCampaign:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def clear_boss(self) -> str:
        self.calls.append("clear_boss")
        return "boss"


def test_early_boss_generation_uses_manifest_pack_strategy_without_touching_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, stage = _map_data(monkeypatch)
    _make_early_boss(stage)
    repository_root = tmp_path
    events_root = repository_root / "content" / "events"
    pack_id = "event_early_cn"
    stages_root = events_root / pack_id / "stages"
    stages_root.mkdir(parents=True)
    stage_path = stages_root / "t1.yaml"
    stage_path.write_text("placeholder: true\n", encoding="utf-8", newline="\n")
    strategy_path = repository_root / "campaign" / pack_id / "strategy.py"
    strategy_path.parent.mkdir(parents=True)
    strategy_bytes = b"# hand-written early boss strategy\n"
    strategy_path.write_bytes(strategy_bytes)
    manifest = events_root / f"{pack_id}.yaml"
    manifest.write_text(
        """schema_version: 1
id: event_early_cn
kind: event
ui_profile: legacy_python
releases:
- opened_on: '2026-01-01'
  name_cn: 早期Boss测试
  order: 1
stages:
- id: t1
  source: stages/t1.yaml
  strategy: campaign.event_early_cn.strategy:EarlyBossStrategy
""",
        encoding="utf-8",
        newline="\n",
    )
    (pack,) = load_event_manifests(events_root)
    spec = pack.stages[0]

    assert stage.write_stage(stages_root, overwrite=True, strategy=spec.strategy) is True
    assert strategy_path.read_bytes() == strategy_bytes
    module = ModuleType(f"campaign.{pack_id}.strategy")
    module.__file__ = str(strategy_path)
    module.__dict__["EarlyBossStrategy"] = _EarlyBossStrategy
    monkeypatch.setattr("module.content.stage_loader.importlib.import_module", lambda _name: module)

    loaded = StageSpecLoader(content_root=events_root, campaign_root=repository_root / "campaign").load(spec)
    campaign = _ClearBossCampaign()

    assert cast("Any", loaded.campaign_class).battle_4(campaign) == "boss"
    assert campaign.calls == ["clear_boss"]
    assert strategy_path.read_bytes() == strategy_bytes


def test_extractor_unknown_grid_sentinel_is_rejected_by_native_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _module, stage = _map_data(monkeypatch)
    stage.map_data[(1, 1)] = "??"
    events_root = tmp_path / "events"
    stages_root = events_root / "event_future_cn" / "stages"
    stage.write_stage(stages_root)
    spec = StageSpec(StageRef("event_future_cn", "ht2"), "stages/ht2.yaml")

    with pytest.raises(ContentValidationError, match=r"map\.map_data:.*unknown.*\?\?"):
        StageSpecLoader(content_root=events_root, campaign_root=tmp_path / "campaign").load(spec)
