"""Windows 平台入口，当前个人分支只暴露 MuMu 平台实现。"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from module.device.platform.platform_windows import PlatformWindows as Platform

__all__ = ["Platform"]


def __getattr__(name: str):
    """延迟解析旧 Platform 导出，避免平台包初始化时反向导入 runtime。"""
    if name != "Platform":
        message = f"module {__name__!r} has no attribute {name!r}"
        raise AttributeError(message)

    from module.device.platform.platform_windows import PlatformWindows  # noqa: PLC0415

    return PlatformWindows
