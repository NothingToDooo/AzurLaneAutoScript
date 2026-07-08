from collections import deque

# deep_* 函数用于访问嵌套字典和列表。
# 这些函数位于热路径，优先保留实测更快的写法。
# 键存在时，直接索引并捕获 KeyError 最快，dict.get 次之，先检查成员最慢。
# 键不存在时，先检查成员最快，dict.get 次之，直接索引并捕获 KeyError 最慢。

INVALID_DEPTH_RANGE_MESSAGE = "Invalid depth range"


def _validate_depth_range(min_depth: int, depth: int) -> None:
    """检查深度参数是否有效。"""
    if 1 <= min_depth <= depth:
        return
    message = f"{INVALID_DEPTH_RANGE_MESSAGE}: min_depth={min_depth}, depth={depth}"
    raise ValueError(message)


def deep_get(d, keys, default=None):
    """
    Get value from nested dict and list
    https://stackoverflow.com/questions/25833613/safe-method-to-get-value-of-nested-dictionary

    Args:
        d (dict):
        keys (list[str], str): Such as ['Scheduler', 'NextRun', 'value']
        default: Default return if key not found.

    Returns:
        Value on given keys
    """
    # 基准成本约为 240 加 30 乘 depth 纳秒。
    if type(keys) is str:
        keys = keys.split(".")

    try:
        for k in keys:
            d = d[k]
    # 没有这个键。
    except KeyError:
        return default
    # 没有这个索引。
    except IndexError:
        return default
    # `keys` 不可迭代，或者 `d` 不是字典。
    # 例如：list indices must be integers or slices, not str。
    except TypeError:
        return default
    else:
        return d


def deep_get_with_error(d, keys):
    """
    Get value from nested dict and list, raise KeyError if key not exists

    Args:
        d (dict):
        keys (list[str], str): Such as ['Scheduler', 'NextRun', 'value']

    Returns:
        Value on given keys

    Raises:
        KeyError: If key not exists
    """
    # 基准成本约为 240 加 30 乘 depth 纳秒。
    if type(keys) is str:
        keys = keys.split(".")

    try:
        for k in keys:
            d = d[k]
    # KeyError 保持原样向外抛出。
    # 没有这个键。
    except IndexError as e:
        raise KeyError from e
    # `keys` 不可迭代，或者 `d` 不是字典。
    # 例如：list indices must be integers or slices, not str。
    except TypeError as e:
        raise KeyError from e
    else:
        return d


def deep_exist(d, keys):
    """
    Check if keys exists in nested dict or list

    Args:
        d (dict):
        keys (str, list): Such as `Scheduler.NextRun.value`

    Returns:
        bool: If key exists
    """
    # 基准成本约为 240 加 30 乘 depth 纳秒。
    if type(keys) is str:
        keys = keys.split(".")

    try:
        for k in keys:
            d = d[k]
    # 没有这个键。
    except KeyError:
        return False
    # 没有这个索引。
    except IndexError:
        return False
    # `keys` 不可迭代，或者 `d` 不是字典。
    # 例如：list indices must be integers or slices, not str。
    except TypeError:
        return False
    else:
        return True


def deep_set(d, keys, value):
    """
    Set value into nested dict safely, imitating deep_get().
    Can only set dict
    """
    # 基准成本约为 150 乘 depth 纳秒。
    if type(keys) is str:
        keys = keys.split(".")

    first = True
    exist = True
    prev_d = None
    prev_k = None
    prev_k2 = None
    try:
        for k in keys:
            if first:
                prev_d = d
                prev_k = k
                first = False
                continue
            try:
                # 成员检查比 get、setdefault 和异常路径更快。
                if exist and prev_k in d:
                    prev_d = d
                    d = d[prev_k]
                else:
                    exist = False
                    new = {}
                    d[prev_k] = new
                    d = new
            except TypeError:
                # `d` 不是字典。
                exist = False
                d = {}
                prev_d[prev_k2] = {prev_k: d}

            prev_k2 = prev_k
            prev_k = k
    # `keys` 不可迭代。
    except TypeError:
        return

    # 最后一个键，写入值。
    try:
        d[prev_k] = value
    # 最后一层的 `d` 不是字典。
    except TypeError:
        prev_d[prev_k2] = {prev_k: value}
        return
    else:
        return


