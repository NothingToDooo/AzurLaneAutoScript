from typing import Protocol


class StopEvent(Protocol):
    """跨线程或跨进程停止信号。"""

    def set(self) -> None:
        """请求停止。"""

    def is_set(self) -> bool:
        """返回是否已经请求停止。"""
