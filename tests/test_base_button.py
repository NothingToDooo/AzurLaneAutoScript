import pytest

from module.base.button import Button


def test_click_only_button_exposes_only_click_area() -> None:
    button = Button(area=(), color=(), button=(10, 20, 30, 40), name="click_only")

    assert button.button == (10, 20, 30, 40)
    with pytest.raises(ValueError, match="detection color"):
        _ = button.color
    with pytest.raises(ValueError, match="detection area"):
        _ = button.area


def test_detection_only_button_exposes_no_click_area() -> None:
    button = Button(area=(10, 20, 30, 40), color=(1, 2, 3), button=(), name="detection_only")

    assert button.area == (10, 20, 30, 40)
    assert button.color == (1, 2, 3)
    with pytest.raises(ValueError, match="clickable area"):
        _ = button.button
