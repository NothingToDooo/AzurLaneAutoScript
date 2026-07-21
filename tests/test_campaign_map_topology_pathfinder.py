from module.map.map_base import CampaignMap


def _synthetic_map(shape: str = "C2") -> CampaignMap:
    map_ = CampaignMap("topology-pathfinder-test")
    map_.layout.initialize(shape)
    return map_


def test_topology_applies_bidirectional_walls_and_directed_portals() -> None:
    map_ = _synthetic_map()
    map_.topology.configure(
        walls=(((0, 0), (1, 0)),),
        portals=(((0, 1), (2, 0)),),
    )

    map_.topology.rebuild(wall=True, portal=True)

    assert (1, 0) not in map_.topology.neighbors((0, 0))
    assert (0, 0) not in map_.topology.neighbors((1, 0))
    assert map_.topology.neighbors((0, 1)) == frozenset({(2, 0)})
    assert (0, 1) not in map_.topology.neighbors((2, 0))
    assert map_.topology.portal_destination((0, 1)) == (2, 0)


def test_topology_rebuild_restores_disabled_walls_and_preserves_natural_portal_edges() -> None:
    map_ = _synthetic_map("B1")
    edge = ((0, 0), (1, 0))
    map_.topology.configure(walls=(edge,), portals=(edge,))

    map_.topology.rebuild(wall=True, portal=False)

    assert map_.topology.neighbors((0, 0)) == frozenset()
    assert map_.topology.portal_destination((0, 0)) is None

    map_.topology.rebuild(wall=True, portal=True)

    assert map_.topology.neighbors((0, 0)) == frozenset({(1, 0)})
    assert map_.topology.neighbors((1, 0)) == frozenset()
    assert map_.topology.portal_destination((0, 0)) == (1, 0)

    map_.topology.rebuild(wall=False, portal=False)

    assert map_.topology.neighbors((0, 0)) == frozenset({(1, 0)})
    assert map_.topology.neighbors((1, 0)) == frozenset({(0, 0)})


def test_pathfinder_uses_portal_segments_without_clicking_the_portal_exit() -> None:
    map_ = _synthetic_map()
    map_.topology.configure(
        walls=(((0, 0), (1, 0)),),
        portals=(((0, 1), (2, 0)),),
    )
    map_.topology.rebuild(wall=True, portal=True)

    map_.pathfinder.project((0, 0), has_ambush=False)

    assert map_[(2, 1)].cost == 3
    assert map_.pathfinder.route((2, 1), step=1) == [(0, 1), (2, 1)]


def test_pathfinder_projects_enemy_cost_but_does_not_walk_through_it() -> None:
    map_ = _synthetic_map("C1")
    map_.topology.rebuild()
    map_[(1, 0)].is_enemy = True

    map_.pathfinder.project((0, 0), has_ambush=False)

    assert map_[(1, 0)].cost == 1
    assert map_[(2, 0)].cost == 9999

    map_.pathfinder.project((0, 0), has_ambush=False, has_enemy=False)

    assert map_[(2, 0)].cost == 2


def test_pathfinder_keeps_each_fleet_cost_and_the_current_projection() -> None:
    map_ = _synthetic_map("C1")
    map_.topology.rebuild()

    map_.pathfinder.project_fleets(
        {1: (0, 0), 2: (2, 0)},
        current=(2, 0),
        has_ambush=False,
    )

    assert [grid.cost_1 for grid in map_] == [0, 1, 2]
    assert [grid.cost_2 for grid in map_] == [2, 1, 0]
    assert [grid.cost for grid in map_] == [2, 1, 0]
    assert map_.pathfinder.route((0, 0)) == [(0, 0)]


def test_pathfinder_finds_the_weighted_shortest_path_deterministically() -> None:
    map_ = _synthetic_map("C3")
    map_.topology.rebuild()
    for location in ((1, 0), (1, 1), (2, 0)):
        map_[location].may_ambush = True

    map_.pathfinder.project((0, 0))

    assert map_[(2, 0)].cost == 15
    assert map_.pathfinder.route((2, 0), step=1) == [
        (0, 1),
        (0, 2),
        (1, 2),
        (2, 2),
        (2, 1),
        (2, 0),
    ]


def test_equal_cost_route_prefers_a_horizontal_final_step() -> None:
    map_ = _synthetic_map("B2")
    map_.topology.rebuild()

    map_.pathfinder.project((0, 0), has_ambush=False)

    assert map_.pathfinder.route((1, 1), step=1) == [(0, 1), (1, 1)]
    assert map_.pathfinder.route((1, 1), turning_optimize=True) == [(0, 1), (1, 1)]
