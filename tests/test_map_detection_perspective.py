from typing import TYPE_CHECKING

import numpy as np
import pytest

from module.map_detection.perspective import LineDetectionOptions, Perspective
from module.map_detection.utils import Lines

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray
    from module.config.config_manual import FindPeaksParameter


@pytest.mark.parametrize(("is_horizontal", "line_index"), [(True, 3), (False, 4)])
def test_find_peaks_extracts_axis_aligned_ridge(*, is_horizontal: bool, line_index: int) -> None:
    image = np.zeros((7, 8), dtype=np.uint8)
    expected = np.zeros_like(image)
    if is_horizontal:
        image[line_index, :] = 200
        expected[line_index, :] = 255
    else:
        image[:, line_index] = 200
        expected[:, line_index] = 255

    result = Perspective.find_peaks(
        image,
        is_horizontal=is_horizontal,
        param={"height": 100, "distance": 2},
    )

    np.testing.assert_array_equal(result, expected)


def test_find_peaks_applies_mask() -> None:
    image = np.zeros((7, 8), dtype=np.uint8)
    image[3, :] = 200
    mask = np.full_like(image, 255)
    mask[3, 5:] = 0
    expected = np.zeros_like(image)
    expected[3, :5] = 255

    result = Perspective.find_peaks(
        image,
        is_horizontal=True,
        param={"height": 100, "distance": 2},
        mask=mask,
    )

    assert result.shape == image.shape
    np.testing.assert_array_equal(result, expected)


def test_find_peaks_padding_separates_flattened_scanlines() -> None:
    image = np.array(
        [
            [0, 200, 0],
            [0, 200, 0],
        ],
        dtype=np.uint8,
    )
    expected = np.array(
        [
            [0, 255, 0],
            [0, 255, 0],
        ],
        dtype=np.uint8,
    )

    result = Perspective.find_peaks(
        image,
        is_horizontal=False,
        param={"height": (100, 254), "distance": 4},
        pad=2,
    )

    np.testing.assert_array_equal(result, expected)


@pytest.mark.parametrize(("is_horizontal", "line_index"), [(True, 20), (False, 30)])
def test_hough_lines_detects_axis_aligned_line(*, is_horizontal: bool, line_index: int) -> None:
    image = np.zeros((64, 64), dtype=np.uint8)
    if is_horizontal:
        image[line_index, :] = 255
        expected_theta = np.pi / 2
    else:
        image[:, line_index] = 255
        expected_theta = 0.0

    lines = Perspective.hough_lines(
        image,
        is_horizontal=is_horizontal,
        threshold=50,
        theta=1,
    )

    assert lines.is_horizontal is is_horizontal
    np.testing.assert_allclose(lines.rho, [line_index], atol=0.5)
    np.testing.assert_allclose(lines.theta, [expected_theta], atol=np.deg2rad(0.5))


def test_hough_lines_rejects_line_from_other_orientation() -> None:
    image = np.zeros((64, 64), dtype=np.uint8)
    image[20, :] = 255

    lines = Perspective.hough_lines(
        image,
        is_horizontal=False,
        threshold=50,
        theta=1,
    )

    assert not lines


def test_detect_lines_forwards_detection_options(monkeypatch: pytest.MonkeyPatch) -> None:
    perspective = Perspective.__new__(Perspective)
    image = np.zeros((2, 2), dtype=np.uint8)
    peaks = np.ones((2, 2), dtype=np.uint8)
    lines = Lines(None, is_horizontal=True)
    find_peaks_calls: list[tuple[ImageArray, bool, dict[str, FindPeaksParameter], int, bool]] = []
    hough_lines_calls: list[tuple[ImageArray, bool, int, float]] = []

    def fake_find_peaks(
        source: ImageArray,
        *,
        is_horizontal: bool,
        param: dict[str, FindPeaksParameter],
        pad: int = 0,
        mask: ImageArray | None = None,
    ) -> ImageArray:
        find_peaks_calls.append((source, is_horizontal, param, pad, mask is not None))
        return peaks

    def fake_hough_lines(
        source: ImageArray,
        *,
        is_horizontal: bool,
        threshold: int,
        theta: float,
    ) -> Lines:
        hough_lines_calls.append((source, is_horizontal, threshold, theta))
        return lines

    monkeypatch.setattr(Perspective, "find_peaks", staticmethod(fake_find_peaks))
    monkeypatch.setattr(Perspective, "hough_lines", staticmethod(fake_hough_lines))

    result = perspective.detect_lines(
        image,
        LineDetectionOptions(
            is_horizontal=True,
            peak_params={"distance": 2},
            hough_threshold=40,
            theta_threshold=3.5,
            pad=8,
        ),
    )

    assert result is lines
    assert find_peaks_calls == [(image, True, {"distance": 2}, 8, True)]
    assert hough_lines_calls == [(peaks, True, 40, 3.5)]
