from module.device import control as control_module
from module.device.control import Control
from module.device.control_options import SwipeVectorOptions
from module.device.device import Device
from module.device.method.minitouch import Minitouch
from module.device.method.nemu_ipc import NemuIpc


class _Control(Control):
    def __init__(self) -> None:
        self.swipes: list[tuple[object, ...]] = []

    def swipe(self, p1, p2, duration=(0.1, 0.2), name="SWIPE", distance_check=True, **_kwargs: object) -> None:
        self.swipes.append((p1, p2, duration, name, distance_check))


def test_control_stack_uses_minitouch_without_nemu_ipc() -> None:
    assert Control.__bases__ == (Minitouch,)
    assert NemuIpc not in Control.__mro__


def test_release_during_wait_releases_nemu_ipc() -> None:
    calls: list[str] = []
    device = object.__new__(Device)

    def release() -> None:
        calls.append("released")

    device.nemu_ipc_release = release

    device.release_during_wait()

    assert calls == ["released"]


def test_swipe_vector_uses_options(monkeypatch) -> None:
    calls = []

    def random_path(vector, path_options):
        calls.append((vector, path_options))
        return (1, 2), (3, 4)

    monkeypatch.setattr(control_module, "random_rectangle_vector_opted", random_path)
    device = _Control()
    options = SwipeVectorOptions(
        box=(10, 20, 30, 40),
        random_range=(-1, -2, 1, 2),
        padding=0,
        duration=(0.3, 0.4),
        whitelist_area=[(1, 1, 2, 2)],
        blacklist_area=[(3, 3, 4, 4)],
        name="TEST_SWIPE",
        distance_check=False,
    )

    device.swipe_vector((5, 6), options)

    assert len(calls) == 1
    vector, path_options = calls[0]
    assert vector == (5, 6)
    assert path_options.box == (10, 20, 30, 40)
    assert path_options.random_range == (-1, -2, 1, 2)
    assert path_options.padding == 0
    assert path_options.whitelist_area == [(1, 1, 2, 2)]
    assert path_options.blacklist_area == [(3, 3, 4, 4)]
    assert device.swipes == [((1, 2), (3, 4), (0.3, 0.4), "TEST_SWIPE", False)]
