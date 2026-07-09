from campaign.campaign_main.campaign_16_4 import I8, J6, Campaign


class _FleetBoss:
    def __init__(self, calls):
        self.calls = calls

    def clear_boss(self):
        self.calls.append(("clear_boss",))
        return True


class _Map:
    def __init__(self, boss):
        self.boss = boss

    def select(self, *, is_boss=False):
        if is_boss and self.boss is not None:
            return [self.boss]
        return []


class _Campaign(Campaign):
    map: _Map

    def __init__(self, *, boss=None, boss_accessible=True, clear_mode=False, support_fleet=False):
        self.calls = []
        self.map = _Map(boss)
        self.boss_fleet = _FleetBoss(self.calls)
        self.map_is_clear_mode = clear_mode
        self.use_support_fleet = support_fleet
        self.boss_accessible = boss_accessible
        self.roadblocks_result = False
        self.potential_roadblocks_result = False
        self.filter_enemy_result = False

    @property
    def fleet_boss(self):
        return self.boss_fleet

    def check_accessibility(self, grid, fleet=None, *_args: object, **_kwargs: object):
        self.calls.append(("check_accessibility", grid, fleet))
        return self.boss_accessible

    def clear_roadblocks(self, roads, *_args: object, **_kwargs: object):
        del roads
        self.calls.append(("clear_roadblocks",))
        return self.roadblocks_result

    def clear_potential_roadblocks(self, roads, *_args: object, **_kwargs: object):
        del roads
        self.calls.append(("clear_potential_roadblocks",))
        return self.potential_roadblocks_result

    def clear_filter_enemy(self, string, preserve=0, *_args: object, **_kwargs: object):
        self.calls.append(("clear_filter_enemy", string, preserve))
        return self.filter_enemy_result

    def battle_default(self):
        self.calls.append(("battle_default",))
        return "default"

    def goto(self, location, *_args: object, **_kwargs: object):
        self.calls.append(("goto", location.location))

    def air_strike(self, location, *_args: object, **_kwargs: object):
        self.calls.append(("air_strike", location.location))


def test_battle_4_clear_mode_clears_boss_directly() -> None:
    campaign = _Campaign(clear_mode=True)

    assert campaign.battle_4() is True

    assert campaign.calls == [("clear_boss",)]


def test_battle_4_inaccessible_boss_clears_roadblocks() -> None:
    campaign = _Campaign(boss=object(), boss_accessible=False)
    campaign.roadblocks_result = True

    assert campaign.battle_4() is True

    assert campaign.calls == [
        ("check_accessibility", campaign.map.boss, "boss"),
        ("clear_roadblocks",),
    ]


def test_battle_4_support_fleet_attacks_before_boss() -> None:
    campaign = _Campaign(boss=object(), support_fleet=True)

    assert campaign.battle_4() is True

    assert campaign.calls == [
        ("check_accessibility", campaign.map.boss, "boss"),
        ("goto", J6.location),
        ("air_strike", I8.location),
        ("clear_boss",),
    ]


def test_battle_4_without_boss_uses_path_priority() -> None:
    campaign = _Campaign()
    campaign.potential_roadblocks_result = True

    assert campaign.battle_4() is True

    assert campaign.calls == [
        ("clear_roadblocks",),
        ("clear_potential_roadblocks",),
    ]
