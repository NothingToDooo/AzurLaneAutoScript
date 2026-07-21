from typing import TYPE_CHECKING, override

import module.map.fleet as fleet_module
from module.map.fleet import Fleet
from module.map.fleet_turn import FleetTurnController, FleetTurnRules
from module.map.map_base import CampaignMap
from module.map.map_observer import STANDARD_CAMPAIGN_MAP_OBSERVER, CampaignMapObserver
from module.map.map_scanner import MovableEnemySnapshot
from module.map_detection.grid import Grid

if TYPE_CHECKING:
    from module.base.type_alias import Point
    from module.combat.combat import CombatEnd
    from module.map.map_observer import MapObserverRuntime
    from module.map.type_alias import GridLocation
    from module.map_detection.grid_info import GridInfo


class _Config:
    Submarine_Mode = "do_not_use"
    MAP_FOCUS_ENEMY_AFTER_BATTLE = False
    MAP_HAS_BOUNCING_ENEMY = False
    MAP_HAS_LAND_BASED = False
    MAP_HAS_MAZE = False
    MAP_HAS_MOVABLE_ENEMY = False
    submarine = False


class _LocalGrid(Grid):
    def __init__(self) -> None:
        pass

    @override
    def predict_fleet(self) -> bool:
        return True

    @override
    def predict_current_fleet(self) -> bool:
        return True


class _RecordingObserver:
    def __init__(self) -> None:
        self.calls: list[tuple[MapObserverRuntime, GridInfo, int, bool]] = []

    def camera_repositioned_after_combat(
        self,
        runtime: MapObserverRuntime,
        destination: GridInfo,
    ) -> bool:
        self.calls.append(
            (
                runtime,
                destination,
                runtime.battle_count,
                destination.is_cleared,
            )
        )
        destination.is_fortress = True
        return False


class _CombatFleet(Fleet):
    config: _Config

    def __init__(self, observer: CampaignMapObserver) -> None:
        self.config = _Config()
        self.map = CampaignMap("fleet-observer-test")
        self.map.layout.initialize("A1")
        self.map.spawn_data = []
        self._turn_controller = FleetTurnController(FleetTurnRules(), self.map)
        self._map_observer = observer
        self.battle_count = 0
        self.fleet_ammo = 5
        self.siren_count = 0
        self._hp = {self.fleet_current_index: [1.0]}

    @override
    def combat_appear(self) -> bool:
        return True

    @override
    def combat(
        self,
        *,
        balance_hp: bool | None = None,
        emotion_reduce: bool | None = None,
        submarine_mode: str | None = None,
        expected_end: CombatEnd | None = None,
        fleet_index: int = 1,
    ) -> None:
        del balance_hp, emotion_reduce, submarine_mode, expected_end, fleet_index

    @override
    def hp_get(self) -> list[float]:
        return self.hp

    @override
    def lv_get(self, *, after_battle: bool = False) -> None:
        del after_battle

    @override
    def convert_global_to_local(self, location: GridInfo | str | Point) -> _LocalGrid:
        del location
        return _LocalGrid()

    def run_combat_at(self, location: GridLocation) -> None:
        state = self._goto_state(
            fleet_module._GotoRequest(  # ruff:ignore[private-member-access] - 构造真实导航状态以测试战斗观测顺序。
                location=location,
                expected="combat",
                portal_destination=None,
                may_submarine_icon=False,
                movable_snapshot=MovableEnemySnapshot(),
            ),
            _LocalGrid(),
        )
        self._goto_handle_combat(state)


def test_combat_observer_receives_and_mutates_the_exact_destination_grid() -> None:
    observer = _RecordingObserver()
    fleet = _CombatFleet(
        CampaignMapObserver(
            combat=observer,
            scanner=STANDARD_CAMPAIGN_MAP_OBSERVER.scanner,
            enemy_searching=STANDARD_CAMPAIGN_MAP_OBSERVER.enemy_searching,
            viewport=STANDARD_CAMPAIGN_MAP_OBSERVER.viewport,
            fleet_locator=STANDARD_CAMPAIGN_MAP_OBSERVER.fleet_locator,
            preparation=STANDARD_CAMPAIGN_MAP_OBSERVER.preparation,
        )
    )
    destination = fleet.map[(0, 0)]
    destination.may_enemy = True

    fleet.run_combat_at((0, 0))

    assert len(observer.calls) == 1
    observed_runtime, observed_destination, observed_battle_count, observed_cleared = observer.calls[0]
    assert observed_runtime is fleet
    assert observed_destination is destination
    assert observed_battle_count == 1
    assert observed_cleared
    assert destination.is_cleared
    assert destination.is_fortress
