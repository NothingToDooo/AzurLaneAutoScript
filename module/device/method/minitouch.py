"""旧 minitouch 导入路径的单向兼容层。"""

from module.device.minitouch_service import (
    MINITOUCH_EMPTY_DATA_MESSAGE,
    MINITOUCH_OCCUPIED_MESSAGE,
    Command,
    CommandBuilder,
    MinitouchController,
    MinitouchNotInstalledError,
    MinitouchOccupiedError,
    insert_swipe,
    random_normal_distribution,
    random_rho,
    random_theta,
    retry,
)


class Minitouch(MinitouchController):
    """兼容旧类名；不再继承 Connection。"""


__all__ = [
    "MINITOUCH_EMPTY_DATA_MESSAGE",
    "MINITOUCH_OCCUPIED_MESSAGE",
    "Command",
    "CommandBuilder",
    "Minitouch",
    "MinitouchController",
    "MinitouchNotInstalledError",
    "MinitouchOccupiedError",
    "insert_swipe",
    "random_normal_distribution",
    "random_rho",
    "random_theta",
    "retry",
]
