import random
import socket
import time

from adbutils import AdbTimeout

from module.device.method.remove_warning import remove_shell_warning

try:
    # adbutils 0.x
    from adbutils import _AdbStreamConnection as AdbConnection
except ImportError:
    # adbutils >= 1.0
    import subprocess

    # Patch list2cmdline back to subprocess.list2cmdline
    # We expect `screencap | nc 192.168.0.1 20298` instead of `screencap '|' nc 192.168.80.1 20298`
    import adbutils
    from adbutils import AdbConnection

    adbutils._utils.list2cmdline = subprocess.list2cmdline
    adbutils._device.list2cmdline = subprocess.list2cmdline

    # BaseDevice.shell() is missing a check_okay() call before reading output,
    # resulting in an `OKAY` prefix in output.
    def shell(
        self, cmdargs: str | list | tuple, stream: bool = False, timeout: float | None = None, rstrip=True
    ) -> AdbConnection | str:
        if isinstance(cmdargs, (list, tuple)):
            cmdargs = subprocess.list2cmdline(cmdargs)
        if stream:
            timeout = None
        c = self.open_transport(timeout=timeout)
        c.send_command("shell:" + cmdargs)
        c.check_okay()  # check_okay() is missing here
        if stream:
            return c
        output = c.read_until_close()
        return output.rstrip() if rstrip else output

    adbutils._device.BaseDevice.shell = shell

from module.logger import logger

RETRY_TRIES = 5
RETRY_DELAY = 3


def is_port_using(port_num):
    """if port is using by others, return True. else return False"""
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(2)

    try:
        s.bind(("127.0.0.1", port_num))
    except OSError:
        # Address already bind
        return True
    else:
        return False
    finally:
        s.close()


def random_port(port_range):
    """get a random port from port set"""
    new_port = random.choice(list(range(*port_range)))
    if is_port_using(new_port):
        return random_port(port_range)
    return new_port


def recv_all(stream, chunk_size=4096, recv_interval=0.000) -> bytes:
    """
    Args:
        stream:
        chunk_size:
        recv_interval (float): Default to 0.000, use 0.001 if receiving as server

    Returns:
        bytes:

    Raises:
        AdbTimeout
    """
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
        raise AdbTimeout("adb read timeout") from e


def possible_reasons(*args):
    """
    Show possible reasons

        Possible reason #1: <reason_1>
        Possible reason #2: <reason_2>
    """
    for index, reason in enumerate(args):
        reason_number = index + 1
        logger.critical(f"Possible reason #{reason_number}: {reason}")


class PackageNotInstalled(Exception):
    pass


class ImageTruncated(Exception):
    pass


def retry_sleep(trial):
    # 前两次尝试不等待。
    if trial in {0, 1}:
        return 0
    # Failed twice
    if trial == 2:
        return 1
    # Failed more
    return RETRY_DELAY


def handle_adb_error(e):
    """
    Args:
        e (Exception):

    Returns:
        bool: If should retry
    """
    text = str(e)
    if "not found" in text:
        # When you call `adb disconnect <serial>`
        # Or when adb server was killed (low possibility)
        # AdbError(device '127.0.0.1:59865' not found)
        logger.error(e)
        return True
    if "timeout" in text:
        # AdbTimeout(adb read timeout)
        logger.error(e)
        return True
    if "closed" in text:
        # AdbError(closed)
        # Usually after AdbTimeout(adb read timeout)
        # Disconnect and re-connect should fix this.
        logger.error(e)
        return True
    if "device offline" in text:
        # AdbError(device offline)
        # When a device that has been connected wirelessly is disconnected passively,
        # it does not disappear from the adb device list,
        # but will be displayed as offline.
        # In many cases, such as disconnection and recovery caused by network fluctuations,
        # or after VMOS reboot when running Alas on a phone,
        # the device is still available, but it needs to be disconnected and re-connected.
        logger.error(e)
        return True
    if "is offline" in text:
        # RuntimeError: USB device 127.0.0.1:7555 is offline
        # ADB 服务被其他版本抢占后，部分底层调用会返回这种离线文本。
        logger.error(e)
        return True
    if text == "rest":
        # AdbError(rest)
        # Response telling adbd service has reset, client should reconnect
        logger.error(e)
        return True
    # AdbError()
    logger.exception(e)
    possible_reasons(
        "Emulator died, please restart emulator",
        "Serial incorrect, no such device exists or emulator is not running",
    )
    return False


def handle_unknown_host_service(e):
    """
    Args:
        e (Exception):

    Returns:
        bool: If should retry
    """
    text = str(e)
    if "unknown host service" in text:
        # AdbError(unknown host service)
        # Another version of ADB service started, current ADB service has been killed.
        # Usually because user opened a Chinese emulator, which uses ADB from the Stone Age.
        logger.error(e)
        return True
    return False


def get_serial_pair(serial):
    """
    Args:
        serial (str):

    Returns:
        tuple[Optional[str], Optional[str]]: `127.0.0.1:5555+{X}` and `emulator-5554+{X}`, 0 <= X <= 32
    """
    if serial.startswith("127.0.0.1:"):
        try:
            port = int(serial[10:])
            if 5555 <= port <= 5555 + 64:
                return f"127.0.0.1:{port}", f"emulator-{port - 1}"
        except ValueError, IndexError:
            pass
    if serial.startswith("emulator-"):
        try:
            port = int(serial[9:])
            if 5554 <= port <= 5554 + 64:
                return f"127.0.0.1:{port + 1}", f"emulator-{port}"
        except ValueError, IndexError:
            pass

    return None, None
