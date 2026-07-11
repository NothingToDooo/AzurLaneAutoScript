import random
import re
from contextlib import suppress
from functools import cached_property, wraps

from module.logger import logger

__all__ = (
    "cached_property",
    "del_cached_property",
    "function_drop",
    "has_cached_property",
    "run_once",
    "set_cached_property",
)


def del_cached_property(obj, name):
    with suppress(KeyError):
        del obj.__dict__[name]


def has_cached_property(obj, name):
    return name in obj.__dict__


def set_cached_property(obj, name, value):
    obj.__dict__[name] = value


def function_drop(rate=0.5, default=None):
    """按 0～1 的 rate 随机丢弃调用，用于模拟器卡顿测试；丢弃时返回 default。"""

    def decorate(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if random.uniform(0, 1) > rate:
                return func(*args, **kwargs)
            cls = ""
            arguments = [str(arg) for arg in args]
            if arguments:
                matched = re.search(r"<(.*?) object at", arguments[0])
                if matched:
                    cls = matched.group(1) + "."
                    arguments.pop(0)
            arguments += [f"{k}={v}" for k, v in kwargs.items()]
            arguments = ", ".join(arguments)
            logger.info(f"Dropped: {cls}{func.__name__}({arguments})")
            return default

        return wrapper

    return decorate


def run_once(f):
    """仅执行首次调用；后续调用返回 None。"""
    has_run = False

    def wrapper(*args, **kwargs):
        nonlocal has_run
        if not has_run:
            has_run = True
            return f(*args, **kwargs)
        return None

    return wrapper
