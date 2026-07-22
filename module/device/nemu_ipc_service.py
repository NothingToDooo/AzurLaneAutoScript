import ctypes
import os
import sys
import time
from pathlib import Path
from typing import TYPE_CHECKING, ClassVar, Protocol

import cv2
import numpy as np

from module.base.decorator import cached_property, del_cached_property, has_cached_property
from module.device.method.pool import WORKER_POOL, JobTimeoutError
from module.device.method.utils import RETRY_TRIES, retry_sleep
from module.exception import HumanTakeoverRequiredError
from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Callable
    from types import TracebackType
    from typing import Self

    from module.base.type_alias import ImageArray
    from module.device.contracts import CaptureRuntime
    from module.device.platform.emulator_base import EmulatorInstanceBase

type PixelBuffer = ctypes.Array[ctypes.c_ubyte]
type Recovery = Callable[[], None]


class _NemuRetryTarget(Protocol):
    def reconnect(self) -> None: ...


class NemuIpcCompatibilityError(Exception):
    pass


class NemuIpcError(Exception):
    pass


NEMU_IPC_MIN_VERSION_MESSAGE = "NemuIpc requires MuMu12 version >= 3.8.13, please check your version"
NEMU_IPC_INSTANCE_DEAD_MESSAGE = "Emulator instance is probably dead"
NEMU_IPC_CONNECT_FAILED_MESSAGE = "Connection failed, please check if nemu_folder is correct and emulator is running"
NEMU_IPC_GET_RESOLUTION_FAILED_MESSAGE = "nemu_capture_display failed during get_resolution()"
NEMU_IPC_SCREENSHOT_FAILED_MESSAGE = "nemu_capture_display failed during screenshot()"
NEMU_IPC_TIMEOUT_MESSAGE = "NemuIpc native call timed out; this connection can no longer be used"


class CaptureStd:
    """同时捕获 Python 与 C 库写入的 stdout/stderr。

    见 https://stackoverflow.com/a/17954769。
    """

    def __init__(self) -> None:
        self.stdout = b""
        self.stderr = b""

    def _redirect_stdout(self, to: int) -> None:
        sys.stdout.close()
        os.dup2(to, self.fdout)
        sys.stdout = os.fdopen(self.fdout, "w")

    def _redirect_stderr(self, to: int) -> None:
        sys.stderr.close()
        os.dup2(to, self.fderr)
        sys.stderr = os.fdopen(self.fderr, "w")

    def __enter__(self) -> Self:
        self.fdout = sys.stdout.fileno()
        self.fderr = sys.stderr.fileno()
        self.reader_out, self.writer_out = os.pipe()
        self.reader_err, self.writer_err = os.pipe()
        self.old_stdout = os.dup(self.fdout)
        self.old_stderr = os.dup(self.fderr)

        file_out = os.fdopen(self.writer_out, "w")
        file_err = os.fdopen(self.writer_err, "w")
        self._redirect_stdout(to=file_out.fileno())
        self._redirect_stderr(to=file_err.fileno())
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self._redirect_stdout(to=self.old_stdout)
        self._redirect_stderr(to=self.old_stderr)
        os.close(self.old_stdout)
        os.close(self.old_stderr)

        self.stdout = self.recvall(self.reader_out)
        self.stderr = self.recvall(self.reader_err)
        os.close(self.reader_out)
        os.close(self.reader_err)

    @staticmethod
    def recvall(reader: int, length: int = 1024) -> bytes:
        fragments = []
        while 1:
            chunk = os.read(reader, length)
            if chunk:
                fragments.append(chunk)
            else:
                break
        return b"".join(fragments)


