from typing import overload


@overload
def remove_shell_warning(s: bytes) -> bytes: ...


@overload
def remove_shell_warning(s: str) -> str: ...


def remove_shell_warning(s):
    """VMOS 可能在 shell 真实输出前反复插入 `WARNING: linker:` 行。

    只移除连续的前缀告警，见 https://github.com/LmeSzinc/AzurLaneAutoScript/issues/1425。
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
