MUMU12_SERIAL_EXAMPLE = "127.0.0.1:16384"
MUMU12_PORT_BASE = 16384
MUMU12_PORT_STEP = 32
MUMU12_MAX_INSTANCES = 32
MUMU12_PORT_OFFSETS = {-2, -1, 0, 1, 2}
MUMU12_HOST = "127.0.0.1"


def mumu12_serial_to_id(serial: str) -> int | None:
    """
    从 MuMu12 TCP serial 推算实例 ID。
    """
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
        return index
    return None


def is_mumu12_serial(serial: str) -> bool:
    """
    判断 serial 是否属于当前个人版支持的 MuMu12 TCP 端口族。
    """
    return mumu12_serial_to_id(serial) is not None
