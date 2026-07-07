import re
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, overload

import psutil

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

DEPLOY_CONFIG = "./config/deploy.yaml"
DEPLOY_TEMPLATE = "./deploy/template"


class cached_property[T]:
    """
    cached-property from https://github.com/pydanny/cached-property
    Add typing support

    A property that is only computed once per instance and then replaces itself
    with an ordinary attribute. Deleting the attribute resets the property.
    Source: https://github.com/bottlepy/bottle/commit/fa7733e075da0d790d809aa3d2f53071897e6f76
    """

    def __init__(self, func: Callable[[Any], T]):
        self.func = func

    @overload
    def __get__(self, obj: None, cls: type[Any] | None = None) -> cached_property[T]: ...

    @overload
    def __get__(self, obj: object, cls: type[Any] | None = None) -> T: ...

    def __get__(self, obj: Any | None, cls: type[Any] | None = None) -> T | cached_property[T]:
        if obj is None:
            return self

        value = obj.__dict__[self.func.__name__] = self.func(obj)
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
    for sub in Path(folder).iterdir():
        if is_dir:
            if sub.is_dir():
                yield sub.as_posix()
        elif ext is not None:
            if not sub.is_dir() and sub.suffix == ext:
                yield sub.as_posix()
        else:
            yield sub.as_posix()


def poor_yaml_read(file):
    """
    Poor implementation to load yaml without pyyaml dependency, but with re

    Args:
        file (str):

    Returns:
        dict:
    """
    if not Path(file).exists():
        return {}

    data = {}
    regex = re.compile(r"^(.*?):(.*?)$")
    with Path(file).open(encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip("\n\r\t ").replace("\\", "/")
            if line.startswith("#"):
                continue
            result = re.match(regex, line)
            if result:
                k, v = result.group(1), result.group(2).strip("\n\r\t' ")
                if v:
                    if v.lower() == "null":
                        v = None
                    elif v.lower() == "false":
                        v = False
                    elif v.lower() == "true":
                        v = True
                    elif v.isdigit():
                        v = int(v)
                    data[k] = v

    return data


def poor_yaml_write(data, file, template_file=DEPLOY_TEMPLATE):
    """
    Args:
        data (dict):
        file (str):
        template_file (str):
    """
    with Path(template_file).open(encoding="utf-8") as f:
        text = f.read().replace("\\", "/")

    for key, raw_value in data.items():
        if raw_value is None:
            value = "null"
        elif raw_value is True:
            value = "true"
        elif raw_value is False:
            value = "false"
        else:
            value = raw_value
        text = re.sub(f"{key}:.*?\n", f"{key}: {value}\n", text)

    with Path(file).open("w", encoding="utf-8", newline="") as f:
        f.write(text)


@dataclass
class DataProcessInfo:
    proc: Any  # psutil.Process 或 psutil._pswindows.Process
    pid: int

    @cached_property
    def name(self):
        try:
            name = self.proc.name()
        except psutil.Error:
            name = ""
        return name

    @cached_property
    def cmdline(self):
        try:
            cmdline = self.proc.cmdline()
        except psutil.Error:
            # psutil.AccessDenied
            # # NoSuchProcess: process no longer exists (pid=xxx)
            cmdline = []
        return " ".join(cmdline).replace(r"\\", "/").replace("\\", "/")

    def __str__(self):
        # Don't print `proc`, it will take some time to get process properties
        return f'DataProcessInfo(name="{self.name}", pid={self.pid}, cmdline="{self.cmdline}")'

    __repr__ = __str__


def iter_process() -> Iterable[DataProcessInfo]:
    if psutil.WINDOWS:
        # 这里是一次性扫描，直接访问 psutil._psplatform.Process，
        # 避开 psutil.Process.is_running() 的额外开销。
        # 这段通常只需要约 0.017 秒。
        for pid in psutil.pids():
            proc = psutil._psplatform.Process(pid)
            yield DataProcessInfo(
                proc=proc,
                pid=proc.pid,
            )
    else:
        # 即使指定 attr，这条路径也大约需要 0.45 秒。
        for proc in psutil.process_iter():
            yield DataProcessInfo(
                proc=proc,
                pid=proc.pid,
            )
