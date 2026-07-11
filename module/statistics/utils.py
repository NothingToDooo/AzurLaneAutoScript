from pathlib import Path

import cv2

from module.base.utils import crop, image_size


class ImageError(Exception):
    """解析图片时发生错误。"""


class ImageInvalidResolution(ImageError):
    """图片不是 1280x720 或其纵向拼接尺寸。"""


UNEXPECTED_IMAGE_SIZE_TEMPLATE = "Unexpected image size: {size}"


def load_folder(folder, ext=".png"):
    """返回目录中指定扩展名的 {文件名: 路径} 映射；目录不存在时返回空字典。"""
    if not Path(folder).exists():
        return {}

    out = {}
    for path in Path(folder).iterdir():
        if path.suffix == ext:
            out[path.stem] = path.as_posix()

    return out


def pack(img_list):
    """纵向拼接图像列表。"""
    return cv2.vconcat(img_list)


def unpack(image):
    """按 720 像素高度拆分 1280 宽图片；尺寸不符时抛出 ImageInvalidResolution。"""
    size = image_size(image)
    if size == (1280, 720):
        return [image]
    if size[0] != 1280 or size[1] % 720 != 0:
        message = UNEXPECTED_IMAGE_SIZE_TEMPLATE.format(size=size)
        raise ImageInvalidResolution(message)
    return [crop(image, (0, n * 720, 1280, (n + 1) * 720)) for n in range(size[1] // 720)]
