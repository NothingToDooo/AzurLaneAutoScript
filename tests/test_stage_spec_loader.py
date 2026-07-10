import inspect
import textwrap
from pathlib import Path
from types import ModuleType
from typing import TYPE_CHECKING, cast

import pytest

from module.campaign.campaign_base import CampaignBase
from module.content.errors import ContentValidationError
from module.content.legacy_stage import LegacyStageModuleAdapter
from module.content.models import StageRef, StageSpec
from module.content.stage_loader import StageSpecLoader, load_default_stage

if TYPE_CHECKING:
    from typing import Any

PACK_ID = "event_20260625_cn"
ENEMY_FILTER = "1L > 1M > 1E > 1C > 2L > 2M > 2E > 2C > 3L > 3M > 3E > 3C"


class _BossFleet:
    def __init__(self, calls: list[object], result: object) -> None:
        self.calls = calls
        self.result = result

    def clear_boss(self) -> object:
        self.calls.append("fleet_boss.clear_boss")
        return self.result


class _BattleCampaign:
    ENEMY_FILTER = ENEMY_FILTER

    def __init__(
        self,
        *,
        siren_result: object = False,
        enemy_result: object = False,
        boss_result: object = False,
    ) -> None:
        self.calls: list[object] = []
        self.default_result = object()
        self.siren_result = siren_result
        self.enemy_result = enemy_result
        self.boss_result = boss_result
        self.fleet_boss = _BossFleet(self.calls, boss_result)

    def clear_siren(self) -> object:
        self.calls.append("clear_siren")
        return self.siren_result

    def clear_filter_enemy(self, enemy_filter: str, *, preserve: int) -> object:
        self.calls.append(("clear_filter_enemy", enemy_filter, preserve))
        return self.enemy_result

    def battle_default(self) -> object:
        self.calls.append("battle_default")
        return self.default_result

    def clear_boss(self) -> object:
        self.calls.append("clear_boss")
        return self.boss_result


def _normalized_rows(value: str) -> tuple[str, ...]:
    return tuple(line.strip() for line in value.splitlines() if line.strip())


def _config_values(config_class: type[object]) -> dict[str, object]:
    return {name: value for name, value in vars(config_class).items() if name.isupper()}


def _call_battle(campaign_class: type[CampaignBase], battle: int, campaign: _BattleCampaign) -> object:
    method = getattr(campaign_class, f"battle_{battle}")
    return method(cast("Any", campaign))


@pytest.mark.parametrize("stage_id", ["t1", "t2", "t3", "ht1", "ht2", "ht3", "sp"])
def test_default_loader_resolves_every_20260625_native_stage(stage_id: str) -> None:
    loaded = load_default_stage(StageRef(PACK_ID, stage_id))

    assert loaded.map.name == stage_id.upper()
    assert loaded.config_class.__name__ == "Config"
    assert loaded.campaign_class.__name__ == "Campaign"
    assert loaded.campaign_class.MAP is loaded.map
    assert cast("Any", loaded.campaign_class).ENEMY_FILTER == ENEMY_FILTER


def test_t1_stage_matches_the_pre_migration_map_and_complete_config_snapshot() -> None:
    loaded = load_default_stage(StageRef(PACK_ID, "t1"))

    assert loaded.map.shape == (8, 6)
    assert [str(grid) for grid in loaded.map.camera_data] == ["F2", "F5"]
    assert [str(grid) for grid in loaded.map.camera_data_spawn_point] == ["D5"]
    assert _normalized_rows(loaded.map.map_data)[0] == "-- -- ME -- ME -- -- ++ MB"
    assert loaded.map.spawn_data == [
        {"battle": 0, "enemy": 2, "siren": 1},
        {"battle": 1, "enemy": 2},
        {"battle": 2, "enemy": 1},
        {"battle": 3, "enemy": 1},
        {"battle": 4, "boss": 1},
    ]
    assert _config_values(loaded.config_class) == {
        "MAP_SIREN_TEMPLATE": ("MeowfficerBust_Hobbies",),
        "MOVABLE_ENEMY_TURN": (2,),
        "MAP_HAS_SIREN": True,
        "MAP_HAS_MOVABLE_ENEMY": True,
        "MAP_HAS_MAP_STORY": False,
        "MAP_HAS_FLEET_STEP": True,
        "MAP_HAS_AMBUSH": False,
        "MAP_HAS_MYSTERY": False,
        "MAP_CHAPTER_SWITCH_20241219_SP": True,
        "STAGE_ENTRANCE": ("half", "20240725"),
        "MAP_HAS_MODE_SWITCH": True,
        "MAP_SWIPE_MULTIPLY": (1.144, 1.165),
        "MAP_SWIPE_MULTIPLY_MINITOUCH": (1.106, 1.126),
    }


