from typing import Literal

import pytest

from campaign.event_20200917_cn.campaign_base import CampaignBase as Event20200917Base
from campaign.event_20230525_cn.campaign_base import CampaignBase as Event20230525Base
from campaign.war_archives_20200917_cn.campaign_base import CampaignBase as WarArchives20200917Base
from campaign.war_archives_20230525_cn.campaign_base import CampaignBase as WarArchives20230525Base

type _Call = tuple[str] | tuple[str, str | int]
type _BallStatus = Literal["blue", "red"]


class _RecordingCampaign:
    def __init__(self) -> None:
        self.calls: list[_Call] = []

    def ui_goto_campaign(self) -> bool:
        self.calls.append(("ui_goto_campaign",))
        return True

    def ui_goto_event(self) -> bool:
        self.calls.append(("ui_goto_event",))
        return True

    def ui_goto_sp(self) -> bool:
        self.calls.append(("ui_goto_sp",))
        return True

    def campaign_ensure_mode(self, mode: str) -> None:
        self.calls.append(("mode", mode))

    def campaign_ensure_chapter(
        self,
        chapter: str | int,
        *,
        skip_first_screenshot: bool = True,
    ) -> None:
        del skip_first_screenshot
        self.calls.append(("chapter", chapter))

    def _campaign_ball_set(self, status: _BallStatus) -> None:
        self.calls.append(("ball", status))


class _Event20200917Campaign(_RecordingCampaign, Event20200917Base):
    pass


class _WarArchives20200917Campaign(_RecordingCampaign, WarArchives20200917Base):
    pass


class _Event20230525Campaign(_RecordingCampaign, Event20230525Base):
    pass


class _WarArchives20230525Campaign(_RecordingCampaign, WarArchives20230525Base):
    pass


@pytest.mark.parametrize(
    "campaign_cls",
    [_Event20200917Campaign, _WarArchives20200917Campaign],
)
@pytest.mark.parametrize(
    ("name", "expected_calls"),
    [
        (
            "t1",
            [
                ("ui_goto_event",),
                ("ball", "blue"),
                ("mode", "normal"),
                ("chapter", 1),
            ],
        ),
        (
            "t2",
            [
                ("ui_goto_event",),
                ("ball", "red"),
                ("mode", "normal"),
                ("chapter", 1),
            ],
        ),
        (
            "ht6",
            [
                ("ui_goto_event",),
                ("ball", "blue"),
                ("mode", "hard"),
                ("chapter", 1),
            ],
        ),
    ],
)
def test_20200917_event_ball_chapter_keeps_original_order(
    campaign_cls: type[_Event20200917Campaign | _WarArchives20200917Campaign],
    name: str,
    expected_calls: list[_Call],
) -> None:
    campaign = campaign_cls()

    campaign.campaign_set_chapter(name)

    assert campaign.calls == expected_calls


@pytest.mark.parametrize(
    "campaign_cls",
    [_Event20230525Campaign, _WarArchives20230525Campaign],
)
@pytest.mark.parametrize(
    ("name", "expected_calls"),
    [
        (
            "t3",
            [
                ("ui_goto_event",),
                ("mode", "normal"),
                ("ball", "blue"),
                ("chapter", 1),
            ],
        ),
        (
            "t4",
            [
                ("ui_goto_event",),
                ("mode", "normal"),
                ("ball", "red"),
                ("chapter", 1),
            ],
        ),
        (
            "hts1",
            [
                ("ui_goto_event",),
                ("mode", "hard"),
                ("ball", "blue"),
                ("chapter", 1),
            ],
        ),
    ],
)
def test_20230525_event_ball_chapter_keeps_original_order(
    campaign_cls: type[_Event20230525Campaign | _WarArchives20230525Campaign],
    name: str,
    expected_calls: list[_Call],
) -> None:
    campaign = campaign_cls()

    campaign.campaign_set_chapter(name)

    assert campaign.calls == expected_calls


@pytest.mark.parametrize(
    "campaign_cls",
    [
        _Event20200917Campaign,
        _WarArchives20200917Campaign,
        _Event20230525Campaign,
        _WarArchives20230525Campaign,
    ],
)
def test_event_ball_campaign_keeps_regular_chapter_routes(
    campaign_cls: (
        type[
            _Event20200917Campaign
            | _WarArchives20200917Campaign
            | _Event20230525Campaign
            | _WarArchives20230525Campaign
        ]
    ),
) -> None:
    campaign = campaign_cls()

    campaign.campaign_set_chapter("7-2", mode="hard")

    assert campaign.calls == [
        ("ui_goto_campaign",),
        ("mode", "normal"),
        ("chapter", "7"),
        ("mode", "hard"),
    ]
