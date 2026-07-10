"""旧 Windows 平台导入的单向兼容层。"""

from module.device.runtime import (
    EmulatorUnknown,
    MumuRuntime,
    flash_window,
    get_focused_window,
    get_window_title,
    minimize_window,
    set_focus_window,
)


class PlatformWindows(MumuRuntime):
    """兼容旧类名；不再继承 Connection。"""


__all__ = [
    "EmulatorUnknown",
    "PlatformWindows",
    "flash_window",
    "get_focused_window",
    "get_window_title",
    "minimize_window",
    "set_focus_window",
]
