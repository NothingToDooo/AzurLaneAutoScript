"""旧平台基类导入的单向兼容层。"""

from module.device.mumu_runtime_base import serial_to_id
from module.device.runtime import MumuRuntime


class PlatformBase(MumuRuntime):
    """兼容旧类名；不再继承 Connection。"""


__all__ = ["PlatformBase", "serial_to_id"]