class CaptureNemuIpc(CaptureStd):
    instance: ClassVar[CaptureNemuIpc | None] = None

    def is_capturing(self) -> bool:
        """只让最外层包装器重定向，嵌套实例不做任何操作。"""
        cls = self.__class__
        return isinstance(cls.instance, cls) and cls.instance != self

    def __enter__(self) -> Self:
        if self.is_capturing():
            return self

        super().__enter__()
        CaptureNemuIpc.instance = self
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        if self.is_capturing():
            return

        CaptureNemuIpc.instance = None
        super().__exit__(exc_type, exc_val, exc_tb)

        self.check_stdout()
        self.check_stderr()

    def check_stdout(self) -> None:
        if not self.stdout:
            return
        logger.info(f"NemuIpc stdout: {self.stdout}")

    def check_stderr(self) -> None:
        if not self.stderr:
            return
        logger.error(f"NemuIpc stderr: {self.stderr}")

        # 旧 MuMu12 3.4.0/3.7.3 会分别返回 rpc error 1783/1745。
        if b"error: 1783" in self.stderr or b"error: 1745" in self.stderr:
            raise NemuIpcCompatibilityError(NEMU_IPC_MIN_VERSION_MESSAGE)
        # 连接 id 错误时会提示找不到 rpc connection。
        if b"cannot find rpc connection" in self.stderr:
            raise NemuIpcError(self.stderr)
        # 模拟器进程退出时可能返回 rpc error 1722/1726。
        if b"error: 1722" in self.stderr or b"error: 1726" in self.stderr:
            raise NemuIpcError(NEMU_IPC_INSTANCE_DEAD_MESSAGE)


def _noop_recovery() -> None:
    pass


def _nemu_ipc_error_recovery(
    self: _NemuRetryTarget,
    error: NemuIpcCompatibilityError | JobTimeoutError | NemuIpcError | OSError | ValueError | ctypes.ArgumentError,
    func_name: str,
) -> Recovery | None:
    if isinstance(error, NemuIpcCompatibilityError):
        logger.error(error)
        return None
    if isinstance(error, JobTimeoutError):
        logger.critical(f"Func {func_name}() call timeout; stop using this NemuIpc connection")
        return None
    if isinstance(error, NemuIpcError):
        logger.error(error)
        return self.reconnect
    if isinstance(error, (OSError, ValueError, ctypes.ArgumentError)):
        logger.error(error)
        return _noop_recovery
    return None


def _run_with_retry[TargetT: _NemuRetryTarget, ResultT](
    target: TargetT, func_name: str, invoke: Callable[[int], ResultT]
) -> ResultT:
    recovery: Recovery | None = None
    terminal_error: BaseException | None = None
    for trial in range(RETRY_TRIES):
        try:
            if recovery is not None:
                time.sleep(retry_sleep(trial))
                recovery()
            return invoke(trial)
        except HumanTakeoverRequiredError:
            raise
        except (
            NemuIpcCompatibilityError,
            JobTimeoutError,
            NemuIpcError,
            OSError,
            ValueError,
            ctypes.ArgumentError,
        ) as error:
            terminal_error = error
            recovery = _nemu_ipc_error_recovery(target, error, func_name)
            if recovery is None:
                break

    message = NEMU_IPC_TIMEOUT_MESSAGE if isinstance(terminal_error, JobTimeoutError) else f"Retry {func_name}() failed"
    logger.critical(message)
    raise HumanTakeoverRequiredError(message) from terminal_error


