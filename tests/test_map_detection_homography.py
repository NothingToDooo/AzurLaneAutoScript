from types import SimpleNamespace
from typing import TYPE_CHECKING, cast

import numpy as np
import pytest

from module.exception import MapDetectionError
from module.map_detection.homography import NO_HOMOGRAPHY_INPUT_MESSAGE, Homography

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig


def _homography() -> Homography:
    config = SimpleNamespace(
        DETECTING_AREA=(100, 50, 300, 150),
        HOMO_TILE=(20, 10),
    )
    return Homography(cast("AzurLaneConfig", config))


def test_find_homography_recovers_identity_transform_for_rectangular_grid() -> None:
    homography = _homography()
    source_corners = [(100, 50), (300, 50), (100, 150), (300, 150)]

    homography.find_homography((10, 10), source_corners)

    assert homography.homo_loaded
    assert homography.homo_storage == ((10, 10), source_corners)
    assert homography.homo_size == (200, 100)
    np.testing.assert_allclose(homography.homo_data, np.eye(3), atol=1e-6)
    np.testing.assert_allclose(homography.homo_invt, np.eye(3), atol=1e-6)


def test_find_homography_overflow_keeps_full_transform_while_inner_mode_crops() -> None:
    source_corners = [(120, 60), (280, 60), (100, 140), (300, 140)]
    overflow_homography = _homography()
    inner_homography = _homography()

    overflow_homography.find_homography((10, 10), source_corners, overflow=True)
    inner_homography.find_homography((10, 10), source_corners, overflow=False)

    assert overflow_homography.homo_size[0] > inner_homography.homo_size[0]
    assert overflow_homography.homo_size[1] == inner_homography.homo_size[1]
    assert overflow_homography.homo_data[0, 2] == pytest.approx(0, abs=1e-6)
    assert inner_homography.homo_data[0, 2] < -1
    np.testing.assert_allclose(
        overflow_homography.homo_data @ overflow_homography.homo_invt,
        np.eye(3),
        atol=1e-6,
    )
    np.testing.assert_allclose(
        inner_homography.homo_data @ inner_homography.homo_invt,
        np.eye(3),
        atol=1e-6,
    )


def test_load_homography_accepts_storage_and_rejects_missing_input() -> None:
    homography = _homography()
    storage = ((10, 10), [(100, 50), (300, 50), (100, 150), (300, 150)])

    homography.load_homography(storage=storage)

    assert homography.homo_loaded
    with pytest.raises(MapDetectionError, match=NO_HOMOGRAPHY_INPUT_MESSAGE):
        _homography().load_homography()