def test_ht3_stage_keeps_inherited_config_and_battle_preserve_counts() -> None:
    loaded = load_default_stage(StageRef(PACK_ID, "ht3"))

    assert loaded.map.shape == (8, 7)
    assert loaded.map.spawn_data[-2:] == [{"battle": 5}, {"battle": 6, "boss": 1}]
    assert _config_values(loaded.config_class) == {
        "MAP_SIREN_TEMPLATE": ("MeowfficerBust_Studying", "MeowfficerBust_Playtime"),
        "MOVABLE_ENEMY_TURN": (2,),
        "MAP_HAS_SIREN": True,
        "MAP_HAS_MOVABLE_ENEMY": True,
        "MAP_HAS_MAP_STORY": False,
        "MAP_HAS_FLEET_STEP": True,
        "MAP_HAS_AMBUSH": False,
        "MAP_HAS_MYSTERY": False,
        "MAP_CHAPTER_SWITCH_20241219_SP": True,
        "STAGE_ENTRANCE": ("half", "20240725"),
        "MAP_HAS_MODE_SWITCH": True,
        "MAP_SWIPE_MULTIPLY": (1.115, 1.136),
        "MAP_SWIPE_MULTIPLY_MINITOUCH": (1.078, 1.098),
    }

    campaign = _BattleCampaign(boss_result="boss")
    assert _call_battle(loaded.campaign_class, 0, campaign) is campaign.default_result
    assert campaign.calls == [
        "clear_siren",
        ("clear_filter_enemy", ENEMY_FILTER, 1),
        "battle_default",
    ]
    campaign = _BattleCampaign()
    _call_battle(loaded.campaign_class, 5, campaign)
    assert campaign.calls == [
        "clear_siren",
        ("clear_filter_enemy", ENEMY_FILTER, 0),
        "battle_default",
    ]
    campaign = _BattleCampaign(boss_result="boss")
    assert _call_battle(loaded.campaign_class, 6, campaign) == "boss"
    assert campaign.calls == ["fleet_boss.clear_boss"]


def test_sp_stage_keeps_one_time_homography_and_edge_config() -> None:
    loaded = load_default_stage(StageRef(PACK_ID, "sp"))
    config = _config_values(loaded.config_class)

    assert loaded.map.shape == (6, 9)
    assert config["STAR_REQUIRE_1"] == config["STAR_REQUIRE_2"] == config["STAR_REQUIRE_3"] == 0
    assert config["MAP_IS_ONE_TIME_STAGE"] is True
    assert config["HOMO_STORAGE"] == (
        (8, 6),
        ((137.405, 104.804), (1046.044, 104.804), (-12.171, 652.093), (1166.717, 652.093)),
    )
    assert config["MAP_ENSURE_EDGE_INSIGHT_CORNER"] == "bottom"
    assert config == {
        "MAP_SIREN_TEMPLATE": ("MeowfficerBust_Studying", "MeowfficerBust_Playtime"),
        "MOVABLE_ENEMY_TURN": (2,),
        "MAP_HAS_SIREN": True,
        "MAP_HAS_MOVABLE_ENEMY": True,
        "MAP_HAS_MAP_STORY": False,
        "MAP_HAS_FLEET_STEP": False,
        "MAP_HAS_AMBUSH": False,
        "MAP_HAS_MYSTERY": False,
        "STAR_REQUIRE_1": 0,
        "STAR_REQUIRE_2": 0,
        "STAR_REQUIRE_3": 0,
        "MAP_IS_ONE_TIME_STAGE": True,
        "MAP_CHAPTER_SWITCH_20241219_SP": True,
        "STAGE_ENTRANCE": ("half", "20240725"),
        "MAP_HAS_MODE_SWITCH": False,
        "HOMO_STORAGE": (
            (8, 6),
            ((137.405, 104.804), (1046.044, 104.804), (-12.171, 652.093), (1166.717, 652.093)),
        ),
        "MAP_ENSURE_EDGE_INSIGHT_CORNER": "bottom",
        "MAP_SWIPE_MULTIPLY": (1.005, 1.024),
        "MAP_SWIPE_MULTIPLY_MINITOUCH": (0.972, 0.990),
    }

    campaign = _BattleCampaign()
    _call_battle(loaded.campaign_class, 0, campaign)
    assert campaign.calls[1] == ("clear_filter_enemy", ENEMY_FILTER, 2)
    campaign = _BattleCampaign()
    _call_battle(loaded.campaign_class, 5, campaign)
    assert campaign.calls[1] == ("clear_filter_enemy", ENEMY_FILTER, 0)
    campaign = _BattleCampaign(boss_result="boss")
    assert _call_battle(loaded.campaign_class, 7, campaign) == "boss"