class NemuIpcImpl:
    def __init__(self, nemu_folder: str, instance_id: int, display_id: int = 0) -> None:
        """nemu_folder 是 MuMu12 安装目录，instance_id 从 0 开始。

        关闭后台保活时 display_id 始终为 0。
        """
        self.nemu_folder: str = nemu_folder
        self.instance_id: int = instance_id
        self.display_id: int = display_id

        nemu_path = Path(nemu_folder)
        list_dll = [
            # MuMuPlayer12
            str((nemu_path / "shell/sdk/external_renderer_ipc.dll").resolve()),
            # MuMuPlayer12 5.0
            str((nemu_path / "nx_device/12.0/shell/sdk/external_renderer_ipc.dll").resolve()),
            # MuMuPlayer12 6.0
            str((nemu_path / "nx_main/sdk/external_renderer_ipc.dll").resolve()),
        ]
        lib: ctypes.CDLL | None = None
        for ipc_dll in list_dll:
            if not Path(ipc_dll).exists():
                continue
            try:
                lib = ctypes.CDLL(ipc_dll)
                break
            except OSError as e:
                logger.error(e)
                logger.error(f"ipc_dll={ipc_dll} exists, but cannot be loaded")
                continue
        if lib is None:
            message = f"{NEMU_IPC_MIN_VERSION_MESSAGE}. None of the following path exists: {list_dll}"
            raise NemuIpcCompatibilityError(message)
        self.lib = lib
        logger.info(
            f"NemuIpcImpl init, "
            f"nemu_folder={nemu_folder}, "
            f"ipc_dll={ipc_dll}, "
            f"instance_id={instance_id}, "
            f"display_id={display_id}"
        )
        self.connect_id: int = 0
        self.width = 0
        self.height = 0
        self._timed_out = False

    def _require_usable(self) -> None:
        if self._timed_out:
            raise HumanTakeoverRequiredError(NEMU_IPC_TIMEOUT_MESSAGE)

    def connect(self, *, on_thread: bool = True) -> None:
        self._require_usable()
        if self.connect_id > 0:
            return

        if on_thread:
            connect_id = self.run_func(self.lib.nemu_connect, self.nemu_folder, self.instance_id)
        else:
            connect_id = self.lib.nemu_connect(self.nemu_folder, self.instance_id)
        if connect_id == 0:
            raise NemuIpcError(NEMU_IPC_CONNECT_FAILED_MESSAGE)

        self.connect_id = connect_id

    def connect_with_retry(self, *, on_thread: bool = True) -> None:
        _run_with_retry(self, "connect_with_retry", lambda _trial: self.connect(on_thread=on_thread))

    def disconnect(self) -> None:
        if self.connect_id == 0:
            return
        if self._timed_out:
            self.connect_id = 0
            return

        self.run_func(self.lib.nemu_disconnect, self.connect_id)

        self.connect_id = 0

    def reconnect(self) -> None:
        self.disconnect()
        self.connect()

    def __enter__(self) -> Self:
        self.connect()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        self.disconnect()

    def run_func[*ArgsT, ResultT](
        self, func: Callable[[*ArgsT], ResultT], *args: *ArgsT, on_thread: bool = True, timeout: float = 0.5
    ) -> ResultT:
        """on_thread=True 时在工作线程运行同步函数，timeout 秒后抛出 JobTimeoutError。

        底层调用还可抛出 NemuIpcCompatibilityError 或 NemuIpcError。
        """
        self._require_usable()
        try:
            if on_thread:
                job = WORKER_POOL.start_thread_soon(func, *args)
                result = job.get_or_timeout(timeout)
            else:
                result = func(*args)
        except JobTimeoutError:
            self._timed_out = True
            raise

        func_name = getattr(func, "__name__", type(func).__name__)
        err = False
        if func_name == "_screenshot":
            return result
        if not isinstance(result, int):
            message = f"Native function {func_name} returned non-integer result: {type(result).__name__}"
            raise TypeError(message)
        if func_name == "nemu_connect":
            if result == 0:
                err = True
        elif result > 0:
            err = True
        # 再调用一次以捕获 C 库写到 stdout/stderr 的真实错误。
        if err:
            logger.warning(f"Failed to call {func_name}, result={result}")
            with CaptureNemuIpc():
                func(*args)

        return result

    def get_resolution(self, *, on_thread: bool = True) -> None:
        """结果写入 self.width 和 self.height，不直接返回。"""
        if self.connect_id == 0:
            self.connect()

        width_ptr = ctypes.pointer(ctypes.c_int(0))
        height_ptr = ctypes.pointer(ctypes.c_int(0))
        nullptr = ctypes.POINTER(ctypes.c_int)()

        ret = self.run_func(
            self.lib.nemu_capture_display,
            self.connect_id,
            self.display_id,
            0,
            width_ptr,
            height_ptr,
            nullptr,
            on_thread=on_thread,
        )
        if ret > 0:
            raise NemuIpcError(NEMU_IPC_GET_RESOLUTION_FAILED_MESSAGE)
        self.width = width_ptr.contents.value
        self.height = height_ptr.contents.value

    def _screenshot(self) -> PixelBuffer:
        if self.connect_id == 0:
            self.connect(on_thread=False)
        self.get_resolution(on_thread=False)

        width_ptr = ctypes.pointer(ctypes.c_int(self.width))
        height_ptr = ctypes.pointer(ctypes.c_int(self.height))
        length = self.width * self.height * 4
        pixels_pointer = ctypes.pointer((ctypes.c_ubyte * length)())

        ret = self.lib.nemu_capture_display(
            self.connect_id,
            self.display_id,
            length,
            width_ptr,
            height_ptr,
            pixels_pointer,
        )
        if ret > 0:
            raise NemuIpcError(NEMU_IPC_SCREENSHOT_FAILED_MESSAGE)

        # 返回像素指针，避免在线程 Job 间传递整张图像。
        return pixels_pointer.contents

    def _screenshot_once(self, timeout: float) -> ImageArray:
        """timeout 单位为秒，重试时动态延长。

        返回上下颠倒的 RGBA 数组，形状为 (height, width, 4)。
        """
        if self.connect_id == 0:
            self.connect()

        pixels = self.run_func(self._screenshot, timeout=timeout)

        return np.ctypeslib.as_array(pixels).reshape((self.height, self.width, 4))

    def screenshot(self, timeout: float = 0.5) -> ImageArray:
        def invoke(trial: int) -> ImageArray:
            retry_timeout = retry_sleep(trial)
            return self._screenshot_once(retry_timeout if retry_timeout > 0 else timeout)

        return _run_with_retry(self, "screenshot", invoke)


