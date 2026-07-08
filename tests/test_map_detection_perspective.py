from module.map_detection.perspective import LineDetectionOptions, Perspective


def test_detect_lines_forwards_detection_options(monkeypatch) -> None:
    perspective = Perspective.__new__(Perspective)
    calls = {}

    def fake_find_peaks(image, *, is_horizontal, param, pad=0, mask=None):
        calls["find_peaks"] = (image, is_horizontal, param, pad, mask is not None)
        return "peaks"

    def fake_hough_lines(self, image, *, is_horizontal, threshold, theta):
        calls["hough_lines"] = (self, image, is_horizontal, threshold, theta)
        return "lines"

    monkeypatch.setattr(Perspective, "find_peaks", staticmethod(fake_find_peaks))
    monkeypatch.setattr(Perspective, "hough_lines", fake_hough_lines)

    result = perspective.detect_lines(
        "image",
        LineDetectionOptions(
            is_horizontal=True,
            peak_params={"distance": 2},
            hough_threshold=40,
            theta_threshold=3.5,
            pad=8,
        ),
    )

    assert result == "lines"
    assert calls["find_peaks"] == ("image", True, {"distance": 2}, 8, True)
    assert calls["hough_lines"] == (perspective, "peaks", True, 40, 3.5)
