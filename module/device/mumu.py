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


def mumu12_serial_to_id(serial: str) -> int | None:
    parsed = MuMuSerial.parse(serial)
    return None if parsed is None else parsed.instance_id


def is_mumu12_serial(serial: str) -> bool:
    return mumu12_serial_to_id(serial) is not None


def mumu12_shifted_serials(serial: str) -> list[str]:
    parsed = MuMuSerial.parse(serial)
    return [] if parsed is None else parsed.shifted_candidates()
