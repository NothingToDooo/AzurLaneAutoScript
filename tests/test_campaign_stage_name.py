import pytest

from module.campaign.run import (
    _apply_campaign_folder_policies,
    _apply_stage_alias_policies,
    _normalize_stage_alias,
    _resolve_stage_loop_alias,
)


class _LoopConfig:
    def __init__(self, run_count: int) -> None:
        self.STAGE_LOOP_ALIAS = {("event_loop", "ts"): "ts1 > ts2 > ts3"}
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


@pytest.mark.parametrize(
    ("folder", "name", "expected"),
    [
        ("event_20201126_cn", "vsp", "sp"),
        ("event_20220324_cn", "esp", "sp"),
        ("event_20221124_cn", "a.sp", "sp"),
        ("event_20240425_cn", "\u03bcsp", "sp"),
        ("event_20240425_cn", "1sp", "isp1"),
        ("event_20240724_cn", "y.sp", "sp"),
        ("event_20211125_cn", "a1", "t1"),
        ("event_20221124_cn", "d1", "th4"),
        ("campaign_main", "t1", "a1"),
        ("event_20230817_cn", "e01", "a1"),
        ("event_20240829_cn", "tp", "sp"),
    ],
)
def test_stage_alias_normalization(folder: str, name: str, expected: str) -> None:
    assert _normalize_stage_alias(name, folder) == expected


def test_stage_loop_alias_uses_remaining_run_count() -> None:
    config = _LoopConfig(run_count=1)

    name, is_stage_loop = _resolve_stage_loop_alias("ts", "event_loop", config)

    assert name == "ts3"
    assert is_stage_loop
    assert config.overrides == [
        {"StopCondition_MapAchievement": "non_stop"},
        {"StopCondition_StageIncrease": False},
    ]


def test_stage_loop_alias_ignores_regular_stage() -> None:
    config = _LoopConfig(run_count=1)

    name, is_stage_loop = _resolve_stage_loop_alias("a1", "event_loop", config)

    assert name == "a1"
    assert not is_stage_loop
    assert config.overrides == []


def test_stage_alias_policies_force_th_chapter_map_achievement() -> None:
    config = _PolicyConfig(map_achievement="100_percent_clear")

    _apply_stage_alias_policies("th4", "event_20221124_cn", config)

    assert config.overrides == [{"StopCondition_MapAchievement": "threat_safe"}]


def test_stage_alias_policies_keep_non_stop_map_achievement() -> None:
    config = _PolicyConfig(map_achievement="non_stop")

    _apply_stage_alias_policies("th4", "event_20221124_cn", config)

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


def test_campaign_folder_policies_fallback_threat_safe() -> None:
    config = _PolicyConfig(map_achievement="threat_safe")

    _apply_campaign_folder_policies("event_20240912_cn", config)

    assert config.overrides == [{"StopCondition_MapAchievement": "map_3_stars"}]


def test_campaign_folder_policies_fallback_threat_safe_without_3_stars() -> None:
    config = _PolicyConfig(map_achievement="threat_safe_without_3_stars")

    _apply_campaign_folder_policies("event_20240912_cn", config)

    assert config.overrides == [{"StopCondition_MapAchievement": "100_percent_clear"}]
