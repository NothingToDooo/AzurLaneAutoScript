from typing import TYPE_CHECKING

import numpy as np

from module.map_detection.perspective import LineDetectionOptions, Perspective
from module.map_detection.utils import Lines

if TYPE_CHECKING:
    import pytest

    from module.base.type_alias import ImageArray
    from module.config.config_manual import FindPeaksParameter


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
