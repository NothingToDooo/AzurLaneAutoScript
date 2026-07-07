from typing import overload


@overload
def remove_shell_warning(s: bytes) -> bytes: ...


@overload
def remove_shell_warning(s: str) -> str: ...


def remove_shell_warning(s):
    r"""
    移除 shell 输出前面的告警文本。

    1. VMOS shell 里的 linker 告警。
    https://github.com/LmeSzinc/AzurLaneAutoScript/issues/1425

    WARNING: linker: [vdso]: unused DT entry: type 0x70000001 arg 0x0\n
    \x89PNG\r\n\x1a\n\x00\x00\x00\rIH...

    2. 连续执行多条命令时，linker 告警可能出现多次。

    mek_8q:/dev # getprop | grep gnss
    WARNING: linker: Warning: "[vdso]" unused DT entry: unknown processor-specific (type 0x70000001 arg 0x0) (ignoring)
    WARNING: linker: Warning: "[vdso]" unused DT entry: unknown processor-specific (type 0x70000001 arg 0x0) (ignoring)
    [init.svc.gnss_service]: [running]
    [init.svc_debug_pid.gnss_service]: [406]
    [ro.boottime.gnss_service]: [27308752875]

    Args:
        s (str | bytes)：shell 输出。

    Returns:
        str | bytes：移除告警后的 shell 输出。
    """
    if isinstance(s, bytes):
        while 1:
            if s.startswith(b"WARNING: linker:"):
                _, _, s = s.partition(b"\n")
            else:
                break
    elif isinstance(s, str):
        while 1:
            if s.startswith("WARNING: linker:"):
                _, _, s = s.partition("\n")
            else:
                break

    return s
