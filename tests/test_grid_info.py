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
