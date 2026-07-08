import multiprocessing
from typing import TYPE_CHECKING, cast

from module.config.config_updater import ConfigUpdater
from module.webui.config import WebUIConfig

if TYPE_CHECKING:
    from collections.abc import Callable
    from multiprocessing.managers import SyncManager


class cached_class_property[T]:
    """
    Code from https://github.com/dssg/dickens
    Add typing support

    Descriptor decorator implementing a class-level, read-only
    property, which caches its results on the class(es) on which it
    operates.
    Inheritance is supported, insofar as the descriptor is never hidden
    by its cache; rather, it stores values under its access name with
    added underscores. For example, when wrapping getters named
    "choices", "choices_" or "_choices", each class's result is stored
    on the class at "_choices_"; decoration of a getter named
    "_choices_" would raise an exception.
    """

    class AliasConflict(ValueError):
        pass

    def __init__(self, func: Callable[..., T]):
        self.__func__ = func
        func_name: str = func.__name__
        self.__cache_name__ = "_{}_".format(func_name.strip("_"))
        if self.__cache_name__ == func_name:
            raise self.AliasConflict(self.__cache_name__)

    def __get__(self, instance, cls=None) -> T:
        if cls is None:
            cls = type(instance)

        try:
            return vars(cls)[self.__cache_name__]
        except KeyError:
            result = self.__func__(cls)
            setattr(cls, self.__cache_name__, result)
            return result


class State:
    """
    Shared settings
    """

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
    def webui_config(cls) -> WebUIConfig:
        """
        Returns:
            WebUIConfig：
        """
        return WebUIConfig()

    @cached_class_property
    def config_updater(cls) -> ConfigUpdater:
        """
        Returns:
            ConfigUpdater：
        """
        return ConfigUpdater()
