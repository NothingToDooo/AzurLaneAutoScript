from functools import wraps
from typing import TYPE_CHECKING, Protocol

from module.device.adb_session import retry as adb_retry

if TYPE_CHECKING:
    from collections.abc import Callable
    from typing import Concatenate

    from module.device.contracts import AdbRecoverySession


class _SessionService(Protocol):
    @property
    def session(self) -> AdbRecoverySession: ...


def session_retry[ServiceT: _SessionService, **P, ResultT](
    func: Callable[Concatenate[ServiceT, P], ResultT],
) -> Callable[Concatenate[ServiceT, P], ResultT]:
    """让组合服务的 ADB 重试始终作用于其注入 session。"""

    @wraps(func)
    def wrapper(self: ServiceT, *args: P.args, **kwargs: P.kwargs) -> ResultT:
        @adb_retry
        @wraps(func)
        def call(_session: AdbRecoverySession) -> ResultT:
            return func(self, *args, **kwargs)

        return call(self.session)

    return wrapper
