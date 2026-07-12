import multiprocessing
from typing import TYPE_CHECKING, cast

from module.config.config_updater import ConfigUpdater
from module.webui.config import WebUIConfig

if TYPE_CHECKING:
    from collections.abc import Callable
    from multiprocessing.managers import SyncManager


class cached_class_property[T]:
    """类级只读缓存属性，缓存写入实际访问类并支持继承。
    改写自 https://github.com/dssg/dickens，并补充类型标注。
    """

    class AliasConflict(ValueError):
        """缓存属性名与生成的缓存字段名冲突。"""

    def __init__(self, func: Callable[..., T]) -> None:
        self.__func__ = func
        func_name = getattr(func, "__name__", type(func).__name__)
        self.__cache_name__ = "_{}_".format(func_name.strip("_"))
        if self.__cache_name__ == func_name:
            raise self.AliasConflict(self.__cache_name__)

    def __get__(self, instance: None, cls: type | None = None) -> T:
        del instance
        if cls is None:
            message = "cached class property requires an owner class"
            raise TypeError(message)

        try:
            return vars(cls)[self.__cache_name__]
        except KeyError:
            result = self.__func__(cls)
            setattr(cls, self.__cache_name__, result)
            return result


class State:
    _init = False
    _clearup = False

    manager: SyncManager = cast("SyncManager", None)
    theme: str = "default"

    @classmethod
    def init(cls) -> None:
        cls.manager = multiprocessing.Manager()
        cls._init = True

    @classmethod
    def clearup(cls) -> None:
        cls.manager.shutdown()
        cls._clearup = True

    @cached_class_property
    def webui_config(cls: type[State]) -> WebUIConfig:
        return WebUIConfig()

    @cached_class_property
    def config_updater(cls: type[State]) -> ConfigUpdater:
        return ConfigUpdater()