def test_t1_pack_strategy_keeps_clear_boss_instead_of_fleet_boss() -> None:
    loaded = load_default_stage(StageRef(PACK_ID, "t1"))
    campaign = _BattleCampaign(boss_result="boss")

    assert _call_battle(loaded.campaign_class, 4, campaign) == "boss"
    assert campaign.calls == ["clear_boss"]


def test_t1_loaded_policy_short_circuits_in_declared_order() -> None:
    loaded = load_default_stage(StageRef(PACK_ID, "t1"))
    campaign = _BattleCampaign(siren_result="siren")

    assert _call_battle(loaded.campaign_class, 0, campaign) is True
    assert campaign.calls == ["clear_siren"]

    campaign = _BattleCampaign(enemy_result="enemy")
    assert _call_battle(loaded.campaign_class, 0, campaign) is True
    assert campaign.calls == [
        "clear_siren",
        ("clear_filter_enemy", ENEMY_FILTER, 0),
    ]


@pytest.mark.parametrize("stage_id", ["t1", "t2", "t3", "ht1", "ht2", "ht3", "sp"])
def test_legacy_python_stage_is_only_a_thin_export_of_native_content(stage_id: str) -> None:
    ref = StageRef(PACK_ID, stage_id)
    native = load_default_stage(ref)

    compatible = LegacyStageModuleAdapter().load(ref)

    assert compatible.map is native.map
    assert compatible.config_class is native.config_class
    assert compatible.campaign_class is native.campaign_class
    source = Path("campaign") / PACK_ID / f"{stage_id}.py"
    text = source.read_text(encoding="utf-8")
    assert "CampaignMap" not in text
    assert "class Config" not in text
    assert "class Campaign" not in text


def _write_stage(root: Path, body: str, *, strategy: str | None = None) -> tuple[StageSpecLoader, StageSpec]:
    pack_root = root / PACK_ID
    stage_path = pack_root / "stages" / "t1.yaml"
    stage_path.parent.mkdir(parents=True)
    stage_path.write_text(inspect.cleandoc(body) + "\n", encoding="utf-8", newline="\n")
    return (
        StageSpecLoader(content_root=root, campaign_root=root.parent / "campaign"),
        StageSpec(StageRef(PACK_ID, "t1"), "stages/t1.yaml", strategy=strategy),
    )


