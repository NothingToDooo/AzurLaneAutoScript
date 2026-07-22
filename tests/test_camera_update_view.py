from types import SimpleNamespace
from typing import TYPE_CHECKING, Unpack, override

import numpy as np
import pytest

import module.map.camera as camera_module
from module.exception import CampaignEnd, GameNotRunningError, MapDetectionError
from module.map.camera import Camera

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.base.button import Button, MatchOffset
    from module.base.type_alias import Area, ImageArray, Point
    from module.device.control import ButtonTarget
    from module.ui.ui import CheckButton, UiClickOptions, UiClickOptionSettings


class _View:
    def __init__(self, *, error: MapDetectionError | None = None) -> None:
        self.error = error
        self.loaded_images: list[ImageArray] = []
        self.updated_images: list[ImageArray] = []
        self.center_offset = (0.5, 0.5)

    def load(self, image: ImageArray) -> None:
        self.loaded_images.append(image)
        if self.error is not None:
            raise self.error

    def update(self, *, image: ImageArray) -> None:
        self.updated_images.append(image)


class _Device:
    def __init__(self) -> None:
        self.image = np.zeros((1, 1, 3), dtype=np.uint8)
        self.clicked: list[ButtonTarget] = []
        self.is_running = True
        self.screenshot_count = 0
        self.interval_clear_count = 0

    def click(self, button: ButtonTarget) -> None:
        self.clicked.append(button)

    def app_is_running(self) -> bool:
        return self.is_running

    def screenshot_interval_clear(self) -> None:
        self.interval_clear_count += 1

    def screenshot(self) -> None:
        self.screenshot_count += 1


class _Camera(Camera):
    _auto_search_menu_offset = (1, 2, 3, 4)
    device: _Device
    view: _View
    config: SimpleNamespace

    def __init__(self, *, view_error: MapDetectionError | None = None, command: str = "Main") -> None:
        self.device = _Device()
        self.view = _View(error=view_error)
        self.config = SimpleNamespace(task=SimpleNamespace(command=command))
        self.info_bar_visible = False
        self.stage_visible = False
        self.story_visible = False
        self.popup_confirmed = False
        self.visible_assets: list[Button] = []
        self.calls = []
        self.swipes = []

    def _view_init(self) -> None:
        self.calls.append(("view_init",))

    def _ensure_image_detectable(self) -> None:
        self.calls.append(("ensure_detectable",))

    def info_bar_count(self) -> bool:
        return self.info_bar_visible

    @override
    def handle_info_bar(self) -> bool:
        self.calls.append(("handle_info_bar",))
        return True

    @override
    def appear(
        self,
        button: Button,
        offset: MatchOffset | None = 0,
        interval: float = 0,
        similarity: float = 0.85,
        threshold: int = 10,
    ) -> bool:
        del interval, similarity, threshold
        self.calls.append(("appear", button, offset))
        return any(button is visible for visible in self.visible_assets)

    def handle_story_skip(self) -> bool:
        self.calls.append(("handle_story_skip",))
        return self.story_visible

    @override
    def ensure_no_story(self, *, skip_first_screenshot: bool = True) -> None:
        self.calls.append(("ensure_no_story", skip_first_screenshot))

    def is_in_stage(self) -> bool:
        self.calls.append(("is_in_stage",))
        return self.stage_visible

    @override
    def enter_map_cancel(self, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("enter_map_cancel",))
        return True

    @override
    def ensure_auto_search_exit(self, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("ensure_auto_search_exit",))
        return True

    def is_in_map(self) -> bool:
        self.calls.append(("is_in_map",))
        return True

    @override
    def ui_click(
        self,
        click_button: ButtonTarget,
        check_button: CheckButton,
        options: UiClickOptions | None = None,
        **settings: Unpack[UiClickOptionSettings],
    ) -> None:
        kwargs = dict(settings)
        if check_button is not None:
            kwargs["check_button"] = check_button
        if options is not None:
            kwargs["options"] = options
        self.calls.append(("ui_click", click_button, kwargs))

    def handle_popup_confirm(self, name: str = "", *_args: object, **_kwargs: object) -> bool:
        self.calls.append(("handle_popup_confirm", name))
        return self.popup_confirmed

    @override
    def _map_swipe(self, vector: Point, box: Area | None = None) -> bool:
        del box
        self.swipes.append(tuple(vector))
        return True

    def update_view_for_test(self) -> bool:
        return self._update_view()


