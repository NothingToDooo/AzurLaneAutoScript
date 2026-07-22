from module.combat.hp_balancer import HPBalancer


class _HPBalancer(HPBalancer):
    def exchange_steps(self, target: list[int]) -> list[tuple[int, int]]:
        return list(self._gen_exchange_step(target))

    def initialize_hp_cache(self) -> None:
        self._hp = {}
        self._hp_has_ship = {}

    def hp_cache(self) -> tuple[dict[int, list[float]], dict[int, list[bool]]]:
        return self._hp, self._hp_has_ship


def test_exchange_steps_use_minitouch_drag_order_for_three_ship_rotation() -> None:
    balancer = object.__new__(_HPBalancer)

    assert balancer.exchange_steps([2, 0, 1]) == [(2, 0)]
    assert balancer.exchange_steps([1, 2, 0]) == [(0, 2)]


def test_exchange_steps_use_direct_swap_for_two_misplaced_ships() -> None:
    balancer = object.__new__(_HPBalancer)

    assert balancer.exchange_steps([0, 2, 1]) == [(1, 2)]
    assert balancer.exchange_steps([0, 1, 2]) == []


def test_non_map_hp_cache_uses_fleet_1_policy() -> None:
    balancer = object.__new__(_HPBalancer)
    balancer.initialize_hp_cache()
    hp = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4]
    has_ship = [True, True, False, True, False, True]

    balancer.hp = hp
    balancer.hp_has_ship = has_ship

    assert balancer.hp == hp
    assert balancer.hp_has_ship == has_ship
    assert balancer.hp_cache() == ({1: hp}, {1: has_ship})
