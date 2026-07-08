import random
import re
from contextlib import suppress
from functools import cached_property, wraps
from typing import ClassVar

from module.logger import logger

__all__ = (
    "Config",
    "cached_property",
    "del_cached_property",
    "function_drop",
    "has_cached_property",
    "run_once",
    "set_cached_property",
)


class Config:
    """
    Decorator that calls different function with a same name according to config.

    func_list likes:
    func_list = {
        'func1': [
            {'options': {'ENABLE': True}, 'func': 1},
            {'options': {'ENABLE': False}, 'func': 1}
        ]
    }
    """

    func_list: ClassVar[dict[str, list[dict[str, object]]]] = {}

    @classmethod
    def when(cls, **kwargs):
        """
        Args:
            **kwargs: Any option in AzurLaneConfig.

        Examples:
            @Config.when(USE_ONE_CLICK_RETIREMENT=True)
            def retire_ships(self, amount=None, rarity=None):
                pass

            @Config.when(USE_ONE_CLICK_RETIREMENT=False)
            def retire_ships(self, amount=None, rarity=None):
                pass
        """
        options = kwargs

        def decorate(func):
            name = func.__name__
            data = {"options": options, "func": func}
            if name not in cls.func_list:
                cls.func_list[name] = [data]
            else:
                override = False
                for record in cls.func_list[name]:
                    if record["options"] == data["options"]:
                        record["func"] = data["func"]
                        override = True
                if not override:
                    cls.func_list[name].append(data)

            @wraps(func)
            def wrapper(self, *args, **kwargs):
                """
                Args:
                    self: ModuleBase instance.
                    *args:
                    **kwargs:
                """
                for record in cls.func_list[name]:
                    flag = [
                        value is None or self.config.__getattribute__(key) == value
                        for key, value in record["options"].items()
                    ]
                    if not all(flag):
                        continue

                    return record["func"](self, *args, **kwargs)

                logger.warning(f"No option fits for {name}, using the last define func.")
                return func(self, *args, **kwargs)

            return wrapper

        return decorate


def del_cached_property(obj, name):
    """
    Delete a cached property safely.

    Args:
        obj:
        name (str):
    """
    with suppress(KeyError):
        del obj.__dict__[name]


def has_cached_property(obj, name):
    """
    Check if a property is cached.

    Args:
        obj:
        name (str):
    """
    return name in obj.__dict__


def set_cached_property(obj, name, value):
    """
    Set a cached property.

    Args:
        obj:
        name (str):
        value:
    """
    obj.__dict__[name] = value


def function_drop(rate=0.5, default=None):
    """
    Drop function calls to simulate random emulator stuck, for testing purpose.

    Args:
        rate (float): 0 to 1. Drop rate.
        default: Default value to return if dropped.

    Examples:
        @function_drop(0.3)
        def click(self, button, record_check=True):
            pass

        30% possibility:
        INFO | Dropped: module.device.device.Device.click(REWARD_GOTO_MAIN, record_check=True)
        70% possibility:
        INFO | Click (1091,  628) @ REWARD_GOTO_MAIN
    """

    def decorate(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            if random.uniform(0, 1) > rate:
                return func(*args, **kwargs)
            cls = ""
            arguments = [str(arg) for arg in args]
            if arguments:
                matched = re.search("<(.*?) object at", arguments[0])
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
    """
    Run a function only once, no matter how many times it has been called.

    Examples:
        @run_once
        def my_function(foo, bar):
            return foo + bar

        while 1:
            my_function()

    Examples:
        def my_function(foo, bar):
            return foo + bar

        action = run_once(my_function)
        while 1:
            action()
    """

    def wrapper(*args, **kwargs):
        if not wrapper.has_run:
            wrapper.has_run = True
            return f(*args, **kwargs)
        return None

    wrapper.has_run = False
    return wrapper
