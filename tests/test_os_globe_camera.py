from typing import ClassVar, TypeVar

import pytest

from module.exception import GameStuckError
from module.os import globe_camera as globe_camera_module
from module.os.globe_camera import GlobeCamera

_T = TypeVar("_T")


def button_key(button: object) -> str:
    return str(getattr(button, "name", repr(button)))


class _Timer:
    next_index: ClassVar[int] = 0
    reached_results: ClassVar[dict[int, list[bool]]] = {}
    reset_count: ClassVar[int] = 0

    def __init__(self, *_args: object, **_kwargs: object) -> None:
        self.index = _Timer.next_index
        _Timer.next_index += 1

    def start(self) -> _Timer:
        return self

    def reached(self) -> bool:
        results = _Timer.reached_results.get(self.index)
        if results:
            return results.pop(0)
        return False

    def reset(self) -> _Timer:
        _Timer.reset_count += 1
        return self


class _Device:
    def __init__(self) -> None:
        self.image = object()
        self.screenshot_count = 0
        self.clicks: list[object] = []

    def screenshot(self) -> None:
        self.screenshot_count += 1

    def click(self, button: object) -> None:
        self.clicks.append(button)


class _Zone:
    zone_id = 42


class _Globe:
    center_loca = (12, 34)

    def __init__(self) -> None:
        self.loaded_images: list[object] = []

    def load(self, image: object) -> None:
        self.loaded_images.append(image)


class _GlobeCamera(GlobeCamera):
    device: _Device
    globe: _Globe

    def __init__(self) -> None:
        self.device = _Device()
        self.calls: list[tuple[object, ...]] = []
        self.in_globe_results: list[bool] = []
        self.appear_then_click_results: dict[str, list[bool]] = {}
        self.appear_results: dict[str, list[bool]] = {}
        self.map_event_results: list[bool] = []
        self.popup_results: list[bool] = []

    def update_globe(self) -> None:
        self.globe_update()

    @staticmethod
    def _next_result(results: list[_T], *, default: _T) -> _T:
        if results:
            return results.pop(0)
        return default

    def _globe_init(self) -> None:
        self.calls.append(("_globe_init",))
        if not hasattr(self, "globe"):
            self.globe = _Globe()

    def is_in_globe(self) -> bool:
        self.calls.append(("is_in_globe",))
        return self._next_result(self.in_globe_results, default=False)

    def appear_then_click(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear_then_click", key, kwargs))
        return self._next_result(self.appear_then_click_results.get(key, []), default=False)

    def appear(self, button: object, *_args: object, **kwargs: object) -> bool:
        key = button_key(button)
        self.calls.append(("appear", key, kwargs))
        return self._next_result(self.appear_results.get(key, []), default=False)

    def interval_reset(self, button: object, *_args: object, **_kwargs: object) -> None:
        self.calls.append(("interval_reset", button_key(button)))

    def handle_map_event(self) -> bool:
        self.calls.append(("handle_map_event",))
        return self._next_result(self.map_event_results, default=False)

    def handle_popup_confirm(self, name: str = "", *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self._next_result(self.popup_results, default=False)

    def camera_to_zone(self, camera: object, region: int | None = None) -> _Zone:
        if region is None:
            self.calls.append(("camera_to_zone", camera))
        else:
            self.calls.append(("camera_to_zone", camera, region))
        return _Zone()


@pytest.fixture(autouse=True)
def _patch_timer(monkeypatch: pytest.MonkeyPatch) -> None:
    _Timer.next_index = 0
    _Timer.reached_results = {}
    _Timer.reset_count = 0
    monkeypatch.setattr(globe_camera_module, "Timer", _Timer)


def test_globe_update_loads_camera_when_already_in_globe() -> None:
    camera = _GlobeCamera()
    camera.in_globe_results = [True]

    camera.update_globe()

    assert camera.device.screenshot_count == 1
    assert camera.globe_camera == _Globe.center_loca
    assert camera.globe.loaded_images == [camera.device.image]
    assert ("camera_to_zone", _Globe.center_loca) in camera.calls
    assert _Timer.reset_count == 0


def test_globe_update_clicks_goto_and_resets_timeout() -> None:
    camera = _GlobeCamera()
    camera.in_globe_results = [False, True]
    camera.appear_then_click_results[button_key(globe_camera_module.MAP_GOTO_GLOBE)] = [True]

    camera.update_globe()

    assert camera.device.screenshot_count == 2
    assert _Timer.reset_count == 1
    assert (
        "appear",
        button_key(globe_camera_module.MAP_GOTO_GLOBE_FOG),
        {"interval": 3},
    ) in camera.calls
    assert camera.globe_camera == _Globe.center_loca


def test_globe_update_cancels_action_point_popup() -> None:
    camera = _GlobeCamera()
    camera.in_globe_results = [False, True]
    camera.appear_results[button_key(globe_camera_module.ACTION_POINT_USE)] = [True]

    camera.update_globe()

    assert camera.device.clicks == [globe_camera_module.ACTION_POINT_CANCEL]
    assert _Timer.reset_count == 1


def test_globe_update_raises_when_globe_never_recovers() -> None:
    camera = _GlobeCamera()
    camera.in_globe_results = [False]
    _Timer.reached_results = {0: [False, True]}

    with pytest.raises(GameStuckError):
        camera.update_globe()

    assert not hasattr(camera, "globe")
