from pathlib import Path
from types import SimpleNamespace

import pytest

from module.campaign.campaign_ocr import CampaignOcr, StageMatchOptions, stage_match_options
from module.campaign.run import (
    CampaignRun,
    _apply_campaign_folder_policies,
    _apply_stage_alias_policies,
    _normalize_stage_alias,
    _resolve_stage_loop_alias,
)
from module.config.config_manual import ManualConfig
from module.content.manifest import load_event_manifests

PACKS = load_event_manifests(Path("content/events"))


class _LoopConfig:
    def __init__(self, run_count: int) -> None:
        self.StopCondition_RunCount = run_count
        self.overrides: list[dict[str, object]] = []

    def override(self, **kwargs: object) -> None:
        self.overrides.append(kwargs)


class _PolicyConfig:
    def __init__(self, map_achievement: str) -> None:
        self.StopCondition_MapAchievement = map_achievement
        self.overrides: list[dict[str, object]] = []

    def override(self, **kwargs: object) -> None:
        self.overrides.append(kwargs)
        for key, value in kwargs.items():
            setattr(self, key, value)


class _HandleConfig(_PolicyConfig):
    def __init__(self, *, run_count: int = 1, map_achievement: str = "100_percent_clear") -> None:
        super().__init__(map_achievement)
        self.StopCondition_RunCount = run_count
        self.task = SimpleNamespace(command="Event")


@pytest.mark.parametrize(
    ("folder", "name", "expected"),
    [
        ("event_20201126_cn", "vsp", "sp"),
        ("event_20220324_cn", "esp", "sp"),
        ("event_20221124_cn", "a.sp", "sp"),
        ("event_20240425_cn", "\u03bcsp", "sp"),
        ("event_20240425_cn", "1sp", "isp1"),
        ("event_20240725_cn", "y.sp", "sp"),
        ("event_20260417_cn", "vsp", "sp"),
        ("event_20210722_cn", "vsp", "sp"),
        ("event_20211125_cn", "a1", "t1"),
        ("event_20221124_cn", "d1", "th4"),
        ("campaign_main", "t1", "a1"),
        ("event_20230817_cn", "e01", "a1"),
        ("event_20230817_cn", "e02", "a1"),
        ("event_20230817_cn", "e03", "a1"),
        ("event_20230817_cn", "e0-1", "a1"),
        ("event_20230817_cn", "e0-2", "a1"),
        ("event_20230817_cn", "e0-3", "a1"),
        ("event_20240829_cn", "tp", "sp"),
    ],
)
def test_stage_alias_normalization(folder: str, name: str, expected: str) -> None:
    assert _normalize_stage_alias(name, folder) == expected


@pytest.mark.parametrize(
    ("alias", "expected"),
    [
        *((f"lsp{index}", f"isp{index}") for index in range(1, 7)),
        *((f"1sp{index}", f"isp{index}") for index in range(1, 7)),
    ],
)
def test_music_event_numbered_sp_aliases(alias: str, expected: str) -> None:
    assert _normalize_stage_alias(alias, "event_20240425_cn") == expected


def test_stage_loop_alias_uses_remaining_run_count() -> None:
    config = _LoopConfig(run_count=1)

    name, is_stage_loop = _resolve_stage_loop_alias("ts", "event_20250724_cn", config)

    assert name == "ts5"
    assert is_stage_loop
    assert config.overrides == [
        {"StopCondition_MapAchievement": "non_stop"},
        {"StopCondition_StageIncrease": False},
    ]


def test_stage_loop_alias_ignores_regular_stage() -> None:
    config = _LoopConfig(run_count=1)

    name, is_stage_loop = _resolve_stage_loop_alias("a1", "event_20250724_cn", config)

    assert name == "a1"
    assert not is_stage_loop
    assert config.overrides == []


@pytest.mark.parametrize(
    ("run_count", "expected"),
    [(5, "ts1"), (4, "ts2"), (1, "ts5")],
)
def test_stage_loop_alias_preserves_reverse_modulo_boundary(run_count: int, expected: str) -> None:
    config = _LoopConfig(run_count=run_count)

    name, is_stage_loop = _resolve_stage_loop_alias("ts", "event_20250724_cn", config)

    assert name == expected
    assert is_stage_loop


def test_stage_loop_alias_uses_random_choice_for_zero_count(monkeypatch: pytest.MonkeyPatch) -> None:
    config = _LoopConfig(run_count=0)
    monkeypatch.setattr("module.content.campaign_policy.random.choice", lambda stages: stages[2])

    name, is_stage_loop = _resolve_stage_loop_alias("th", "event_20221124_cn", config)

    assert name == "th3"
    assert is_stage_loop


def test_config_manual_no_longer_owns_dated_loop_data() -> None:
    assert not hasattr(ManualConfig, "STAGE_LOOP_ALIAS")


def test_every_manifest_alias_is_applied_exactly() -> None:
    for pack in PACKS:
        for source, target in pack.policy.aliases:
            assert _normalize_stage_alias(source, str(pack.pack_id)) == target


