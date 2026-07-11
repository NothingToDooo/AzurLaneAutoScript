import pytest

from campaign.event_20221124_cn.campaign_base import CampaignBase


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("ex", ("t4", "1")),
        ("asp", ("t3", "1")),
        ("sp", ("t3", "1")),
        ("ts1", ("t1", "1")),
        ("th5", ("t2", "5")),
        ("t4", ("t1", "4")),
    ],
)
def test_ryza_campaign_separate_name_aliases(name, expected) -> None:
    assert CampaignBase.campaign_separate_name(name) == expected


def test_ryza_campaign_separate_name_falls_back_to_base() -> None:
    assert CampaignBase.campaign_separate_name("7-2") == ("7", "2")
