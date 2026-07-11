from typing import TYPE_CHECKING

import numpy as np

from module.research import series

if TYPE_CHECKING:
    import pytest

    from module.base.type_alias import ImageArray


class _FakeTemplate:
    def __init__(self, *, result: bool) -> None:
        self.result = result
        self.calls: list[tuple[ImageArray, float]] = []

    def match(self, image: ImageArray, *, scaling: float) -> bool:
        self.calls.append((image, scaling))
        return self.result


def test_match_series_returns_first_matching_series(monkeypatch: pytest.MonkeyPatch) -> None:
    image = np.zeros((1, 1, 3), dtype=np.uint8)
    gray = np.zeros((1, 1), dtype=np.uint8)
    miss = _FakeTemplate(result=False)
    hit = _FakeTemplate(result=True)
    skipped = _FakeTemplate(result=True)
    monkeypatch.setattr(series, "rgb2gray", lambda _image: gray)
    monkeypatch.setattr(series, "RESEARCH_SERIES_TEMPLATES", ((miss, 8), (hit, 4), (skipped, 5)))

    assert series.match_series(image, scaling=0.75) == 4
    assert miss.calls == [(gray, 0.75)]
    assert hit.calls == [(gray, 0.75)]
    assert skipped.calls == []


def test_match_series_returns_zero_without_match(monkeypatch: pytest.MonkeyPatch) -> None:
    image = np.zeros((1, 1, 3), dtype=np.uint8)
    first = _FakeTemplate(result=False)
    second = _FakeTemplate(result=False)
    monkeypatch.setattr(series, "rgb2gray", lambda image: image)
    monkeypatch.setattr(series, "RESEARCH_SERIES_TEMPLATES", ((first, 8), (second, 7)))

    assert series.match_series(image, scaling=1.0) == 0
    assert first.calls == [(image, 1.0)]
    assert second.calls == [(image, 1.0)]
