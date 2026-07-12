from typing import TYPE_CHECKING

import pytest

from module.device import control as control_module
from module.device.control import Control
from module.device.control_options import Duration, SwipeVectorOptions
from module.device.device import Device
from module.replay import ClickAction, RecordedAction, SwipeAction

if TYPE_CHECKING:
    from module.base.type_alias import Area, Point
    from module.base.utils import SwipePathOptions


class _Control(Control):
    def __init__(self) -> None:
        self.swipes: list[tuple[object, ...]] = []

    def swipe(
        self,
        p1: Point,
        p2: Point,
        duration: Duration = (0.1, 0.2),
        name: str = "SWIPE",
        *,
        distance_check: bool = True,
    ) -> None:
        self.swipes.append((p1, p2, duration, name, distance_check))


class _Button:
    button = (10, 20, 30, 40)

    def __init__(self, name: str) -> None:
        self.name = name

    def __str__(self) -> str:
        return self.name


class _RecordingControl(Control):
    def __init__(self) -> None:
        self.actions: list[RecordedAction] = []
        self.unsupported_actions: list[str] = []
        self.low_level_calls: list[tuple[object, ...]] = []
        self.fail_click = False

    def replay_record_action(self, action: RecordedAction) -> None:
        self.actions.append(action)

    def replay_mark_unsupported_action(self, action: str) -> None:
        self.unsupported_actions.append(action)

    def click_minitouch(self, x: int, y: int) -> None:
        if self.fail_click:
            message = "controller failed"
            raise RuntimeError(message)
        self.low_level_calls.append(("click", x, y))

    def long_click_minitouch(self, x: int, y: int, duration: float = 1.0) -> None:
        self.low_level_calls.append(("long_click", x, y, duration))

    def swipe_minitouch(self, p1: Point, p2: Point) -> None:
        self.low_level_calls.append(("swipe", p1, p2))

    def drag_minitouch(self, p1: Point, p2: Point, point_random: Area = (-10, -10, 10, 10)) -> None:
        self.low_level_calls.append(("drag", p1, p2, point_random))


def test_control_uses_explicit_controller_without_device_service_bases() -> None:
    assert Control.__bases__ == (object,)


def test_release_during_wait_releases_nemu_ipc() -> None:
    calls: list[str] = []
    device = object.__new__(Device)

    vars(device)["_runtime"] = type(
        "_Runtime",
        (),
        {"capture": type("_Capture", (), {"release": lambda _capture: calls.append("released")})()},
    )()

    device.release_during_wait()

    assert calls == ["released"]


def test_swipe_vector_uses_options(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = []

    def random_path(vector: Point, path_options: SwipePathOptions) -> tuple[Point, Point]:
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


def test_control_records_click_name_before_controller_call() -> None:
    control = _RecordingControl()
    button = _Button("POPUP_CONFIRM_REPLAY")

    control.click(button)
    button.name = "POPUP_CONFIRM"

    assert control.actions == [ClickAction(target="POPUP_CONFIRM_REPLAY")]
    assert control.low_level_calls[0][0] == "click"


def test_control_keeps_attempted_click_when_controller_fails() -> None:
    control = _RecordingControl()
    control.fail_click = True

    with pytest.raises(RuntimeError, match="controller failed"):
        control.click(_Button("CONFIRM"))

    assert control.actions == [ClickAction(target="CONFIRM")]


def test_control_records_only_swipes_that_are_sent() -> None:
    control = _RecordingControl()

    control.swipe((10, 20), (15, 25))
    control.swipe((10.9, 20.1), (30.8, 40.2))

    assert control.actions == [SwipeAction(start=(10, 20), end=(30, 40))]
    assert control.low_level_calls == [("swipe", (10, 20), (30, 40))]


def test_control_marks_long_click_and_drag_as_unsupported() -> None:
    control = _RecordingControl()

    control.long_click(_Button("HOLD"), duration=1)
    control.drag((10, 20), (30, 40), point_random=(0, 0, 0, 0))

    assert control.unsupported_actions == ["long_click", "drag"]