def _minimal_stage(**replacements: str) -> str:
    body = inspect.cleandoc(
        """
        schema_version: 1
        map:
          name: T1
          shape: A1
          camera_data: [A1]
          camera_data_spawn_point: [A1]
          map_data: |-
            --
          weight_data: |-
            50
          spawn_data:
          - battle: 0
            boss: 1
        config:
          MAP_HAS_AMBUSH: false
        enemy_filter: 1L
        battles:
          0:
            policy: fleet_boss
        """
    )
    if "shape" in replacements:
        body = body.replace("  shape: A1", f"  shape: {replacements['shape']}")
    if "map_data" in replacements:
        rendered = textwrap.indent(replacements["map_data"], "    ")
        body = body.replace("  map_data: |-\n    --", f"  map_data: |-\n{rendered}")
    if "weight_data" in replacements:
        rendered = textwrap.indent(replacements["weight_data"], "    ")
        body = body.replace("  weight_data: |-\n    50", f"  weight_data: |-\n{rendered}")
    if "spawn_data" in replacements:
        rendered = textwrap.indent(replacements["spawn_data"], "  ")
        body = body.replace("  spawn_data:\n  - battle: 0\n    boss: 1", f"  spawn_data:\n{rendered}")
    if "config" in replacements:
        rendered = textwrap.indent(replacements["config"], "  ")
        body = body.replace("config:\n  MAP_HAS_AMBUSH: false", f"config:\n{rendered}")
    if "battles" in replacements:
        rendered = textwrap.indent(replacements["battles"], "  ")
        body = body.replace("battles:\n  0:\n    policy: fleet_boss", f"battles:\n{rendered}")
    return body


@pytest.mark.parametrize(
    ("replacement", "value", "message"),
    [
        ("shape", "not-a-shape", "shape"),
        ("map_data", "-- --", "map_data"),
        ("spawn_data", "- battle: true", "battle"),
        ("spawn_data", "- battle: 0\n  arbitrary: 1", "unknown"),
        ("config", "lowercase: true", "config"),
        ("config", "DANGEROUS: {call: value}", "scalar or sequence"),
        ("battles", "1:\n  policy: fleet_boss", "spawn"),
        ("battles", "0:\n  policy: arbitrary_expression", "unknown battle policy"),
        ("battles", "0:\n  policy: fleet_boss\n  arbitrary: true", "unknown"),
    ],
)
def test_loader_rejects_invalid_stage_contract_at_load_time(
    tmp_path: Path,
    replacement: str,
    value: str,
    message: str,
) -> None:
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage(**{replacement: value}))

    with pytest.raises(ContentValidationError, match=message):
        loader.load(spec)


def test_loader_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    body = _minimal_stage().replace("  name: T1", "  name: T1\n  name: OTHER")
    loader, spec = _write_stage(tmp_path / "events", body)

    with pytest.raises(ContentValidationError, match="duplicate YAML key"):
        loader.load(spec)


@pytest.mark.parametrize("token", ["--", "++", "SP", "ME", "Me", "me", "MB", "MS", "MM", "MA", "__", "SI"])
def test_loader_accepts_every_repository_map_token(tmp_path: Path, token: str) -> None:
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage(map_data=token))

    loaded = loader.load(spec)

    assert _normalized_rows(loaded.map.map_data) == (token,)


def test_loader_rejects_unknown_map_data_token_with_location(tmp_path: Path) -> None:
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage(map_data="??"))

    with pytest.raises(ContentValidationError, match=r"map\.map_data:.*unknown.*\?\?"):
        loader.load(spec)


def test_loader_rejects_unknown_map_data_loop_token_with_location(tmp_path: Path) -> None:
    body = _minimal_stage().replace(
        "  weight_data: |-\n    50",
        "  map_data_loop: |-\n    ??\n  weight_data: |-\n    50",
    )
    loader, spec = _write_stage(tmp_path / "events", body)

    with pytest.raises(ContentValidationError, match=r"map\.map_data_loop:.*unknown.*\?\?"):
        loader.load(spec)


def test_loader_rejects_boss_battle_without_policy_or_pack_strategy(tmp_path: Path) -> None:
    body = _minimal_stage(
        spawn_data="""- battle: 0
- battle: 1
- battle: 2
- battle: 3
- battle: 4
  boss: 1""",
        battles="""0:
  policy: filtered_enemy_then_default
  preserve: 0""",
    )
    loader, spec = _write_stage(tmp_path / "events", body)

    with pytest.raises(ContentValidationError, match=r"battles\.4.*strategy|strategy.*battle_4"):
        loader.load(spec)


def _stage_with_loop_only_boss(*, declare_boss_policy: bool) -> str:
    battles = """0:
  policy: filtered_enemy_then_default
  preserve: 0"""
    if declare_boss_policy:
        battles += """
1:
  policy: fleet_boss"""
    body = _minimal_stage(spawn_data="- battle: 0", battles=battles)
    return body.replace(
        "config:\n",
        "  spawn_data_loop:\n  - battle: 0\n  - battle: 1\n    boss: 1\nconfig:\n",
    )


