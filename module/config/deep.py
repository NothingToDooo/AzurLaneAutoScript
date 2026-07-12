from collections import deque
from collections.abc import Iterable, Iterator, Mapping, Sequence
from datetime import datetime
from typing import Protocol, cast, overload, runtime_checkable

type DeepKey = str | int
type DeepPath = str | Sequence[DeepKey]
type DeepScalar = bool | int | float | str | datetime | None
type DeepValue = DeepScalar | Sequence[DeepValue] | Mapping[str, DeepValue]
type MutableDeepValue = DeepScalar | list[MutableDeepValue] | tuple[MutableDeepValue, ...] | dict[str, MutableDeepValue]
type MutableDeepData = dict[str, MutableDeepValue]


@runtime_checkable
class SupportsItems(Protocol):
    def items(self) -> Iterable[tuple[str, DeepValue]]: ...


# deep_* 位于热路径；实测键存在时直接索引最快，缺失时先检查成员最快。

INVALID_DEPTH_RANGE_MESSAGE = "Invalid depth range"


def _validate_depth_range(min_depth: int, depth: int) -> None:
    if 1 <= min_depth <= depth:
        return
    message = f"{INVALID_DEPTH_RANGE_MESSAGE}: min_depth={min_depth}, depth={depth}"
    raise ValueError(message)


def _deep_item(current: DeepValue, key: DeepKey) -> DeepValue:
    if isinstance(current, Mapping) and isinstance(key, str):
        mapping = cast("Mapping[str, DeepValue]", current)
        return mapping[key]
    if isinstance(current, Sequence) and not isinstance(current, str) and isinstance(key, int):
        sequence = cast("Sequence[DeepValue]", current)
        return sequence[key]
    raise KeyError


@overload
def deep_get(d: DeepValue, keys: DeepPath) -> DeepValue | None: ...


@overload
def deep_get(d: DeepValue, keys: DeepPath, default: None) -> DeepValue | None: ...


@overload
def deep_get[T: DeepValue](d: DeepValue, keys: DeepPath, default: T) -> T: ...


def deep_get[T: DeepValue](d: DeepValue, keys: DeepPath, default: T | None = None) -> DeepValue | T | None:
    """按点分隔字符串或键序列访问嵌套字典、列表；路径无效时返回 default。"""
    normalized_keys: Sequence[DeepKey] = keys.split(".") if type(keys) is str else keys
    current = d
    for key in normalized_keys:
        try:
            current = _deep_item(current, key)
        except KeyError, IndexError:
            return default
    return current


def deep_get_with_error(d: DeepValue, keys: DeepPath) -> DeepValue:
    """按点分隔字符串或键序列访问嵌套值；缺键、越界或类型错误统一抛出 KeyError。"""
    normalized_keys: Sequence[DeepKey] = keys.split(".") if type(keys) is str else keys
    current = d
    for key in normalized_keys:
        try:
            current = _deep_item(current, key)
        except (IndexError, TypeError) as error:
            raise KeyError from error
    return current


def deep_exist(d: DeepValue, keys: DeepPath) -> bool:
    """判断点分隔字符串或键序列指定的嵌套路径是否存在。"""
    try:
        deep_get_with_error(d, keys)
    except KeyError:
        return False
    return True


def _mapping_path(keys: DeepPath) -> list[str]:
    normalized_keys = keys.split(".") if type(keys) is str else list(keys)
    if not normalized_keys or not all(isinstance(key, str) for key in normalized_keys):
        message = "deep mutation paths must contain at least one string key"
        raise ValueError(message)
    return normalized_keys


def deep_set(d: MutableDeepData, keys: DeepPath, value: MutableDeepValue) -> None:
    """按点分隔字符串或键序列原地写入嵌套字典，并创建或替换非字典中间层。"""
    path = _mapping_path(keys)
    current = d
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current[path[-1]] = value


def deep_default(d: MutableDeepData, keys: DeepPath, value: MutableDeepValue) -> None:
    """仅在末键缺失时写入默认值，并创建或替换非字典中间层。"""
    path = _mapping_path(keys)
    current = d
    for key in path[:-1]:
        child = current.get(key)
        if not isinstance(child, dict):
            child = {}
            current[key] = child
        current = child
    current.setdefault(path[-1], value)


@overload
def deep_pop(d: MutableDeepValue, keys: DeepPath) -> MutableDeepValue | None: ...


@overload
def deep_pop[T: MutableDeepValue](d: MutableDeepValue, keys: DeepPath, default: T) -> MutableDeepValue | T: ...


def deep_pop[T: MutableDeepValue](
    d: MutableDeepValue,
    keys: DeepPath,
    default: T | None = None,
) -> MutableDeepValue | T | None:
    """从嵌套字典或列表弹出路径末项；路径无效时返回 default。"""
    normalized_keys: Sequence[DeepKey] = keys.split(".") if type(keys) is str else keys
    current = d
    try:
        for key in normalized_keys[:-1]:
            if isinstance(current, dict) and isinstance(key, str):
                mapping = current
                current = mapping[key]
                continue
            if isinstance(current, list) and isinstance(key, int):
                sequence = current
                current = sequence[key]
                continue
            return default
        last_key = normalized_keys[-1]
        if isinstance(current, dict) and isinstance(last_key, str):
            return current.pop(last_key)
        if isinstance(current, list) and isinstance(last_key, int):
            return current.pop(last_key)
    except KeyError, IndexError:
        return default
    return default


def deep_iter_depth1(data: SupportsItems | DeepValue) -> Iterator[tuple[str, DeepValue]]:
    """产出一层字典的 (key, value)；非映射输入不产出内容。"""
    if isinstance(data, SupportsItems):
        yield from data.items()


def deep_iter_depth2(data: SupportsItems | DeepValue) -> Iterator[tuple[str, str, DeepValue]]:
    """产出二层字典的 (key1, key2, value)；非映射输入不产出内容。"""
    if not isinstance(data, SupportsItems):
        return
    for k1, v1 in data.items():
        if type(v1) is dict:
            mapping = cast("dict[str, DeepValue]", v1)
            for k2, v2 in mapping.items():
                yield k1, k2, v2


def deep_iter(
    data: SupportsItems | DeepValue,
    min_depth: int | None = None,
    depth: int = 3,
) -> Iterator[tuple[list[str], DeepValue]]:
    """广度遍历嵌套字典，产出 min_depth 到 depth 的 (键路径, 值)。

    仅深入 dict；深度范围不满足 `1 <= min_depth <= depth` 时抛出 ValueError。
    """
    if min_depth is None:
        min_depth = depth
    _validate_depth_range(min_depth, depth)

    if not isinstance(data, SupportsItems):
        return
    queue: deque[tuple[list[str], Iterable[tuple[str, DeepValue]]]] = deque([([], data.items())])

    current = 1
    while current <= depth:
        new_queue: deque[tuple[list[str], Iterable[tuple[str, DeepValue]]]] = deque()
        for key, items in queue:
            for k, v in items:
                subkey = [*key, k]
                if current == depth:
                    yield subkey, v
                elif type(v) is dict:
                    mapping = cast("dict[str, DeepValue]", v)
                    new_queue.append((subkey, mapping.items()))
                elif current >= min_depth:
                    yield subkey, v
        queue = new_queue
        current += 1
