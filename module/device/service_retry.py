from functools import wraps

from module.device.adb_session import retry as adb_retry


def session_retry(func):
    """让组合服务的 ADB 重试始终作用于其注入 session。"""

    @wraps(func)
    def wrapper(self, *args, **kwargs):
        @adb_retry
        @wraps(func)
        def call(_session):
            return func(self, *args, **kwargs)

        return call(self.session)

    return wrapper
