import re
from dataclasses import dataclass

MUMU12_SERIAL_EXAMPLE = "127.0.0.1:16384"
MUMU12_PORT_BASE = 16384
MUMU12_PORT_STEP = 32
MUMU12_MAX_INSTANCES = 32
MUMU12_PORT_OFFSETS = {-2, -1, 0, 1, 2}
MUMU12_SHIFT_PORT_OFFSETS = (1, -1, 2, -2)
MUMU12_HOST = "127.0.0.1"


@dataclass(frozen=True, slots=True)
class MuMuSerial:
    value: str
    port: int
    instance_id: int

    @classmethod
    def parse(cls, serial: str) -> MuMuSerial | None:
        host, sep, port_text = serial.partition(":")
        if sep != ":" or host != MUMU12_HOST:
            return None

        try:
            port = int(port_text)
        except ValueError:
            return None

        index, offset = divmod(port - MUMU12_PORT_BASE + MUMU12_PORT_STEP // 2, MUMU12_PORT_STEP)
        offset -= MUMU12_PORT_STEP // 2
        if 0 <= index < MUMU12_MAX_INSTANCES and offset in MUMU12_PORT_OFFSETS:
            return cls(value=serial, port=port, instance_id=index)
        return None

    def shifted_candidates(self) -> list[str]:
        """返回 MuMu12 动态端口漂移时可尝试连接的相邻 serial。"""
        return [f"{MUMU12_HOST}:{self.port + offset}" for offset in MUMU12_SHIFT_PORT_OFFSETS]


def revise_mumu12_serial(serial: str) -> str:
    """修正常见手填 MuMu12 serial 错误。"""
    serial = serial.strip().replace(" ", "")
    # 127。0。0。1：5555
    serial = serial.replace("。", ".").replace("，", ".").replace(",", ".").replace("：", ":")
    # 127.0.0.1.5555
    serial = serial.replace("127.0.0.1.", "127.0.0.1:")
    # 5555,16384。逗号已被替换为点，实际形态是 5555.16384。
    if "." in serial:
        left, _, right = serial.partition(".")
        try:
            left = int(left)
            right = int(right)
            if 5500 < left < 6000 and 16300 < right < 20000:
                serial = str(right)
        except ValueError:
            pass
    # 16384
    if serial.isdigit():
        try:
            port = int(serial)
            if 1000 < port < 65536:
                serial = f"{MUMU12_HOST}:{port}"
        except ValueError:
            pass
    # MuMu模拟器12127.0.0.1:16384
    if "模拟" in serial:
        result = re.search(r"(127\.\d+\.\d+\.\d+:\d+)", serial)
        if result:
            serial = result.group(1)
    # 12127.0.0.1:16384
    serial = serial.replace("12127.0.0.1", "127.0.0.1")
    # auto127.0.0.1:16384
    return serial.replace("auto127.0.0.1", "127.0.0.1").replace("autoemulator", "emulator")


def mumu12_serial_to_id(serial: str) -> int | None:
    """
    从 MuMu12 TCP serial 推算实例 ID。
    """
    parsed = MuMuSerial.parse(serial)
    return None if parsed is None else parsed.instance_id


def is_mumu12_serial(serial: str) -> bool:
    """
    判断 serial 是否属于当前个人版支持的 MuMu12 TCP 端口族。
    """
    return mumu12_serial_to_id(serial) is not None


def mumu12_shifted_serials(serial: str) -> list[str]:
    parsed = MuMuSerial.parse(serial)
    return [] if parsed is None else parsed.shifted_candidates()
