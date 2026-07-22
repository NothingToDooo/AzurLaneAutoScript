from typing import TYPE_CHECKING, cast

import cv2

from module.base.utils import crop, image_size
from module.project_paths import project_path

if TYPE_CHECKING:
    from collections.abc import Sequence

    from module.base.type_alias import FilePath, ImageArray


class ImageError(Exception):
    """解析图片时发生错误。"""


class InvalidImageResolutionError(ImageError):
    """图片不是 1280x720 或其纵向拼接尺寸。"""


UNEXPECTED_IMAGE_SIZE_TEMPLATE = "Unexpected image size: {size}"


def load_folder(folder: FilePath, ext: str = ".png") -> dict[str, str]:
    """返回目录中指定扩展名的 {文件名: 路径} 映射；目录不存在时返回空字典。"""
    folder_path = project_path(folder)
    if not folder_path.exists():
        return {}

    out: dict[str, str] = {}
    for path in folder_path.iterdir():
        if path.suffix == ext:
            out[path.stem] = path.as_posix()

    return out


def pack(img_list: Sequence[ImageArray]) -> ImageArray:
    """纵向拼接图像列表。"""
    return cast("ImageArray", cv2.vconcat(img_list))


def unpack(image: ImageArray) -> list[ImageArray]:
    """按 720 像素高度拆分 1280 宽图片；尺寸不符时抛出 InvalidImageResolutionError。"""
    size = image_size(image)
    if size == (1280, 720):
        return [image]
    if size[0] != 1280 or size[1] % 720 != 0:
        message = UNEXPECTED_IMAGE_SIZE_TEMPLATE.format(size=size)
        raise InvalidImageResolutionError(message)
    return [crop(image, (0, n * 720, 1280, (n + 1) * 720)) for n in range(size[1] // 720)]