def test_old_mistyped_event_ids_do_not_receive_aliases() -> None:
    assert _normalize_stage_alias("vsp", "event_20210723_cn") == "vsp"
    assert _normalize_stage_alias("y.sp", "event_20240724_cn") == "y.sp"


def test_handle_stage_name_keeps_alias_then_stage_policy_order() -> None:
    runner = object.__new__(CampaignRun)
    runner.config = _HandleConfig()
    runner.is_stage_loop = False

    name, folder = runner.handle_stage_name("D1", "event_20221124_cn")

    assert (name, folder) == ("th4", "event_20221124_cn")
    assert runner.config.overrides == [{"StopCondition_MapAchievement": "threat_safe"}]


def test_handle_stage_name_keeps_loop_state_sticky() -> None:
    runner = object.__new__(CampaignRun)
    runner.config = _HandleConfig(run_count=1)
    runner.is_stage_loop = False

    first, _ = runner.handle_stage_name("TS", "event_20250724_cn")
    second, _ = runner.handle_stage_name("A1", "event_20250724_cn")

    assert (first, second) == ("ts5", "t1")
    assert runner.is_stage_loop


def test_handle_stage_name_keeps_hard_mode_conversion(monkeypatch: pytest.MonkeyPatch) -> None:
    runner = object.__new__(CampaignRun)
    runner.config = _HandleConfig()
    runner.is_stage_loop = False
    monkeypatch.setattr("module.campaign.run.map_files", lambda folder: ["a1"] if folder == "campaign_hard" else [])

    name, folder = runner.handle_stage_name("T1", "campaign_main", mode="hard")

    assert (name, folder) == ("a1", "campaign_hard")


def test_stage_alias_policies_force_th_chapter_map_achievement() -> None:
    config = _PolicyConfig(map_achievement="100_percent_clear")

    _apply_stage_alias_policies("th4", "event_20221124_cn", config)

    assert config.overrides == [{"StopCondition_MapAchievement": "threat_safe"}]


def test_stage_alias_policies_keep_non_stop_map_achievement() -> None:
    config = _PolicyConfig(map_achievement="non_stop")

    _apply_stage_alias_policies("th4", "event_20221124_cn", config)

    assert config.overrides == []


def test_stage_alias_policies_are_exact_not_prefix_based() -> None:
    config = _PolicyConfig(map_achievement="100_percent_clear")

    _apply_stage_alias_policies("th6", "event_20221124_cn", config)

    assert config.overrides == []


def test_stage_alias_policies_apply_tss_overrides() -> None:
    config = _PolicyConfig(map_achievement="100_percent_clear")

    _apply_stage_alias_policies("tss1", "event_20211125_cn", config)

    assert config.overrides == [
        {
            "StopCondition_OilLimit": 0,
            "StopCondition_MapAchievement": "100_percent_clear",
            "StopCondition_StageIncrease": True,
            "Emotion_Mode": "ignore",
            "Fleet_Fleet2": 0,
            "Submarine_Fleet": 0,
        }
    ]


def test_every_manifest_loop_and_stage_override_target_exists() -> None:
    for pack in PACKS:
        pack_id = str(pack.pack_id)
        native = {stage.ref.stage_id for stage in pack.stages}
        legacy = {path.stem for path in (Path("campaign") / pack_id).glob("*.py")}
        existing = native | legacy
        for _, target in pack.policy.aliases:
            assert target in existing
        for _, stages in pack.policy.loops:
            assert set(stages) <= existing
        assert set(pack.policy.force_threat_safe_stages) <= existing
        assert set(pack.policy.resource_free_stages) <= existing


def test_campaign_folder_policies_fallback_threat_safe() -> None:
    config = _PolicyConfig(map_achievement="threat_safe")

    _apply_campaign_folder_policies("event_20240912_cn", config)

    assert config.overrides == [{"StopCondition_MapAchievement": "map_3_stars"}]


def test_campaign_folder_policies_fallback_threat_safe_without_3_stars() -> None:
    config = _PolicyConfig(map_achievement="threat_safe_without_3_stars")

    _apply_campaign_folder_policies("event_20240912_cn", config)

    assert config.overrides == [{"StopCondition_MapAchievement": "100_percent_clear"}]


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("sp", ("ex_sp", "1")),
        ("extra", ("ex_ex", "1")),
        ("ex", ("ex_ex", "1")),
        ("7-2", ["7", "2"]),
        ("sp3", ("sp", "3")),
        ("d3", ("d", "3")),
        ("49x", ("", "")),
        ("unknown", ("", "")),
    ],
)
def test_campaign_separate_name(name, expected) -> None:
    assert CampaignOcr.campaign_separate_name(name) == expected


def test_stage_match_options_override_existing_options() -> None:
    options = stage_match_options(StageMatchOptions(name_offset=(1, 2)), {"similarity": 0.6})

    assert options.name_offset == (1, 2)
    assert options.similarity == 0.6
