import ctypes
import os
import sys
import time
from functools import wraps
from pathlib import Path

import cv2
import numpy as np

from module.base.decorator import cached_property, del_cached_property, has_cached_property
from module.device.method.pool import WORKER_POOL, JobTimeout
from module.device.method.utils import RETRY_TRIES, retry_sleep
from module.device.platform import Platform
from module.exception import RequestHumanTakeover
from module.logger import logger


class NemuIpcIncompatible(Exception):
    pass


class NemuIpcError(Exception):
    pass


NEMU_IPC_MIN_VERSION_MESSAGE = "NemuIpc requires MuMu12 version >= 3.8.13, please check your version"
NEMU_IPC_INSTANCE_DEAD_MESSAGE = "Emulator instance is probably dead"
NEMU_IPC_CONNECT_FAILED_MESSAGE = "Connection failed, please check if nemu_folder is correct and emulator is running"
NEMU_IPC_GET_RESOLUTION_FAILED_MESSAGE = "nemu_capture_display failed during get_resolution()"
NEMU_IPC_SCREENSHOT_FAILED_MESSAGE = "nemu_capture_display failed during screenshot()"


class CaptureStd:
    """
    Capture stdout and stderr from both python and C library
    https://stackoverflow.com/questions/5081657/how-do-i-prevent-a-c-shared-library-to-print-on-stdout-in-python/17954769

    ```
    with CaptureStd() as capture:
        # String wasn't printed
        print('whatever')
    # But captured in ``capture.stdout``
    print(f'Got stdout: "{capture.stdout}"')
    print(f'Got stderr: "{capture.stderr}"')
    ```
    """

    def __init__(self):
        self.stdout = b""
        self.stderr = b""

    def _redirect_stdout(self, to):
        sys.stdout.close()
        os.dup2(to, self.fdout)
        sys.stdout = os.fdopen(self.fdout, "w")

    def _redirect_stderr(self, to):
        sys.stderr.close()
        os.dup2(to, self.fderr)
        sys.stderr = os.fdopen(self.fderr, "w")

    def __enter__(self):
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

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._redirect_stdout(to=self.old_stdout)
        self._redirect_stderr(to=self.old_stderr)
        os.close(self.old_stdout)
        os.close(self.old_stderr)

        self.stdout = self.recvall(self.reader_out)
        self.stderr = self.recvall(self.reader_err)
        os.close(self.reader_out)
        os.close(self.reader_err)

    @staticmethod
    def recvall(reader, length=1024) -> bytes:
        fragments = []
        while 1:
            chunk = os.read(reader, length)
            if chunk:
                fragments.append(chunk)
            else:
                break
        return b"".join(fragments)


class CaptureNemuIpc(CaptureStd):
    instance = None

    def is_capturing(self):
        """
        Only capture at the topmost wrapper to avoid nested capturing
        If a capture is ongoing, this instance does nothing
        """
        cls = self.__class__
        return isinstance(cls.instance, cls) and cls.instance != self

    def __enter__(self):
        if self.is_capturing():
            return self

        super().__enter__()
        CaptureNemuIpc.instance = self
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.is_capturing():
            return

        CaptureNemuIpc.instance = None
        super().__exit__(exc_type, exc_val, exc_tb)

        self.check_stdout()
        self.check_stderr()

    def check_stdout(self):
        if not self.stdout:
            return
        logger.info(f"NemuIpc stdout: {self.stdout}")

    def check_stderr(self):
        if not self.stderr:
            return
        logger.error(f"NemuIpc stderr: {self.stderr}")

        # 旧 MuMu12 3.4.0/3.7.3 会分别返回 rpc error 1783/1745。
        if b"error: 1783" in self.stderr or b"error: 1745" in self.stderr:
            raise NemuIpcIncompatible(NEMU_IPC_MIN_VERSION_MESSAGE)
        # 连接 id 错误时会提示找不到 rpc connection。
        if b"cannot find rpc connection" in self.stderr:
            raise NemuIpcError(self.stderr)
        # 模拟器进程退出时可能返回 rpc error 1722/1726。
        if b"error: 1722" in self.stderr or b"error: 1726" in self.stderr:
            raise NemuIpcError(NEMU_IPC_INSTANCE_DEAD_MESSAGE)


def _noop_recovery():
    pass


def _apply_retry_timeout(func_name, trial, kwargs):
    if func_name != "screenshot":
        return
    timeout = retry_sleep(trial)
    if timeout > 0:
        kwargs["timeout"] = timeout


def _nemu_ipc_error_recovery(self, error, func_name, trial):
    if isinstance(error, NemuIpcIncompatible):
        logger.error(error)
        return None
    if isinstance(error, JobTimeout):
        logger.warning(f"Func {func_name}() call timeout, retrying: {trial}")
        return _noop_recovery
    if isinstance(error, NemuIpcError):
        logger.error(error)
        return self.reconnect
    if isinstance(error, (OSError, ValueError, ctypes.ArgumentError)):
        logger.error(error)
        return _noop_recovery
    return None