class NemuIpcCapture:
    """只负责 MuMu nemu_ipc 截图及其连接生命周期。"""

    def __init__(self, mumu_runtime: CaptureRuntime) -> None:
        self.mumu_runtime = mumu_runtime

    @cached_property
    def nemu_ipc(self) -> NemuIpcImpl:
        # 可执行文件位于 <安装目录>/shell 时，nemu_folder 取其上级安装目录。
        instance = self.mumu_runtime.emulator_instance
        if instance is None:
            logger.error("Unable to use NemuIpc because emulator instance not found")
            raise HumanTakeoverRequiredError
        if "MuMuPlayerGlobal" in instance.path:
            logger.info(f"当前个人版不支持 MuMuPlayerGlobal：{instance.path}")
            raise HumanTakeoverRequiredError
        try:
            instance_id = _require_mumu_instance_id(instance)
            impl = NemuIpcImpl(
                nemu_folder=instance.emulator.abspath("../"),
                instance_id=instance_id,
                display_id=0,
            )
            impl.connect_with_retry()
        except (NemuIpcCompatibilityError, NemuIpcError, JobTimeoutError) as e:
            logger.error(e)
            logger.error("Unable to initialize NemuIpc")
            raise HumanTakeoverRequiredError from e
        else:
            return impl

    def release(self) -> None:
        try:
            if has_cached_property(self, "nemu_ipc"):
                self.nemu_ipc.disconnect()
        finally:
            del_cached_property(self, "nemu_ipc")
            logger.info("nemu_ipc released")

    def screenshot_nemu_ipc(self) -> ImageArray:
        source = self.nemu_ipc.screenshot()
        image = np.empty((*source.shape[:2], 3), dtype=np.uint8)
        cv2.cvtColor(source, cv2.COLOR_BGRA2BGR, dst=image)
        cv2.flip(image, 0, dst=image)
        return image

    def screenshot(self) -> ImageArray:
        return self.screenshot_nemu_ipc()


def _require_mumu_instance_id(instance: EmulatorInstanceBase) -> int:
    instance_id = instance.mumu_player_12_id
    if instance_id is None:
        message = f"Unable to determine MuMu instance id from {instance.name}"
        raise NemuIpcError(message)
    return instance_id
