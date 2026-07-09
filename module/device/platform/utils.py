from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload

import psutil

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


class cached_property[T]:
    """
    cached-property from https://github.com/pydanny/cached-property
    Add typing support

    A property that is only computed once per instance and then replaces itself
    with an ordinary attribute. Deleting the attribute resets the property.
    Source: https://github.com/bottlepy/bottle/commit/fa7733e075da0d790d809aa3d2f53071897e6f76
    """

    def __init__(self, func: Callable[..., T]):
        self.func = func
        self.func_name = getattr(func, "__name__", type(func).__name__)

    @overload
    def __get__(self, obj: None, cls: type[Any] | None = None) -> cached_property[T]: ...

    @overload
    def __get__(self, obj: object, cls: type[Any] | None = None) -> T: ...

    def __get__(self, obj, cls=None):
        if obj is None:
            return self

        value = obj.__dict__[self.func_name] = self.func(obj)
        return value


def iter_folder(folder, is_dir=False, ext=None):
    """
    Args:
        folder (str):
        is_dir (bool): True to iter directories only
        ext (str): File extension, such as `.yaml`

    Yields:
        str: Absolute path of files
    """
    try:
        files = list(Path(folder).iterdir())
    except FileNotFoundError:
        return

    for sub in files:
        if is_dir:
            if sub.is_dir():
                yield sub.as_posix()
        elif ext is not None:
            if not sub.is_dir() and sub.suffix == ext:
                yield sub.as_posix()
        else:
            yield sub.as_posix()


@dataclass
class DataProcessInfo:
    proc: Any
    pid: int

    @cached_property
    def name(self):
        try:
            return self.proc.name()
        except psutil.Error:
            return ""

    @cached_property
    def cmdline(self):
        try:
            cmdline = self.proc.cmdline()
        except psutil.Error:
            cmdline = []
        return " ".join(cmdline).replace(r"\\", "/").replace("\\", "/")

    def __str__(self):
        return f'DataProcessInfo(name="{self.name}", pid={self.pid}, cmdline="{self.cmdline}")'

    __repr__ = __str__


def iter_process() -> Iterable[DataProcessInfo]:
    for pid in psutil.pids():
        proc = psutil.Process(pid)
        yield DataProcessInfo(proc=proc, pid=proc.pid)
