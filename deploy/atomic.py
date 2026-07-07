import os
import random
import string
import time
from contextlib import suppress
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterable

IS_WINDOWS = os.name == "nt"
# Max attempt if another process is reading/writing, effective only on Windows
WINDOWS_MAX_ATTEMPT = 5
# Base time to wait between retries (seconds)
WINDOWS_RETRY_DELAY = 0.05


def random_id():
    """
    Returns:
        str: Random ID, like "sTD2kF"
    """
    # 6 random letter (62^6 combinations) would be enough
    return "".join(random.sample(string.ascii_letters + string.digits, 6))


def is_tmp_file(file: str) -> bool:
    """
    Check if a filename is tmp file
    """
    # Check suffix first to reduce regex calls
    if not file.endswith(".tmp"):
        return False
    # Check temp file format
    dot = file[-11:-10]
    if not dot:
        return False
    rid = file[-10:-4]
    return rid.isalnum()


def to_tmp_file(file: str) -> str:
    """
    Convert a filename or directory name to tmp
    filename -> filename.sTD2kF.tmp
    """
    suffix = random_id()
    return f"{file}.{suffix}.tmp"


def to_nontmp_file(file: str) -> str:
    """
    Convert a tmp filename or directory name to original file
    filename.sTD2kF.tmp -> filename
    """
    if is_tmp_file(file):
        return file[:-11]
    return file


def windows_attempt_delay(attempt: int) -> float:
    """
    Exponential Backoff if file is in use on Windows

    Args:
        attempt: Current attempt, starting from 0

    Returns:
        float: Seconds to wait
    """
    return 2**attempt * WINDOWS_RETRY_DELAY


def replace_tmp(tmp: str, file: str):
    """
    Replace temp file to file

    Raises:
        PermissionError: (Windows only) If another process is still reading the file and all retries failed
        FileNotFoundError: If tmp file gets deleted unexpectedly
    """
    if IS_WINDOWS:
        # PermissionError on Windows if another process is reading
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                # Atomic operation
                os.replace(tmp, file)
                # success
                return
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
            except FileNotFoundError:
                # tmp file gets deleted unexpectedly
                raise
            except Exception as e:
                last_error = e
                break
    else:
        # Linux and Mac allow existing reading
        try:
            # Atomic operation
            os.replace(tmp, file)
            # success
            return
        except FileNotFoundError:
            raise
        except Exception as e:
            last_error = e

    # 写入失败时尽力清理临时文件；清理失败仍然抛出原始写入错误。
    with suppress(Exception):
        os.unlink(tmp)
    if last_error is not None:
        raise last_error from None


def atomic_replace(replace_from: str, replace_to: str):
    """
    Replace file or directory

    Raises:
        PermissionError: (Windows only) If another process is still reading the file and all retries failed
        FileNotFoundError:
    """
    if IS_WINDOWS:
        # PermissionError on Windows if another process is reading
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                # Atomic operation
                os.replace(replace_from, replace_to)
                # success
                return
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
            except FileNotFoundError:
                raise
            except Exception as e:
                last_error = e
                break
        if last_error is not None:
            raise last_error from None
    else:
        # Linux and Mac
        os.replace(replace_from, replace_to)


