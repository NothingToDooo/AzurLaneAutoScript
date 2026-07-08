"""Windows 平台入口，当前个人分支只暴露 MuMu 平台实现。"""

from module.device.platform.platform_windows import PlatformWindows as Platform

__all__ = ["Platform"]
