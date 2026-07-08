import pytest

from module.map_detection.os_grid import OSGridInfo
from module.os.radar import RadarGrid


def _grid(**kwargs):
    grid = OSGridInfo()
    for key, value in kwargs.items():
        setattr(grid, key, value)
    return grid


def _radar_grid(**kwargs):
    grid = RadarGrid(location=(1, 0), image=None, center=(0, 0), config=object())
    for key, value in kwargs.items():
        setattr(grid, key, value)
    return grid


def test_os_grid_info_merge_requires_normal_mode() -> None:
    with pytest.raises(ValueError, match="normal scan mode"):
        _grid().merge(_grid(), mode="movable")


@pytest.mark.parametrize(
    "flag",
    [
        "is_ally",
        "is_akashi",
        "is_scanning_device",
        "is_logging_tower",
        "is_exploration_reward",
        "is_fleet_mechanism",
        "is_question",
        "is_meowfficer",
        "is_exclamation",
        "is_resource",
    ],
)
def test_os_grid_info_merge_sets_first_matching_marker(flag: str) -> None:
    grid = _grid()
    assert grid.merge(_grid(**{flag: True})) is True
    assert getattr(grid, flag) is True


def test_os_grid_info_merge_enemy_updates_scale_and_genre() -> None:
    grid = _grid()

    assert grid.merge(_grid(is_enemy=True, enemy_scale=2, enemy_genre="Carrier")) is True

    assert grid.is_enemy is True
    assert grid.enemy_scale == 2
    assert grid.enemy_genre == "Carrier"


def test_os_grid_info_merge_enemy_keeps_known_genre_over_unknown() -> None:
    grid = _grid(enemy_genre="Main")

    assert grid.merge(_grid(is_enemy=True, enemy_scale=1, enemy_genre="Enemy")) is True

    assert grid.is_enemy is True
    assert grid.enemy_scale == 1
    assert grid.enemy_genre == "Main"


def test_os_grid_info_merge_accepts_radar_grid_as_partial_source() -> None:
    grid = _grid()

    assert grid.merge(_radar_grid(is_enemy=True, enemy_scale=3, enemy_genre="Siren_A")) is True

    assert grid.is_radar_scanned is True
    assert grid.is_enemy is True
    assert grid.enemy_scale == 3
    assert grid.enemy_genre == "Siren_A"


def test_os_grid_info_merge_marks_only_radar_scanned_for_empty_radar_grid() -> None:
    grid = _grid()

    assert grid.merge(_radar_grid()) is True

    assert grid.is_radar_scanned is True
    assert grid.is_enemy is False
    assert grid.is_resource is False