def deep_default(d, keys, value):
    """
    Set value into nested dict safely, imitating deep_get().
    Can only set dict
    """
    # 基准成本约为 150 乘 depth 纳秒。
    if type(keys) is str:
        keys = keys.split(".")

    first = True
    exist = True
    prev_d = None
    prev_k = None
    prev_k2 = None
    try:
        for k in keys:
            if first:
                prev_d = d
                prev_k = k
                first = False
                continue
            try:
                # 成员检查比 get、setdefault 和异常路径更快。
                if exist and prev_k in d:
                    prev_d = d
                    d = d[prev_k]
                else:
                    exist = False
                    new = {}
                    d[prev_k] = new
                    d = new
            except TypeError:
                # `d` 不是字典。
                exist = False
                d = {}
                prev_d[prev_k2] = {prev_k: d}

            prev_k2 = prev_k
            prev_k = k
    # `keys` 不可迭代。
    except TypeError:
        return

    # 最后一个键，写入默认值。
    try:
        d.setdefault(prev_k, value)
    # 最后一层的 `d` 不是字典。
    except AttributeError:
        prev_d[prev_k2] = {prev_k: value}
        return
    else:
        return


def deep_pop(d, keys, default=None):
    """
    Pop value from nested dict and list
    """
    if type(keys) is str:
        keys = keys.split(".")

    try:
        for k in keys[:-1]:
            d = d[k]
        # 不使用 pop(k, default)，这样才能同时弹出列表元素。
        return d.pop(keys[-1])
    # 没有这个键。
    except KeyError:
        return default
    # `keys` 不可迭代，或者 `d` 不是字典。
    # 例如：list indices must be integers or slices, not str。
    except TypeError:
        return default
    # `keys` 超出索引范围。
    except IndexError:
        return default
    # 最后一层的 `d` 不是字典。
    except AttributeError:
        return default


def deep_iter_depth1(data):
    """
    Equivalent to data.items() but suppress error if data is not a dict

    Args:
        data:

    Yields:
        Any: Key
        Any: Value
    """
    try:
        yield from data.items()
    except AttributeError:
        # `data` 不是字典。
        return
    else:
        return


def deep_iter_depth2(data):
    """
    Iter key and value in nested dict of depth 2
    A simplified deep_iter

    Args:
        data:

    Yields:
        Any: Key1
        Any: Key2
        Any: Value
    """
    try:
        for k1, v1 in data.items():
            if type(v1) is dict:
                for k2, v2 in v1.items():
                    yield k1, k2, v2
    except AttributeError:
        # `data` 不是字典。
        return


def deep_iter(data, min_depth=None, depth=3):
    """
    遍历嵌套字典里的键路径和值。

    300us on alas.json depth=3 (530+ rows)
    只遍历 dict。

    Args:
        data:
        min_depth:
        depth:

    Yields:
        list[str]: Key path
        Any: Value
    """
    if min_depth is None:
        min_depth = depth
    _validate_depth_range(min_depth, depth)

    try:
        queue = deque([([], data.items())])
    except AttributeError:
        # `data` 不是字典。
        return

    current = 1
    while current <= depth:
        new_queue = deque()
        for key, items in queue:
            for k, v in items:
                subkey = [*key, k]
                if current == depth:
                    yield subkey, v
                elif type(v) is dict:
                    new_queue.append((subkey, v.items()))
                elif current >= min_depth:
                    yield subkey, v
        queue = new_queue
        current += 1
