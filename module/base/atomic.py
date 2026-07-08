import os
import random
import string
import time
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any, NoReturn, cast

if TYPE_CHECKING:
    from collections.abc import Iterable

WINDOWS_MAX_ATTEMPT = 5
WINDOWS_RETRY_DELAY = 0.05
type FilePath = str | os.PathLike[str]


def _as_path(file: FilePath) -> Path:
    return Path(file)


def random_id() -> str:
    """生成用于临时文件名的短随机 ID。"""
    return "".join(random.sample(string.ascii_letters + string.digits, 6))


def is_tmp_file(file: str) -> bool:
    """判断文件名是否是本模块生成的临时文件。"""
    if not file.endswith(".tmp"):
        return False
    dot = file[-11:-10]
    if not dot:
        return False
    return file[-10:-4].isalnum()


def to_tmp_file(file: FilePath) -> str:
    """把目标路径转换成同目录临时路径。"""
    return f"{os.fspath(file)}.{random_id()}.tmp"


def to_nontmp_file(file: str) -> str:
    """把本模块生成的临时路径还原为目标路径。"""
    if is_tmp_file(file):
        return file[:-11]
    return file


def windows_attempt_delay(attempt: int) -> float:
    """返回 Windows 文件占用重试等待时间。"""
    return 2**attempt * WINDOWS_RETRY_DELAY


def _raise_after_retry(file: FilePath, action: str) -> NoReturn:
    raise PermissionError(f"Unable to {action} {os.fspath(file)!r} after {WINDOWS_MAX_ATTEMPT} attempts")


def replace_tmp(tmp: FilePath, file: FilePath) -> None:
    """把临时路径原子替换为目标路径。"""
    last_error = None
    for attempt in range(WINDOWS_MAX_ATTEMPT):
        try:
            _as_path(tmp).replace(file)
        except PermissionError as e:
            last_error = e
            time.sleep(windows_attempt_delay(attempt))
            continue
        except FileNotFoundError:
            raise
        except OSError as e:
            last_error = e
            break
        else:
            return

    with suppress(OSError):
        _as_path(tmp).unlink()
    if last_error is not None:
        raise last_error from None
    _raise_after_retry(file, "replace")


def atomic_replace(replace_from: FilePath, replace_to: FilePath) -> None:
    """原子替换文件或目录。"""
    last_error = None
    for attempt in range(WINDOWS_MAX_ATTEMPT):
        try:
            _as_path(replace_from).replace(replace_to)
        except PermissionError as e:
            last_error = e
            time.sleep(windows_attempt_delay(attempt))
            continue
        except FileNotFoundError:
            raise
        except OSError as e:
            last_error = e
            break
        else:
            return

    if last_error is not None:
        raise last_error from None
    _raise_after_retry(replace_to, "replace")


def _write_once(file: FilePath, data: object) -> None:
    path = _as_path(file)
    if isinstance(data, str):
        mode = "w"
        encoding = "utf-8"
        newline = ""
    else:
        mode = "wb"
        encoding = None
        newline = None
        if isinstance(data, bytes | bytearray):
            data = memoryview(data)

    try:
        with path.open(mode=mode, encoding=encoding, newline=newline) as handle:
            handle.write(cast("Any", data))
            handle.flush()
            os.fsync(handle.fileno())
    except FileNotFoundError:
        if path.parent != Path():
            path.parent.mkdir(parents=True, exist_ok=True)
        with path.open(mode=mode, encoding=encoding, newline=newline) as handle:
            handle.write(cast("Any", data))
            handle.flush()
            os.fsync(handle.fileno())


def file_write(file: FilePath, data: object) -> None:
    """写入文件，自动创建父目录。"""
    _write_once(file, data)


def file_write_stream(file: FilePath, data_generator: Iterable[str] | Iterable[bytes]) -> bool:
    """流式写入文件；生成器为空时不创建文件。"""
    data_iter = iter(data_generator)
    try:
        first_chunk = next(data_iter)
    except StopIteration:
        return False

    path = _as_path(file)
    if isinstance(first_chunk, str):
        mode = "w"
        encoding = "utf-8"
        newline = ""
    else:
        mode = "wb"
        encoding = None
        newline = None

    try:
        with path.open(mode=mode, encoding=encoding, newline=newline) as handle:
            handle.write(first_chunk)
            handle.writelines(data_iter)
            handle.flush()
            os.fsync(handle.fileno())
    except FileNotFoundError:
        if path.parent != Path():
            path.parent.mkdir(parents=True, exist_ok=True)
        with path.open(mode=mode, encoding=encoding, newline=newline) as handle:
            handle.write(first_chunk)
            handle.writelines(data_iter)
            handle.flush()
            os.fsync(handle.fileno())
    return True


def atomic_write(file: FilePath, data: object) -> None:
    """通过临时文件原子写入目标文件。"""
    temp = to_tmp_file(file)
    file_write(temp, data)
    replace_tmp(temp, file)


def atomic_write_stream(file: FilePath, data_generator: Iterable[str] | Iterable[bytes]) -> None:
    """通过临时文件流式原子写入目标文件。"""
    temp = to_tmp_file(file)
    if file_write_stream(temp, data_generator):
        replace_tmp(temp, file)