class _CameraWithOsQuit(_Camera):
    def os_auto_search_quit(self) -> None:
        self.calls.append(("os_auto_search_quit",))

    def os_mission_quit(self) -> None:
        self.calls.append(("os_mission_quit",))


class _UpdateCamera(_Camera):
    def __init__(self, *, update_results: Iterable[bool | BaseException], command: str = "Main") -> None:
        super().__init__(command=command)
        self.update_results = list(update_results)
        self.view_data_update_count = 0

    @override
    def _update_view(self) -> bool:
        result = self.update_results.pop(0)
        if isinstance(result, BaseException):
            raise result
        return result

    def _update_view_data(self) -> bool:
        self.view_data_update_count += 1
        return True


def _failing_camera(*, message: str = "perspective error", command: str = "Main") -> _Camera:
    return _Camera(view_error=MapDetectionError(message), command=command)


def test_update_view_loads_detectable_image() -> None:
    camera = _Camera()

    assert camera.update_view_for_test() is True

    assert camera.view.loaded_images == [camera.device.image]
    assert camera.calls == [("view_init",), ("ensure_detectable",)]


def test_update_view_handles_info_bar_before_terminal_stage() -> None:
    camera = _failing_camera()
    camera.info_bar_visible = True
    camera.stage_visible = True

    assert camera.update_view_for_test() is False

    assert ("handle_info_bar",) in camera.calls
    assert ("is_in_stage",) not in camera.calls


@pytest.mark.parametrize(
    ("visible_asset", "offset", "clicked_button"),
    [
        (camera_module.GET_ITEMS_1, 5, camera_module.GET_ITEMS_1),
        (camera_module.GET_ITEMS_1_RYZA, (-20, -100, 20, 20), camera_module.GET_ITEMS_1_RYZA),
        (camera_module.GET_ADAPTABILITY, (20, 20), camera_module.GET_ADAPTABILITY),
        (camera_module.GET_MISSION, (20, 20), camera_module.GET_MISSION),
        (camera_module.PORT_SUPPLY_CHECK, (20, 20), camera_module.BACK_ARROW),
        (camera_module.GAME_TIPS, (20, 20), camera_module.GAME_TIPS),
    ],
)
def test_update_view_clicks_recoverable_overlay(
    visible_asset: Button,
    offset: MatchOffset,
    clicked_button: Button,
) -> None:
    camera = _failing_camera()
    camera.visible_assets.append(visible_asset)

    assert camera.update_view_for_test() is False

    assert ("appear", visible_asset, offset) in camera.calls
    assert camera.device.clicked == [clicked_button]


def test_update_view_clears_story_overlay() -> None:
    camera = _failing_camera()
    camera.story_visible = True

    assert camera.update_view_for_test() is False

    assert ("ensure_no_story", False) in camera.calls


@pytest.mark.parametrize(
    ("visible_asset", "expected_call", "message"),
    [
        (camera_module.MAP_PREPARATION, ("enter_map_cancel",), "MAP_PREPARATION"),
        (camera_module.AUTO_SEARCH_MENU_CONTINUE, ("ensure_auto_search_exit",), "auto search menu"),
    ],
)
def test_update_view_converts_terminal_campaign_screens_to_campaign_end(
    visible_asset: Button,
    expected_call: tuple[str],
    message: str,
) -> None:
    camera = _failing_camera()
    camera.visible_assets.append(visible_asset)

    with pytest.raises(CampaignEnd, match=message):
        camera.update_view_for_test()

    assert expected_call in camera.calls


def test_update_view_converts_stage_screen_to_campaign_end() -> None:
    camera = _failing_camera()
    camera.stage_visible = True

    with pytest.raises(CampaignEnd, match="Image is in stage"):
        camera.update_view_for_test()


