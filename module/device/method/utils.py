import random
import socket
import time

from adbutils import AdbConnection, AdbTimeout

from module.device.method.remove_warning import remove_shell_warning
from module.logger import logger

RETRY_TRIES = 5
RETRY_DELAY = 3


def is_port_using(port_num: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)

    try:
        s.bind(("127.0.0.1", port_num))
    except OSError:
        return True
    else:
        return False
    finally:
        s.close()


def random_port(port_range: tuple[int, int]) -> int:
    new_port = random.choice(list(range(*port_range)))
    if is_port_using(new_port):
        return random_port(port_range)
    return new_port


def recv_all(stream: AdbConnection | socket.socket, chunk_size: int = 4096, recv_interval: float = 0.000) -> bytes:
    """recv_interval 单位为秒；服务端接收建议用 0.001，10 秒无数据抛出 AdbTimeout。"""
    if isinstance(stream, AdbConnection):
        stream = stream.conn
        stream.settimeout(10)
    else:
        stream.settimeout(10)

    try:
        fragments = []
        while 1:
            chunk = stream.recv(chunk_size)
            if chunk:
                fragments.append(chunk)
                # See https://stackoverflow.com/questions/23837827/python-server-program-has-high-cpu-usage/41749820#41749820
                time.sleep(recv_interval)
            else:
                break
        return remove_shell_warning(b"".join(fragments))
    except TimeoutError as e:
        message = "adb read timeout"
        raise AdbTimeout(message) from e


def possible_reasons(*args: str) -> None:
    for index, reason in enumerate(args):
        reason_number = index + 1
        logger.critical(f"Possible reason #{reason_number}: {reason}")


class PackageNotInstalled(Exception):
    pass


class ImageTruncated(Exception):
    pass


def retry_sleep(trial: int) -> int:
    # 前两次尝试不等待。
    if trial in {0, 1}:
        return 0
    if trial == 2:
        return 1
    return RETRY_DELAY


_RETRYABLE_ADB_ERROR_SNIPPETS = (
    "not found",
    "timeout",
    "closed",
    "device offline",
    "is offline",
)


def is_retryable_adb_error(text: str) -> bool:
    # `rest` 是 adbd 重置响应，其他片段来自常见断线、超时和离线错误。
    return text == "rest" or any(snippet in text for snippet in _RETRYABLE_ADB_ERROR_SNIPPETS)


def handle_adb_error(e: BaseException) -> bool:
    text = str(e)
    if is_retryable_adb_error(text):
        logger.error(e)
        return True
    logger.exception(e)
    possible_reasons(
        "Emulator died, please restart emulator",
        "Serial incorrect, no such device exists or emulator is not running",
    )
    return False


def handle_unknown_host_service(e: BaseException) -> bool:
    text = str(e)
    if "unknown host service" in text:
        # AdbError(unknown host service)
        # Another version of ADB service started, current ADB service has been killed.
        # Usually because user opened a Chinese emulator, which uses ADB from the Stone Age.
        logger.error(e)
        return True
    return False