def file_read_text(file: FilePath, encoding: str = "utf-8", errors: str = "strict") -> str:
    try:
        with _as_path(file).open(encoding=encoding, errors=errors) as handle:
            return handle.read()
    except FileNotFoundError:
        return ""


def file_read_text_stream(
    file: FilePath, encoding: str = "utf-8", errors: str = "strict", chunk_size: int = 8192
) -> Iterable[str]:
    try:
        with _as_path(file).open(encoding=encoding, errors=errors) as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    return
                yield chunk
    except FileNotFoundError:
        return


def file_read_bytes(file: FilePath) -> bytes:
    try:
        with _as_path(file).open(mode="rb", buffering=0) as handle:
            return handle.read()
    except FileNotFoundError:
        return b""


def file_read_bytes_stream(file: FilePath, chunk_size: int = 8192) -> Iterable[bytes]:
    try:
        with _as_path(file).open(mode="rb") as handle:
            while True:
                chunk = handle.read(chunk_size)
                if not chunk:
                    return
                yield chunk
    except FileNotFoundError:
        return


def atomic_read_text(file: FilePath, encoding: str = "utf-8", errors: str = "strict") -> str:
    last_error = None
    for attempt in range(WINDOWS_MAX_ATTEMPT):
        try:
            return file_read_text(file, encoding=encoding, errors=errors)
        except PermissionError as e:
            last_error = e
            time.sleep(windows_attempt_delay(attempt))
    if last_error is not None:
        raise last_error from None
    _raise_after_retry(file, "read")


def atomic_read_text_stream(
    file: FilePath, encoding: str = "utf-8", errors: str = "strict", chunk_size: int = 8192
) -> Iterable[str]:
    last_error = None
    for attempt in range(WINDOWS_MAX_ATTEMPT):
        try:
            yield from file_read_text_stream(file, encoding=encoding, errors=errors, chunk_size=chunk_size)
        except PermissionError as e:
            last_error = e
            time.sleep(windows_attempt_delay(attempt))
            continue
        else:
            return
    if last_error is not None:
        raise last_error from None


def atomic_read_bytes(file: FilePath) -> bytes:
    last_error = None
    for attempt in range(WINDOWS_MAX_ATTEMPT):
        try:
            return file_read_bytes(file)
        except PermissionError as e:
            last_error = e
            time.sleep(windows_attempt_delay(attempt))
    if last_error is not None:
        raise last_error from None
    _raise_after_retry(file, "read")


def atomic_read_bytes_stream(file: FilePath, chunk_size: int = 8192) -> Iterable[bytes]:
    last_error = None
    for attempt in range(WINDOWS_MAX_ATTEMPT):
        try:
            yield from file_read_bytes_stream(file, chunk_size=chunk_size)
        except PermissionError as e:
            last_error = e
            time.sleep(windows_attempt_delay(attempt))
            continue
        else:
            return
    if last_error is not None:
        raise last_error from None


def file_remove(file: FilePath) -> None:
    with suppress(FileNotFoundError):
        _as_path(file).unlink()


def atomic_remove(file: FilePath) -> None:
    last_error = None
    for attempt in range(WINDOWS_MAX_ATTEMPT):
        try:
            file_remove(file)
        except PermissionError as e:
            last_error = e
            time.sleep(windows_attempt_delay(attempt))
        else:
            return
    if last_error is not None:
        raise last_error from None


def _remove_not_directory(path: FilePath) -> bool:
    file_remove(path)
    return True


def _remove_empty_folder(path: Path) -> bool:
    try:
        path.rmdir()
    except FileNotFoundError:
        return True
    except NotADirectoryError:
        return _remove_not_directory(path)
    except OSError:
        return False
    return True


def folder_rmtree(folder: FilePath, may_symlinks: bool = True) -> bool:
    try:
        path = _as_path(folder)
        if may_symlinks and path.is_symlink():
            file_remove(path)
            return True
        with os.scandir(path) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    folder_rmtree(entry.path, may_symlinks=False)
                else:
                    with suppress(PermissionError):
                        file_remove(entry.path)
    except FileNotFoundError:
        return True
    except NotADirectoryError:
        return _remove_not_directory(folder)

    return _remove_empty_folder(path)


def atomic_rmtree(folder: FilePath) -> None:
    """把目录先原子改名为临时目录，再递归删除。"""
    temp = to_tmp_file(folder)
    try:
        atomic_replace(folder, temp)
    except FileNotFoundError:
        return
    folder_rmtree(temp)


def atomic_failure_cleanup(folder: FilePath, recursive: bool = False) -> None:
    """启动时清理残留临时文件。"""
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if is_tmp_file(entry.name):
                    with suppress(OSError):
                        if entry.is_dir(follow_symlinks=False):
                            folder_rmtree(entry.path, may_symlinks=False)
                        else:
                            file_remove(entry.path)
                elif recursive:
                    with suppress(OSError):
                        if entry.is_dir(follow_symlinks=False):
                            atomic_failure_cleanup(entry.path, recursive=True)
    except FileNotFoundError:
        return
    except NotADirectoryError:
        file_remove(folder)
    except OSError:
        return
