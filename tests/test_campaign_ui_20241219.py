from typing import TYPE_CHECKING, override

import pytest

import module.campaign.campaign_ui as campaign_ui_module
from module.campaign.campaign_ui import CampaignUI

if TYPE_CHECKING:
    from collections.abc import Iterable


class _Config:
    def __init__(
        self,
        *,
        chapter_switch: bool = False,
        chapter_switch_sp: bool = False,
        chapter_switch_spex: bool = False,
    ) -> None:
        self.MAP_CHAPTER_SWITCH_20241219 = chapter_switch
        self.MAP_CHAPTER_SWITCH_20241219_SP = chapter_switch_sp
        self.MAP_CHAPTER_SWITCH_20241219_SPEX = chapter_switch_spex
        self.overrides: list[dict[str, str]] = []

    def override(self, **kwargs: str) -> None:
        self.overrides.append(kwargs)


class _CampaignUI(CampaignUI):
    config: _Config

    def __init__(
        self,
        *,
        chapter_switch: bool = False,
        chapter_switch_sp: bool = False,
        chapter_switch_spex: bool = False,
        hard_names: Iterable[str] = (),
    ) -> None:
        self.config = _Config(
            chapter_switch=chapter_switch,
            chapter_switch_sp=chapter_switch_sp,
            chapter_switch_spex=chapter_switch_spex,
        )
        self.hard_names = set(hard_names)
        self.calls = []

    def _campaign_name_is_hard(self, name: str) -> bool:
        self.calls.append(("is_hard", name))
        return name in self.hard_names

    @override
    def ui_goto_event(self) -> bool:
        self.calls.append(("ui_goto_event",))
        return True

    def campaign_ensure_mode_20241219(self, mode: str = "combat") -> None:
        self.calls.append(("mode", mode))

    @override
    def campaign_ensure_aside_20241219(self, chapter: str) -> None:
        self.calls.append(("aside", chapter))

    @override
    def campaign_ensure_chapter(
        self,
        chapter: str | int,
        *,
        skip_first_screenshot: bool = True,
    ) -> None:
        del skip_first_screenshot
        self.calls.append(("chapter", chapter))


def test_campaign_set_chapter_20241219_story_mode_uses_story_switch() -> None:
    ui = _CampaignUI(chapter_switch=True, hard_names={"a1"})

    assert ui.campaign_set_chapter_20241219("a", "1", mode="story") is True

    assert ui.config.overrides == [{"Campaign_Mode": "hard"}]
    assert ui.calls == [("is_hard", "a1"), ("mode", "story")]


@pytest.mark.parametrize(
    ("chapter", "aside"),
    [
        ("a", "part1"),
        ("c", "part1"),
        ("t", "part1"),
        ("b", "part2"),
        ("d", "part2"),
        ("ttl", "part2"),
        ("ex_sp", "sp"),
        ("ex_ex", "ex"),
    ],
)
def test_campaign_set_chapter_20241219_full_switch_routes_chapter(chapter: str, aside: str) -> None:
    ui = _CampaignUI(chapter_switch=True)

    assert ui.campaign_set_chapter_20241219(chapter, "1") is True

    assert ui.calls == [
        ("is_hard", f"{chapter}1"),
        ("ui_goto_event",),
        ("mode", "combat"),
        ("aside", aside),
        ("chapter", chapter),
    ]


@pytest.mark.parametrize(
    ("chapter", "aside"),
    [
        ("sp", "part2"),
        ("t", "part2"),
        ("ht", "part2"),
        ("ex_sp", "sp"),
    ],
)
def test_campaign_set_chapter_20241219_sp_switch_routes_limited_chapter(chapter: str, aside: str) -> None:
    ui = _CampaignUI(chapter_switch_sp=True)

    assert ui.campaign_set_chapter_20241219(chapter, "1") is True

    assert ui.calls == [
        ("is_hard", f"{chapter}1"),
        ("ui_goto_event",),
        ("mode", "combat"),
        ("aside", aside),
        ("chapter", chapter),
    ]


@pytest.mark.parametrize(
    ("chapter", "aside"),
    [
        ("sp", "part2"),
        ("t", "part2"),
        ("ht", "part2"),
        ("ex_sp", "sp"),
        ("ex_ex", "ex"),
    ],
)
def test_campaign_set_chapter_20241219_spex_switch_routes_and_restores_offset(chapter: str, aside: str) -> None:
    ui = _CampaignUI(chapter_switch_spex=True)

    assert ui.campaign_set_chapter_20241219(chapter, "1") is True

    assert ui.calls == [
        ("is_hard", f"{chapter}1"),
        ("ui_goto_event",),
        ("mode", "combat"),
        ("aside", aside),
        ("chapter", chapter),
    ]
    assert campaign_ui_module.ASIDE_SWITCH_20241219.offset == (20, 20)


def test_campaign_set_chapter_20241219_spex_switch_restores_offset_without_match() -> None:
    ui = _CampaignUI(chapter_switch_spex=True)

    assert ui.campaign_set_chapter_20241219("unknown", "1") is False

    assert campaign_ui_module.ASIDE_SWITCH_20241219.offset == (20, 20)


def test_campaign_set_chapter_20241219_returns_false_without_enabled_switch() -> None:
    ui = _CampaignUI()

    assert ui.campaign_set_chapter_20241219("a", "1") is False

    assert ui.calls == []
