import pytest

from campaign.event_20201229_cn.d1 import Campaign as EventD1Campaign
from campaign.event_20201229_cn.d3 import Campaign as EventD3Campaign
from campaign.war_archives_20201229_cn.d1 import Campaign as WarArchivesD1Campaign
from campaign.war_archives_20201229_cn.d3 import Campaign as WarArchivesD3Campaign

type _CampaignCall = tuple[str] | tuple[str, tuple[int, ...], list[str] | None]


class _RecordingCampaign:
    def __init__(self, successful_call: _CampaignCall | None = None) -> None:
        self.successful_call = successful_call
        self.calls: list[_CampaignCall] = []

    def fleet_2_protect(self) -> bool:
        call = ("fleet_2_protect",)
        self.calls.append(call)
        return call == self.successful_call

    def clear_siren(self) -> bool:
        call = ("clear_siren",)
        self.calls.append(call)
        return call == self.successful_call

    def clear_enemy(self, *, scale: tuple[int, ...], genre: list[str] | None = None) -> bool:
        call = ("clear_enemy", scale, genre)
        self.calls.append(call)
        return call == self.successful_call

    def battle_default(self) -> bool:
        self.calls.append(("battle_default",))
        return False


class _EventD1(_RecordingCampaign, EventD1Campaign):
    pass


class _WarArchivesD1(_RecordingCampaign, WarArchivesD1Campaign):
    pass


class _EventD3(_RecordingCampaign, EventD3Campaign):
    pass


class _WarArchivesD3(_RecordingCampaign, WarArchivesD3Campaign):
    pass


@pytest.mark.parametrize("campaign_cls", [_EventD1, _WarArchivesD1])
def test_d1_priority_enemy_keeps_scale_1_before_genre_filters(
    campaign_cls: type[_EventD1 | _WarArchivesD1],
) -> None:
    campaign = campaign_cls(successful_call=("clear_enemy", (3,), ["Enemy", "CarrierInvertedOrthant"]))

    assert campaign.battle_0() is True

    assert campaign.calls == [
        ("clear_siren",),
        ("clear_enemy", (1,), None),
        ("clear_enemy", (2,), ["LightInvertedOrthant", "MainInvertedOrthant"]),
        ("clear_enemy", (3,), ["LightInvertedOrthant", "MainInvertedOrthant"]),
        ("clear_enemy", (2,), ["Enemy", "CarrierInvertedOrthant"]),
        ("clear_enemy", (3,), ["Enemy", "CarrierInvertedOrthant"]),
    ]


@pytest.mark.parametrize("campaign_cls", [_EventD3, _WarArchivesD3])
def test_d3_battle_0_keeps_fleet_protection_and_skips_scale_1(
    campaign_cls: type[_EventD3 | _WarArchivesD3],
) -> None:
    campaign = campaign_cls(successful_call=("clear_enemy", (2,), ["Enemy", "CarrierInvertedOrthant"]))

    assert campaign.battle_0() is True

    assert campaign.calls == [
        ("fleet_2_protect",),
        ("clear_siren",),
        ("clear_enemy", (2,), ["LightInvertedOrthant", "MainInvertedOrthant"]),
        ("clear_enemy", (3,), ["LightInvertedOrthant", "MainInvertedOrthant"]),
        ("clear_enemy", (2,), ["Enemy", "CarrierInvertedOrthant"]),
    ]


@pytest.mark.parametrize("campaign_cls", [_EventD3, _WarArchivesD3])
def test_d3_battle_5_keeps_scale_1_priority(campaign_cls: type[_EventD3 | _WarArchivesD3]) -> None:
    campaign = campaign_cls(successful_call=("clear_enemy", (1,), None))

    assert campaign.battle_5() is True

    assert campaign.calls == [
        ("fleet_2_protect",),
        ("clear_siren",),
        ("clear_enemy", (1,), None),
    ]
