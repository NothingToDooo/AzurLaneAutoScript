from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, overload

import psutil

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable


class cached_property[OwnerT, ValueT]:
    """仅计算一次并写回实例属性，删除该属性即可重置。

    基于 https://github.com/pydanny/cached-property 并加入类型支持；实现来源：
    https://github.com/bottlepy/bottle/commit/fa7733e075da0d790d809aa3d2f53071897e6f76
    """

    def __init__(self, func: Callable[[OwnerT], ValueT]) -> None:
        self.func = func
        self.func_name = getattr(func, "__name__", type(func).__name__)

    @overload
    def __get__(self, obj: None, cls: type[OwnerT] | None = None) -> cached_property[OwnerT, ValueT]: ...

    @overload
    def __get__(self, obj: OwnerT, cls: type[OwnerT] | None = None) -> ValueT: ...

    def __get__(self, obj: OwnerT | None, cls: type[OwnerT] | None = None) -> cached_property[OwnerT, ValueT] | ValueT:
        if obj is None:
            return self

        value = obj.__dict__[self.func_name] = self.func(obj)
        return value


def iter_folder(folder: str | Path, *, is_dir: bool = False, ext: str | None = None) -> Iterable[str]:
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
    proc: psutil.Process
    pid: int

    @cached_property
    def name(self) -> str:
        try:
            return self.proc.name()
        except psutil.Error:
            return ""

    @cached_property
    def cmdline(self) -> str:
        try:
            cmdline = self.proc.cmdline()
        except psutil.Error:
            cmdline = []
        return " ".join(cmdline).replace(r"\\", "/").replace("\\", "/")

    def __str__(self) -> str:
        return f'DataProcessInfo(name="{self.name}", pid={self.pid}, cmdline="{self.cmdline}")'

    __repr__ = __str__


def iter_process() -> Iterable[DataProcessInfo]:
    for pid in psutil.pids():
        proc = psutil.Process(pid)
        yield DataProcessInfo(proc=proc, pid=proc.pid)
