import os

import cv2

from module.base.utils import crop, image_size


class ImageError(Exception):
    """解析图片时发生错误。"""


class ImageInvalidResolution(ImageError):
    """图片不是 1280x720 或其纵向拼接尺寸。"""


def load_folder(folder, ext=".png"):
    """
    Args:
        folder (str): Template folder contains images.
            Image shape: width=96, height=96, channel=3, format=png.
            Image name: Camel-Case, such as 'PlateGeneralT3'. Suffix in name will be ignore.
            For example, 'Javelin' and 'Javelin_2' are different templates, but have same output name 'Javelin'.
        ext (str): File extension.

    Returns:
        dict: Key: str, image file base name. Value: full filepath.
    """
    if not os.path.exists(folder):
        return {}

    out = {}
    for file in os.listdir(folder):
        name, extension = os.path.splitext(file)
        if extension == ext:
            out[name] = os.path.join(folder, file)

    return out


def pack(img_list):
    """
    Stack images vertically.

    Args:
        img_list (list): List of image

    Returns:
        np.ndarray:
    """
    return cv2.vconcat(img_list)


def unpack(image):
    """
    按 720 像素高度纵向拆分图片。

    Args:
        image:

    Returns:
        list: np.ndarray 列表。
    """
    size = image_size(image)
    if size == (1280, 720):
        return [image]
    if size[0] != 1280 or size[1] % 720 != 0:
        raise ImageInvalidResolution(f"Unexpected image size: {size}")
    return [crop(image, (0, n * 720, 1280, (n + 1) * 720)) for n in range(size[1] // 720)]