def retry(func):
    @wraps(func)
    def retry_wrapper(self, *args, **kwargs):
        """
        Args:
            self (NemuIpcImpl):
        """
        recovery = None
        func_name = func.__name__
        for trial in range(RETRY_TRIES):
            _apply_retry_timeout(func_name, trial, kwargs)
            try:
                if callable(recovery):
                    time.sleep(retry_sleep(trial))
                    recovery()
                return func(self, *args, **kwargs)
            # 无法自动处理。
            except RequestHumanTakeover:
                break
            except (NemuIpcIncompatible, JobTimeout, NemuIpcError, OSError, ValueError, ctypes.ArgumentError) as e:
                recovery = _nemu_ipc_error_recovery(self, e, func_name, trial)
                if recovery is None:
                    break

        logger.critical(f"Retry {func.__name__}() failed")
        raise RequestHumanTakeover

    return retry_wrapper


class NemuIpcImpl:
    def __init__(self, nemu_folder: str, instance_id: int, display_id: int = 0):
        """
        Args:
            nemu_folder: Installation path of MuMu12, e.g. E:/ProgramFiles/MuMuPlayer-12.0
            instance_id: Emulator instance ID, starting from 0
            display_id: Always 0 if keep app alive was disabled
        """
        self.nemu_folder: str = nemu_folder
        self.instance_id: int = instance_id
        self.display_id: int = display_id

        # try to load dll from various path
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
            # not found
            message = f"{NEMU_IPC_MIN_VERSION_MESSAGE}. None of the following path exists: {list_dll}"
            raise NemuIpcIncompatible(message)
        self.lib = lib
        # success
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

    def connect(self, on_thread=True):
        if self.connect_id > 0:
            return

        if on_thread:
            connect_id = self.run_func(self.lib.nemu_connect, self.nemu_folder, self.instance_id)
        else:
            connect_id = self.lib.nemu_connect(self.nemu_folder, self.instance_id)
        if connect_id == 0:
            raise NemuIpcError(NEMU_IPC_CONNECT_FAILED_MESSAGE)

        self.connect_id = connect_id

    @retry
    def connect_with_retry(self, on_thread=True):
        self.connect(on_thread=on_thread)

    def disconnect(self):
        if self.connect_id == 0:
            return

        self.run_func(self.lib.nemu_disconnect, self.connect_id)

        self.connect_id = 0

    def reconnect(self):
        self.disconnect()
        self.connect()

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    @staticmethod
    def run_func(func, *args, on_thread=True, timeout=0.5):
        """
        Args:
            func: Sync function to call
            *args:
            on_thread: True to run func on a separated thread
            timeout:

        Raises:
            JobTimeout: If function call timeout
            NemuIpcIncompatible:
            NemuIpcError
        """
        if on_thread:
            # nemu_ipc may timeout sometimes, so we run it on a separated thread
            job = WORKER_POOL.start_thread_soon(func, *args)
            result = job.get_or_kill(timeout)
        else:
            result = func(*args)

        err = False
        if func.__name__ == "_screenshot":
            pass
        elif func.__name__ == "nemu_connect":
            if result == 0:
                err = True
        elif result > 0:
            err = True
        # Get to actual error message printed in std
        if err:
            logger.warning(f"Failed to call {func.__name__}, result={result}")
            with CaptureNemuIpc():
                func(*args)

        return result

    def get_resolution(self, on_thread=True):
        """
        Get emulator resolution, `self.width` and `self.height` will be set
        """
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

    def _screenshot(self):
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

        # Return pixels_pointer instead of image to avoid passing image through jobs
        return pixels_pointer

    @retry
    def screenshot(self, timeout=0.5):
        """
        Args:
            timeout: Timout in seconds to call nemu_ipc
                Will be dynamically extended by `@retry`

        Returns:
            np.ndarray: Image array in RGBA color space
                Note that image is upside down
        """
        if self.connect_id == 0:
            self.connect()

        pixels_pointer = self.run_func(self._screenshot, timeout=timeout)

        return np.ctypeslib.as_array(pixels_pointer.contents).reshape((self.height, self.width, 4))


class NemuIpc(Platform):
    _serial_bound_cached_properties = ("nemu_ipc",)

    @cached_property
    def nemu_ipc(self) -> NemuIpcImpl:
        """
        Initialize a nemu ipc implementation
        """
        # Search emulator instance
        # with E:\ProgramFiles\MuMuPlayer-12.0\shell\MuMuPlayer.exe
        # installation path is E:\ProgramFiles\MuMuPlayer-12.0
        instance = self.emulator_instance
        if instance is None:
            logger.error("Unable to use NemuIpc because emulator instance not found")
            raise RequestHumanTakeover
        if "MuMuPlayerGlobal" in instance.path:
            logger.info(f"当前个人版不支持 MuMuPlayerGlobal：{instance.path}")
            raise RequestHumanTakeover
        try:
            impl = NemuIpcImpl(
                nemu_folder=instance.emulator.abspath("../"),
                instance_id=instance.MuMuPlayer12_id,
                display_id=0,
            )
            impl.connect_with_retry()
        except (NemuIpcIncompatible, NemuIpcError, JobTimeout) as e:
            logger.error(e)
            logger.error("Unable to initialize NemuIpc")
            raise RequestHumanTakeover from e
        else:
            return impl

    def nemu_ipc_release(self):
        if has_cached_property(self, "nemu_ipc"):
            self.nemu_ipc.disconnect()
        del_cached_property(self, "nemu_ipc")
        logger.info("nemu_ipc released")

    def screenshot_nemu_ipc(self):
        image = self.nemu_ipc.screenshot()

        image = cv2.cvtColor(image, cv2.COLOR_BGRA2BGR)
        cv2.flip(image, 0, dst=image)
        return image
