from datetime import datetime
from typing import TYPE_CHECKING

from module.config.utils import filepath_config, read_file, write_file

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.config.deep import MutableDeepData, MutableDeepValue


def iter_config_save_updates(key: str) -> Iterable[tuple[str, MutableDeepValue]]:
    """Emotion 的 `*Value` 变化时产出对应记录时间。"""

    if "Emotion" in key and "Value" in key:
        keys = key.split(".")
        keys[-1] = keys[-1].replace("Value", "Record")
        yield ".".join(keys), datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def read_config_file(config_name: str) -> MutableDeepData:
    """读取当前配置文件；完整 schema 校验由 compiler 边界负责。"""

    return read_file(filepath_config(config_name))


def write_config_file(config_name: str, data: MutableDeepData) -> None:
    """以当前 JSON 格式原子写入配置文件。"""

    write_file(filepath_config(config_name), data)
