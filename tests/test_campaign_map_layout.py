from typing import TYPE_CHECKING

import numpy as np

from module.base.utils import location2node
from module.map.map_layout import CampaignMapLayout
from module.map_detection.grid_info import GridInfo
from module.map_detection.os_grid import OSGridInfo
from module.os.map_base import OSCampaignMap

if TYPE_CHECKING:
    from collections.abc import Iterable


class _CustomGrid(GridInfo):
    pass


def _nodes(grids: Iterable[GridInfo]) -> list[str]:
    nodes = []
    for grid in grids:
        assert grid.location is not None
        nodes.append(location2node(grid.location))
    return nodes


def test_layout_builds_canonical_grids_with_the_injected_factory() -> None:
    layout = CampaignMapLayout(grid_class=_CustomGrid)

    layout.initialize("c2")

    assert layout.shape == (2, 1)
    assert [grid.location for grid in layout] == [
        (0, 0),
        (1, 0),
        (2, 0),
        (0, 1),
        (1, 1),
        (2, 1),
    ]
    assert all(type(grid) is _CustomGrid for grid in layout)
    assert len({id(grid) for grid in layout}) == 6
    assert [grid.weight for grid in layout] == [10.0] * 6
    assert _nodes(layout.camera_data) == ["B1"]
    assert not layout.camera_data_spawn_point


def test_layout_rebuilds_camera_plan_and_manual_queues_from_canonical_grids() -> None:
    layout = CampaignMapLayout(camera_sight=(-1, -1, 1, 1))
    layout.initialize("E4")

    assert _nodes(layout.camera_data) == ["B2", "B3", "D2", "D3"]

    layout.set_camera_data(["E4", "A1"])
    layout.set_camera_data_spawn_point(["C2"])

    assert list(layout.camera_data) == [layout[(4, 3)], layout[(0, 0)]]
    assert list(layout.camera_data_spawn_point) == [layout[(2, 1)]]


def test_layout_projects_weight_text_onto_the_same_grids() -> None:
    layout = CampaignMapLayout()
    layout.initialize("B2")

    layout.apply_weights("1 2\n3 4")

    assert layout.weight_data == "1 2\n3 4"
    assert [grid.weight for grid in layout] == [1.0, 2.0, 3.0, 4.0]


def test_layout_combines_dynamic_and_manual_coverage_without_duplicates() -> None:
    layout = CampaignMapLayout()
    layout.initialize("C3")
    layout[(1, 2)].is_current_fleet = True
    layout[(2, 1)].is_siren = True
    layout[(0, 0)].is_mystery = True
    layout.set_manual_coverage(["A3", "B2"])

    assert set(_nodes(layout.covered_grids)) == {"A3", "B1", "B2", "C1"}
    assert _nodes(layout.manual_coverage) == ["A3", "B2"]


def test_layout_selects_and_normalizes_grid_references_in_iteration_order() -> None:
    layout = CampaignMapLayout()
    layout.initialize("C2")
    layout[(0, 0)].is_enemy = True
    layout[(2, 0)].is_enemy = True
    layout[(2, 0)].is_boss = True

    assert _nodes(layout.select(is_enemy=True)) == ["A1", "C1"]
    assert _nodes(layout.select(is_enemy=True, is_boss=True)) == ["C1"]
    assert list(layout.to_selected((layout[(0, 0)], "C1", (1, 1)))) == [
        layout[(0, 0)],
        layout[(2, 0)],
        layout[(1, 1)],
    ]


def test_layout_membership_requires_an_integral_two_coordinate_location() -> None:
    layout = CampaignMapLayout()
    layout.initialize("B2")

    assert (0, 0) in layout
    assert [1, 1] in layout
    assert np.array([0, 1], dtype=np.int64) in layout
    assert (np.int64(1), np.int64(0)) in layout
    assert (2, 0) not in layout
    assert (0.0, 0) not in layout
    assert np.array([0.0, 1.0]) not in layout
    assert np.array([[0, 1]]) not in layout
    assert "A1" not in layout


def test_os_campaign_map_assembles_os_grids_and_camera_sight() -> None:
    map_ = OSCampaignMap("os-layout-test")

    map_.layout.initialize("E4")

    assert all(type(grid) is OSGridInfo for grid in map_)
    assert map_.layout.camera_sight == (-4, -1, 3, 3)
    assert _nodes(map_.layout.camera_data) == ["C1"]