def test_update_view_returns_false_after_globe_jump_click() -> None:
    camera = _failing_camera()
    camera.visible_assets.append(camera_module.GLOBE_GOTO_MAP)

    assert camera.update_view_for_test() is False

    [call] = [call for call in camera.calls if call[0] == "ui_click"]
    assert call[1] is camera_module.GLOBE_GOTO_MAP
    assert call[2]["check_button"] == camera.is_in_map
    assert call[2]["offset"] == (20, 20)
    assert call[2]["retry_wait"] == 3
    assert call[2]["skip_first_screenshot"] is True


def test_update_view_uses_os_auto_search_quit_when_available() -> None:
    camera = _CameraWithOsQuit(view_error=MapDetectionError("perspective error"), command="OpsiDaily")
    camera.visible_assets.append(camera_module.AUTO_SEARCH_REWARD)

    assert camera.update_view_for_test() is False

    assert ("os_auto_search_quit",) in camera.calls
    assert not [call for call in camera.calls if call[0] == "ui_click"]


def test_update_view_falls_back_to_clicking_auto_search_reward() -> None:
    camera = _failing_camera(command="OpsiDaily")
    camera.visible_assets.append(camera_module.AUTO_SEARCH_REWARD)

    assert camera.update_view_for_test() is False

    [call] = [call for call in camera.calls if call[0] == "ui_click"]
    assert call[1] is camera_module.AUTO_SEARCH_REWARD
    assert call[2]["offset"] == (50, 50)


def test_update_view_uses_os_mission_quit_when_available() -> None:
    camera = _CameraWithOsQuit(view_error=MapDetectionError("perspective error"), command="OpsiDaily")
    camera.visible_assets.append(camera_module.OPSI_MISSION_CHECK)

    assert camera.update_view_for_test() is False

    assert ("os_mission_quit",) in camera.calls
    assert not [call for call in camera.calls if call[0] == "ui_click"]


def test_update_view_confirms_opsi_popup_only_for_opsi_tasks() -> None:
    camera = _failing_camera(command="OpsiDaily")
    camera.popup_confirmed = True

    assert camera.update_view_for_test() is False

    assert ("handle_popup_confirm", "OPSI") in camera.calls


@pytest.mark.parametrize(
    "message",
    [
        f"{camera_module.CAMERA_OUTSIDE_MAP_MESSAGE}: offset=(2, -3)",
        f"{camera_module.CAMERA_OUTSIDE_MAP_MESSAGE} = (2, -3)",
    ],
)
def test_update_view_swipes_back_when_camera_is_outside_map(message: str) -> None:
    camera = _failing_camera(message=message)

    assert camera.update_view_for_test() is True

    assert camera.swipes == [(-2, 3)]


def test_update_view_raises_game_not_running() -> None:
    camera = _failing_camera()
    camera.device.is_running = False

    with pytest.raises(GameNotRunningError):
        camera.update_view_for_test()


def test_update_view_reraises_unhandled_detection_error() -> None:
    camera = _failing_camera()

    with pytest.raises(MapDetectionError, match="perspective error"):
        camera.update_view_for_test()


def test_update_image_only_without_camera_detection() -> None:
    camera = _UpdateCamera(update_results=[])

    assert camera.update(camera=False) is True

    assert camera.device.screenshot_count == 1
    assert camera.view.updated_images == [camera.device.image]
    assert camera.view_data_update_count == 0


def test_update_retries_after_recoverable_view_update() -> None:
    camera = _UpdateCamera(update_results=[False, True])

    assert camera.update() is True

    assert camera.device.screenshot_count == 2
    assert camera.view_data_update_count == 1


def test_update_allows_detection_error_and_still_refreshes_view_data() -> None:
    camera = _UpdateCamera(update_results=[MapDetectionError("temporary")])

    assert camera.update(allow_error=True) is True

    assert camera.device.screenshot_count == 1
    assert camera.view_data_update_count == 1
