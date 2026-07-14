from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from module.interaction import CancellationSignal


class CancellationAwareMumu12Device:
    """为现有 MuMu12 UI primitive 的每个公开 I/O 调用增加取消检查。"""

    __slots__ = ("_cancellation", "_target")

    _cancellation: CancellationSignal
    _target: object

    def __init__(self, target: object, cancellation: CancellationSignal) -> None:
        if isinstance(cancellation, type) or not callable(getattr(cancellation, "raise_if_requested", None)):
            message = "cancellation must implement raise_if_requested()"
            raise TypeError(message)
        object.__setattr__(self, "_target", target)
        object.__setattr__(self, "_cancellation", cancellation)

    def __getattr__(self, name: str) -> object:
        value = getattr(self._target, name)
        if not callable(value):
            return value

        def checked(*args: object, **kwargs: object) -> object:
            self._cancellation.raise_if_requested()
            return value(*args, **kwargs)

        return checked

    def __setattr__(self, name: str, value: object) -> None:
        self._cancellation.raise_if_requested()
        setattr(self._target, name, value)
