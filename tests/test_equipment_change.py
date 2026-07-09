from module.equipment import equipment_change as equipment_change_module
from module.equipment.equipment_change import EquipmentChange


class _Device:
    def __init__(self) -> None:
        self.drags: list[tuple[object, object, tuple[int, int, int, int]]] = []
        self.sleeps: list[float] = []
        self.screenshots = 0

    def drag(self, p1: object, p2: object, *, point_random: tuple[int, int, int, int]) -> None:
        self.drags.append((p1, p2, point_random))

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)

    def screenshot(self) -> None:
        self.screenshots += 1


class _EquipmentChange(EquipmentChange):
    device: _Device

    def __init__(self) -> None:
        self.device = _Device()

    def equipment_swipe_once(self) -> None:
        self._equipment_swipe()


def test_equipment_swipe_uses_minitouch_default_distance(monkeypatch) -> None:
    calls: list[tuple[object, object, object]] = []

    def random_vector(vector: object, *, box: object, random_range: object):
        calls.append((vector, box, random_range))
        return (1, 2), (3, 4)

    monkeypatch.setattr(equipment_change_module, "random_rectangle_vector", random_vector)
    equipment = _EquipmentChange()

    equipment.equipment_swipe_once()

    assert calls == [((0, -190), (620, 67, 1154, 692), (-20, -5, 20, 5))]
    assert equipment.device.drags == [((1, 2), (3, 4), (0, 0, 0, 0))]
    assert equipment.device.sleeps == [0.3]
    assert equipment.device.screenshots == 1