def file_write(file: str, data: str | bytes):
    """
    Write data into file, auto create directory
    Auto determines write mode based on the type of data.
    """
    if isinstance(data, str):
        mode = "w"
        encoding = "utf-8"
        newline = ""
    elif isinstance(data, bytes):
        mode = "wb"
        encoding = None
        newline = None
        # Create memoryview as Pathlib do
        data = memoryview(data)
    else:
        typename = str(type(data))
        if typename == "<class 'numpy.ndarray'>":
            mode = "wb"
            encoding = None
            newline = None
        else:
            mode = "w"
            encoding = "utf-8"
            newline = ""

    try:
        # Write temp file
        with open(file, mode=mode, encoding=encoding, newline=newline) as f:
            f.write(data)
            # Ensure data flush to disk
            f.flush()
            os.fsync(f.fileno())
    except FileNotFoundError:
        # Create parent directory
        directory = os.path.dirname(file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # Write again
        with open(file, mode=mode, encoding=encoding, newline=newline) as f:
            f.write(data)
            # Ensure data flush to disk
            f.flush()
            os.fsync(f.fileno())


def file_write_stream(file: str, data_generator):
    """
    Only creates a file if the generator yields at least one data chunk.
    Auto determines write mode based on the type of first chunk.

    Args:
        file: Target file path
        data_generator: An iterable that yields data chunks (str or bytes)
    """
    # Convert generator to iterator to ensure we can peek at first chunk
    data_iter = iter(data_generator)

    # Try to get the first chunk
    try:
        first_chunk = next(data_iter)
    except StopIteration:
        # Generator is empty, no file will be created
        return

    # Determine mode, encoding and newline from first chunk
    if isinstance(first_chunk, str):
        mode = "w"
        encoding = "utf-8"
        newline = ""
    elif isinstance(first_chunk, bytes):
        mode = "wb"
        encoding = None
        newline = None
    else:
        # Default to text mode for other types
        mode = "w"
        encoding = "utf-8"
        newline = ""

    try:
        # Write temp file
        with open(file, mode=mode, encoding=encoding, newline=newline) as f:
            f.write(first_chunk)
            f.writelines(data_iter)
            # Ensure data flush to disk
            f.flush()
            os.fsync(f.fileno())
    except FileNotFoundError:
        # Create parent directory
        directory = os.path.dirname(file)
        if directory:
            os.makedirs(directory, exist_ok=True)
        # Write again
        with open(file, mode=mode, encoding=encoding, newline=newline) as f:
            f.write(first_chunk)
            f.writelines(data_iter)
            # Ensure data flush to disk
            f.flush()
            os.fsync(f.fileno())


def atomic_write(
    file: str,
    data: str | bytes,
):
    """
    Atomic file write with minimal IO operation
    and handles cases where file might be read by another process.

    os.replace() is an atomic operation among all OS,
    we write to temp file then do os.replace()

    Args:
        file:
        data:
    """
    temp = to_tmp_file(file)
    file_write(temp, data)
    replace_tmp(temp, file)


def atomic_write_stream(
    file: str,
    data_generator,
):
    """
    Atomic file write with streaming data support.
    Handles cases where file might be read by another process.

    os.replace() is an atomic operation among all OS,
    we write to temp file then do os.replace()

    Args:
        file: Target file path
        data_generator: An iterable that yields data chunks (str or bytes)
    """
    temp = to_tmp_file(file)
    file_write_stream(temp, data_generator)
    replace_tmp(temp, file)


def file_read_text(file: str, encoding: str = "utf-8", errors: str = "strict") -> str:
    """
    Args:
        file:
        encoding:
        errors: 'strict', 'ignore', 'replace' and any other errors mode in open()
    """
    try:
        with open(file, encoding=encoding, errors=errors) as f:
            return f.read()
    except FileNotFoundError:
        return ""


def file_read_text_stream(
    file: str, encoding: str = "utf-8", errors: str = "strict", chunk_size: int = 8192
) -> Iterable[str]:
    """
    Args:
        file:
        encoding:
        errors: 'strict', 'ignore', 'replace' and any other errors mode in open()
        chunk_size:
    """
    try:
        with open(file, encoding=encoding, errors=errors) as f:
            while 1:
                chunk = f.read(chunk_size)
                if not chunk:
                    return
                yield chunk
    except FileNotFoundError:
        return


def file_read_bytes(file: str) -> bytes:
    """
    Args:
        file:
    """
    try:
        # No python-side buffering when reading the entire file to speedup reading
        # https://github.com/python/cpython/pull/122111
        with open(file, mode="rb", buffering=0) as f:
            return f.read()
    except FileNotFoundError:
        return b""


def file_read_bytes_stream(file: str, chunk_size: int = 8192) -> Iterable[bytes]:
    """
    Args:
        file:
        chunk_size:
    """
    try:
        with open(file, mode="rb") as f:
            while 1:
                chunk = f.read(chunk_size)
                if not chunk:
                    return
                yield chunk
    except FileNotFoundError:
        return


def atomic_read_text(file: str, encoding: str = "utf-8", errors: str = "strict") -> str:
    """
    Atomic file read with minimal IO operation

    Args:
        file:
        encoding:
        errors: 'strict', 'ignore', 'replace' and any other errors mode in open()
    """
    if IS_WINDOWS:
        # PermissionError on Windows if another process is replacing
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                return file_read_text(file, encoding=encoding, errors=errors)
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
        if last_error is not None:
            raise last_error from None
        raise PermissionError(f"Unable to read {file!r} after {WINDOWS_MAX_ATTEMPT} attempts")

    # Linux 和 Mac 允许边替换边读取。
    return file_read_text(file, encoding=encoding, errors=errors)


def atomic_read_text_stream(
    file: str, encoding: str = "utf-8", errors: str = "strict", chunk_size: int = 8192
) -> Iterable[str]:
    """
    Args:
        file:
        encoding:
        errors: 'strict', 'ignore', 'replace' and any other errors mode in open()
        chunk_size:
    """
    if IS_WINDOWS:
        # PermissionError on Windows if another process is replacing
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                yield from file_read_text_stream(file, encoding=encoding, errors=errors, chunk_size=chunk_size)
                return
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
        if last_error is not None:
            raise last_error from None
    else:
        # Linux and Mac allow reading while replacing
        yield from file_read_text_stream(file, encoding=encoding, errors=errors, chunk_size=chunk_size)
        return


def atomic_read_bytes(file: str) -> bytes:
    """
    Atomic file read with minimal IO operation
    """
    if IS_WINDOWS:
        # PermissionError on Windows if another process is replacing
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                return file_read_bytes(file)
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
        if last_error is not None:
            raise last_error from None
        raise PermissionError(f"Unable to read {file!r} after {WINDOWS_MAX_ATTEMPT} attempts")

    # Linux 和 Mac 允许边替换边读取。
    return file_read_bytes(file)


def atomic_read_bytes_stream(file: str, chunk_size: int = 8192) -> Iterable[bytes]:
    """
    Args:
        file:
        chunk_size:
    """
    if IS_WINDOWS:
        # PermissionError on Windows if another process is replacing
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                yield from file_read_bytes_stream(file, chunk_size=chunk_size)
                return
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
        if last_error is not None:
            raise last_error from None
    else:
        # Linux and Mac allow reading while replacing
        yield from file_read_bytes_stream(file, chunk_size=chunk_size)
        return


def file_remove(file: str):
    """
    非原子地删除文件。
    """
    with suppress(FileNotFoundError):
        os.unlink(file)


def atomic_remove(file: str):
    """
    Atomic file remove

    Args:
        file:
    """
    if IS_WINDOWS:
        # PermissionError on Windows if another process is replacing
        last_error = None
        for attempt in range(WINDOWS_MAX_ATTEMPT):
            try:
                return file_remove(file)
            except PermissionError as e:
                last_error = e
                delay = windows_attempt_delay(attempt)
                time.sleep(delay)
                continue
        if last_error is not None:
            raise last_error from None
        return None

    # Linux 和 Mac 允许在其他进程读取时删除。
    # 目录项会被移除，但文件占用的存储空间会在原文件不再使用后才释放。
    file_remove(file)
    return None


def folder_rmtree(folder, may_symlinks=True):
    """
    Recursively remove a folder and its content

    Args:
        folder:
        may_symlinks: Default to True
            False if you already know it's not a symlink

    Returns:
        bool: If success
    """
    try:
        # 如果是符号链接，只删除链接本身。
        if may_symlinks and os.path.islink(folder):
            file_remove(folder)
            return True
        # 遍历文件夹。
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_dir(follow_symlinks=False):
                    folder_rmtree(entry.path, may_symlinks=False)
                else:
                    # 文件或符号链接；只删除链接本身，不删除链接目标。
                    with suppress(PermissionError):
                        file_remove(entry.path)

    except FileNotFoundError:
        # 需要清理的目录不存在，不需要处理。
        return True
    except NotADirectoryError:
        file_remove(folder)
        return True

    # 删除空文件夹；如果仍非空，可能抛出 OSError。
    try:
        os.rmdir(folder)
        return True
    except FileNotFoundError:
        return True
    except NotADirectoryError:
        file_remove(folder)
        return True
    except OSError:
        return False


def atomic_rmtree(folder: str):
    """
    Atomic folder rmtree
    Rename folder as temp folder and remove it,
    folder can be removed by atomic_failure_cleanup at next startup if remove gets interrupted
    """
    temp = to_tmp_file(folder)
    try:
        atomic_replace(folder, temp)
    except FileNotFoundError:
        # Folder not exist, no need to rmtree
        return
    folder_rmtree(temp)


def atomic_failure_cleanup(folder: str, recursive: bool = False):
    """
    Cleanup remaining temp file under given path.
    In most cases there should be no remaining temp files unless write process get interrupted.

    This method should only be called at startup
    to avoid deleting temp files that another process is writing.
    """
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if is_tmp_file(entry.name):
                    # 临时文件可能仍被其他进程占用；失败时留到下次启动再清理。
                    with suppress(Exception):
                        if entry.is_dir(follow_symlinks=False):
                            folder_rmtree(entry.path, may_symlinks=False)
                        else:
                            file_remove(entry.path)
                else:
                    if recursive:
                        # 递归清理是附带动作，单个目录失败不应中断启动。
                        with suppress(Exception):
                            if entry.is_dir(follow_symlinks=False):
                                atomic_failure_cleanup(entry.path, recursive=True)

    except FileNotFoundError:
        # 需要清理的目录不存在。
        return
    except NotADirectoryError:
        file_remove(folder)
    except Exception:
        # 清理失败不影响启动；残留临时文件可下次再处理。
        return
