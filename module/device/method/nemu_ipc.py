"""旧 nemu_ipc 导入路径的单向兼容层。"""

from module.device.nemu_ipc_service import (
    NEMU_IPC_CONNECT_FAILED_MESSAGE,
    NEMU_IPC_GET_RESOLUTION_FAILED_MESSAGE,
    NEMU_IPC_INSTANCE_DEAD_MESSAGE,
    NEMU_IPC_MIN_VERSION_MESSAGE,
    NEMU_IPC_SCREENSHOT_FAILED_MESSAGE,
    CaptureNemuIpc,
    CaptureStd,
    NemuIpcCapture,
    NemuIpcError,
    NemuIpcImpl,
    NemuIpcIncompatible,
    retry,
)


class NemuIpc(NemuIpcCapture):
    """兼容旧类名；不再继承平台或 Connection。"""


__all__ = [
    "NEMU_IPC_CONNECT_FAILED_MESSAGE",
    "NEMU_IPC_GET_RESOLUTION_FAILED_MESSAGE",
    "NEMU_IPC_INSTANCE_DEAD_MESSAGE",
    "NEMU_IPC_MIN_VERSION_MESSAGE",
    "NEMU_IPC_SCREENSHOT_FAILED_MESSAGE",
    "CaptureNemuIpc",
    "CaptureStd",
    "NemuIpc",
    "NemuIpcCapture",
    "NemuIpcError",
    "NemuIpcImpl",
    "NemuIpcIncompatible",
    "retry",
]