def test_loader_rejects_loop_only_boss_without_handler(tmp_path: Path) -> None:
    loader, spec = _write_stage(
        tmp_path / "events",
        _stage_with_loop_only_boss(declare_boss_policy=False),
    )

    with pytest.raises(ContentValidationError, match=r"battles\.1.*strategy|strategy.*battle_1"):
        loader.load(spec)


def test_loader_accepts_policy_declared_only_for_loop_boss(tmp_path: Path) -> None:
    loader, spec = _write_stage(
        tmp_path / "events",
        _stage_with_loop_only_boss(declare_boss_policy=True),
    )

    loaded = loader.load(spec)

    assert loaded.map.spawn_data == [{"battle": 0}]
    assert loaded.map.spawn_data_loop == [{"battle": 0}, {"battle": 1, "boss": 1}]
    assert "battle_1" in vars(loaded.campaign_class)


class _BossZeroStrategy(CampaignBase):
    def battle_0(self):
        return self.clear_boss()


class _BossOneStrategy(CampaignBase):
    def battle_1(self):
        return self.clear_boss()


def _write_stage_with_strategy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    body: str,
    strategy_class: type[CampaignBase],
) -> tuple[StageSpecLoader, StageSpec]:
    reference = f"campaign.{PACK_ID}.strategy:CampaignStrategy"
    loader, spec = _write_stage(tmp_path / "events", body, strategy=reference)
    strategy_path = tmp_path / "campaign" / PACK_ID / "strategy.py"
    strategy_path.parent.mkdir(parents=True)
    strategy_path.write_text("# test strategy\n", encoding="utf-8", newline="\n")
    module = ModuleType(f"campaign.{PACK_ID}.strategy")
    module.__file__ = str(strategy_path)
    module.__dict__["CampaignStrategy"] = strategy_class
    monkeypatch.setattr("module.content.stage_loader.importlib.import_module", lambda _name: module)
    return loader, spec


def _boss_zero_filtered_stage() -> str:
    return _minimal_stage(
        battles="""0:
  policy: filtered_enemy_then_default
  preserve: 0""",
    )


def test_loader_rejects_filtered_policy_for_boss_zero_without_strategy(tmp_path: Path) -> None:
    loader, spec = _write_stage(tmp_path / "events", _boss_zero_filtered_stage())

    with pytest.raises(ContentValidationError, match=r"battles\.0.*fleet_boss"):
        loader.load(spec)


