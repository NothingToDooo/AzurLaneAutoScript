from module.map_detection.grid_info import GridInfo


def _grid(**kwargs):
    grid = GridInfo()
    for key, value in kwargs.items():
        setattr(grid, key, value)
    return grid


def test_grid_info_encode_prefers_primary_flags() -> None:
    assert _grid(is_land=True, is_current_fleet=True).encode() == "++"
    assert _grid(is_boss=True, is_enemy=True).encode() == "BO"


def test_grid_info_encode_siren_genre() -> None:
    assert _grid(is_siren=True).encode() == "SU"
    assert _grid(is_siren=True, enemy_genre="Siren_Light").encode() == "LI"
    assert _grid(is_siren=True, enemy_genre="Siren_A").encode() == "A "


def test_grid_info_encode_enemy() -> None:
    assert _grid(is_enemy=True, enemy_scale=2, enemy_genre="Carrier").encode() == "2C"
    assert _grid(is_enemy=True).encode() == "0E"


def test_grid_info_encode_secondary_flags_and_empty_sea() -> None:
    assert _grid(is_current_fleet=True).encode() == "FL"
    assert _grid(is_caught_by_siren=True).encode() == "Fc"
    assert _grid(is_cleared=True).encode() == "=="
    assert _grid().encode() == "--"


def test_grid_info_merge_submarine_only_marks_spawn_point() -> None:
    spawn = _grid(is_submarine_spawn_point=True)
    assert spawn.merge(_grid(is_submarine=True)) is True
    assert spawn.is_submarine is True

    sea = _grid()
    assert sea.merge(_grid(is_submarine=True)) is True
    assert sea.is_submarine is False


def test_grid_info_merge_caught_by_siren_requires_sea() -> None:
    sea = _grid()
    assert sea.merge(_grid(is_caught_by_siren=True)) is True
    assert sea.is_fleet is True
    assert sea.is_caught_by_siren is True

    land = _grid(is_land=True)
    assert land.merge(_grid(is_caught_by_siren=True)) is False


def test_grid_info_merge_fleet_marks_current_fleet() -> None:
    sea = _grid()
    assert sea.merge(_grid(is_fleet=True, is_current_fleet=True)) is True
    assert sea.is_fleet is True
    assert sea.is_current_fleet is True

    land = _grid(is_land=True)
    assert land.merge(_grid(is_fleet=True)) is False


def test_grid_info_merge_init_fleet_can_continue_to_enemy() -> None:
    grid = _grid(may_enemy=True)

    assert grid.merge(_grid(is_fleet=True, is_enemy=True, enemy_scale=2, enemy_genre="Main"), mode="init") is True

    assert grid.is_fleet is True
    assert grid.is_enemy is True
    assert grid.enemy_scale == 2
    assert grid.enemy_genre == "Main"


def test_grid_info_merge_boss_requires_boss_spawn_and_not_land() -> None:
    boss = _grid(may_boss=True)
    assert boss.merge(_grid(is_boss=True)) is True
    assert boss.is_boss is True

    assert _grid().merge(_grid(is_boss=True)) is False
    assert _grid(is_land=True, may_boss=True).merge(_grid(is_boss=True)) is False


def test_grid_info_merge_siren_uses_spawn_or_movable_rule() -> None:
    siren = _grid(may_siren=True, enemy_scale=2)
    assert siren.merge(_grid(is_siren=True, enemy_genre="Siren_A")) is True
    assert siren.is_siren is True
    assert siren.enemy_scale == 0
    assert siren.enemy_genre == "Siren_A"

    movable = _grid(is_movable=True)
    assert movable.merge(_grid(is_siren=True, enemy_genre="Siren_B")) is True
    assert movable.is_siren is True
    assert movable.enemy_genre == "Siren_B"

    land = _grid(is_land=True, may_siren=True)
    assert land.merge(_grid(is_siren=True)) is False


def test_grid_info_merge_enemy_updates_scale_and_genre() -> None:
    enemy = _grid(may_enemy=True)
    assert enemy.merge(_grid(is_enemy=True, enemy_scale=2, enemy_genre="Carrier")) is True
    assert enemy.is_enemy is True
    assert enemy.enemy_scale == 2
    assert enemy.enemy_genre == "Carrier"


def test_grid_info_merge_enemy_preserves_known_genre_and_allows_scale_upgrade() -> None:
    enemy = _grid(may_enemy=True, enemy_scale=2, enemy_genre="Main")
    assert enemy.merge(_grid(is_enemy=True, enemy_scale=3, enemy_genre="Enemy")) is True
    assert enemy.enemy_scale == 3
    assert enemy.enemy_genre == "Main"


def test_grid_info_merge_fortress_accepts_enemy_without_state_change() -> None:
    fortress = _grid(is_fortress=True)
    assert fortress.merge(_grid(is_enemy=True, enemy_scale=2, enemy_genre="Main")) is True
    assert fortress.is_enemy is False
    assert fortress.enemy_scale == 0
    assert fortress.enemy_genre is None


def test_grid_info_merge_enemy_special_modes() -> None:
    carrier = _grid()
    assert carrier.merge(_grid(is_enemy=True, enemy_scale=1, enemy_genre="Carrier"), mode="carrier") is True
    assert carrier.is_enemy is True
    assert carrier.is_carrier is True
    assert carrier.enemy_scale == 1
    assert carrier.enemy_genre == "Carrier"

    decoy = _grid()
    assert decoy.merge(_grid(is_enemy=True, enemy_scale=1, enemy_genre="Light"), mode="decoy") is True
    assert decoy.is_enemy is True
    assert decoy.enemy_genre == "Light"

    movable = _grid(is_movable=True)
    assert movable.merge(_grid(is_enemy=True, enemy_scale=3, enemy_genre="Treasure")) is True
    assert movable.is_enemy is True
    assert movable.enemy_scale == 3
    assert movable.enemy_genre == "Treasure"


def test_grid_info_merge_mystery_and_ammo_require_spawn_flags() -> None:
    mystery = _grid(may_mystery=True)
    assert mystery.merge(_grid(is_mystery=True)) is True
    assert mystery.is_mystery is True
    assert _grid().merge(_grid(is_mystery=True)) is False

    ammo = _grid(may_ammo=True)
    assert ammo.merge(_grid(is_ammo=True)) is True
    assert ammo.is_ammo is True
    assert _grid().merge(_grid(is_ammo=True)) is False


def test_grid_info_merge_missile_attack_maps_to_known_spawn_type() -> None:
    siren = _grid(may_siren=True)
    assert siren.merge(_grid(is_missile_attack=True)) is True
    assert siren.is_siren is True

    enemy = _grid(may_enemy=True)
    assert enemy.merge(_grid(is_missile_attack=True)) is True
    assert enemy.is_enemy is True

    unknown = _grid()
    assert unknown.merge(_grid(is_missile_attack=True)) is True
    assert unknown.is_siren is False
    assert unknown.is_enemy is False
