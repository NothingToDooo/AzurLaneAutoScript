from module.combat.hp_balancer import HPBalancer


class _HPBalancer(HPBalancer):
    def exchange_steps(self, target: list[int]) -> list[tuple[int, int]]:
        return list(self._gen_exchange_step(target))


def test_exchange_steps_use_minitouch_drag_order_for_three_ship_rotation() -> None:
    balancer = object.__new__(_HPBalancer)

    assert balancer.exchange_steps([2, 0, 1]) == [(2, 0)]
    assert balancer.exchange_steps([1, 2, 0]) == [(0, 2)]


def test_exchange_steps_use_direct_swap_for_two_misplaced_ships() -> None:
    balancer = object.__new__(_HPBalancer)

    assert balancer.exchange_steps([0, 2, 1]) == [(1, 2)]
    assert balancer.exchange_steps([0, 1, 2]) == []