def test_loader_rejects_policy_and_strategy_for_same_boss_zero(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, spec = _write_stage_with_strategy(
        tmp_path,
        monkeypatch,
        _boss_zero_filtered_stage(),
        _BossZeroStrategy,
    )

    with pytest.raises(ContentValidationError, match=r"battles\.0.*strategy.*same|same.*battle_0"):
        loader.load(spec)


def test_loader_accepts_strategy_only_boss_zero_and_calls_clear_boss(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, spec = _write_stage_with_strategy(
        tmp_path,
        monkeypatch,
        _minimal_stage(battles="{}"),
        _BossZeroStrategy,
    )

    loaded = loader.load(spec)
    campaign = _BattleCampaign(boss_result="boss")

    assert _call_battle(loaded.campaign_class, 0, campaign) == "boss"
    assert campaign.calls == ["clear_boss"]
    assert "battle_0" not in vars(loaded.campaign_class)


def test_loader_rejects_empty_policies_without_any_strategy_handler(tmp_path: Path) -> None:
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage(battles="{}"))

    with pytest.raises(ContentValidationError, match=r"battles.*policy.*strategy"):
        loader.load(spec)


def test_loader_rejects_loop_policy_and_strategy_for_same_battle(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    loader, spec = _write_stage_with_strategy(
        tmp_path,
        monkeypatch,
        _stage_with_loop_only_boss(declare_boss_policy=True),
        _BossOneStrategy,
    )

    with pytest.raises(ContentValidationError, match=r"battles\.1.*strategy.*same|same.*battle_1"):
        loader.load(spec)


def test_loader_accepts_fleet_boss_policy_without_strategy(tmp_path: Path) -> None:
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage())

    loaded = loader.load(spec)
    campaign = _BattleCampaign(boss_result="boss")

    assert _call_battle(loaded.campaign_class, 0, campaign) == "boss"
    assert campaign.calls == ["fleet_boss.clear_boss"]


def test_loader_preserves_loop_portal_and_land_based_map_data(tmp_path: Path) -> None:
    body = """
        schema_version: 1
        map:
          name: T1
          shape: B2
          camera_data: [A1]
          camera_data_spawn_point: [B2]
          portal_data: [[A1, B2]]
          map_data: |-
            -- ++
            SP MB
          map_data_loop: |-
            -- --
            SP MB
          weight_data: |-
            50 50
            50 50
          land_based_data: [[A1, right]]
          spawn_data:
          - battle: 0
            boss: 1
          spawn_data_loop:
          - battle: 0
            boss: 1
        config:
          MAP_HAS_PORTAL: true
          MAP_HAS_LAND_BASED: true
        enemy_filter: 1L
        battles:
          0:
            policy: fleet_boss
    """
    loader, spec = _write_stage(tmp_path / "events", body)

    loaded = loader.load(spec)

    assert _normalized_rows(loaded.map.map_data_loop) == ("-- --", "SP MB")
    assert loaded.map.portal_data == [((0, 0), (1, 1))]
    assert loaded.map.land_based_data == [("A1", "right")]
    assert loaded.map.spawn_data_loop == [{"battle": 0, "boss": 1}]


def test_loader_rejects_manifest_stage_bound_to_another_map(tmp_path: Path) -> None:
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage().replace("name: T1", "name: HT1"))

    with pytest.raises(ContentValidationError, match=r"map\.name.*stage|stage.*map\.name"):
        loader.load(spec)


@pytest.mark.parametrize(
    "strategy",
    [
        "campaign.event_other.strategy:CampaignStrategy",
        "campaign.event_20260625_cn...strategy:CampaignStrategy",
        "campaign.event_20260625_cn.strategy:bad-name",
        "os:path",
    ],
)
def test_loader_rejects_strategy_references_outside_current_pack(
    tmp_path: Path,
    strategy: str,
) -> None:
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage(), strategy=strategy)

    with pytest.raises(ContentValidationError, match="strategy"):
        loader.load(spec)


def test_loader_rejects_strategy_module_resolved_outside_pack(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = f"campaign.{PACK_ID}.strategy:CampaignStrategy"
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage(), strategy=strategy)
    module = ModuleType(f"campaign.{PACK_ID}.strategy")
    module.__file__ = str(tmp_path / "outside" / "strategy.py")
    cast("Any", module).CampaignStrategy = CampaignBase
    monkeypatch.setattr("module.content.stage_loader.importlib.import_module", lambda _name: module)

    with pytest.raises(ContentValidationError, match=r"inside.*pack|pack.*directory"):
        loader.load(spec)


def test_loader_wraps_missing_strategy_import_with_source_location(tmp_path: Path) -> None:
    strategy = f"campaign.{PACK_ID}.missing_strategy:CampaignStrategy"
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage(), strategy=strategy)

    with pytest.raises(ContentValidationError, match=r"t1\.yaml:strategy:.*missing_strategy"):
        loader.load(spec)


def test_loader_rejects_strategy_export_outside_campaign_base(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    strategy = f"campaign.{PACK_ID}.strategy:CampaignStrategy"
    loader, spec = _write_stage(tmp_path / "events", _minimal_stage(), strategy=strategy)
    strategy_path = tmp_path / "campaign" / PACK_ID / "strategy.py"
    strategy_path.parent.mkdir(parents=True)
    strategy_path.write_text("", encoding="utf-8")
    module = ModuleType(f"campaign.{PACK_ID}.strategy")
    module.__file__ = str(strategy_path)
    cast("Any", module).CampaignStrategy = object
    monkeypatch.setattr("module.content.stage_loader.importlib.import_module", lambda _name: module)

    with pytest.raises(ContentValidationError, match="CampaignBase"):
        loader.load(spec)
