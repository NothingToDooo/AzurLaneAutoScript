import numpy as np

from module.base.utils import crop


def _rgb_image() -> np.ndarray:
    return np.arange(4 * 5 * 3, dtype=np.uint8).reshape((4, 5, 3))


def test_crop_inside_area_returns_copy_by_default() -> None:
    image = _rgb_image()

    result = crop(image, (1, 1, 4, 3))

    np.testing.assert_array_equal(result, image[1:3, 1:4])
    result[0, 0, 0] = 255
    assert image[1, 1, 0] != 255


def test_crop_inside_area_can_return_view() -> None:
    image = _rgb_image()

    result = crop(image, (1, 1, 3, 3), copy=False)

    result[0, 0, 0] = 255
    assert image[1, 1, 0] == 255


def test_crop_pads_partial_overflow_with_black_pixels() -> None:
    image = _rgb_image()

    result = crop(image, (-1, -2, 3, 2))
    expected = np.zeros((4, 4, 3), dtype=np.uint8)
    expected[2:4, 1:4] = image[0:2, 0:3]

    np.testing.assert_array_equal(result, expected)


def test_crop_returns_zero_image_when_color_area_is_outside() -> None:
    image = _rgb_image()

    result = crop(image, (5, 1, 7, 3))

    np.testing.assert_array_equal(result, np.zeros((2, 2, 3), dtype=np.uint8))


def test_crop_returns_zero_image_when_gray_area_is_outside() -> None:
    image = np.arange(4 * 5, dtype=np.uint8).reshape((4, 5))

    result = crop(image, (5, 1, 7, 3))

    np.testing.assert_array_equal(result, np.zeros((2, 2), dtype=np.uint8))
