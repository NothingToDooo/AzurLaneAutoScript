from collections import deque

# deep_* 位于热路径；实测键存在时直接索引最快，缺失时先检查成员最快。

INVALID_DEPTH_RANGE_MESSAGE = "Invalid depth range"


def _validate_depth_range(min_depth: int, depth: int) -> None:
    if 1 <= min_depth <= depth:
        return
    message = f"{INVALID_DEPTH_RANGE_MESSAGE}: min_depth={min_depth}, depth={depth}"
    raise ValueError(message)


def deep_get(d, keys, default=None):
    """按点分隔字符串或键序列访问嵌套字典、列表；路径无效时返回 default。"""
    if type(keys) is str:
        keys = keys.split(".")

    try:
        for k in keys:
            d = d[k]
    except KeyError:
        return default
    except IndexError:
        return default
    except TypeError:
        return default
    else:
        return d


def deep_get_with_error(d, keys):
    """按点分隔字符串或键序列访问嵌套值；缺键、越界或类型错误统一抛出 KeyError。"""
    if type(keys) is str:
        keys = keys.split(".")

    try:
        for k in keys:
            d = d[k]
    except IndexError as e:
        raise KeyError from e
    except TypeError as e:
        raise KeyError from e
    else:
        return d


def deep_exist(d, keys):
    """判断点分隔字符串或键序列指定的嵌套路径是否存在。"""
    if type(keys) is str:
        keys = keys.split(".")

    try:
        for k in keys:
            d = d[k]
    except KeyError:
        return False
    except IndexError:
        return False
    except TypeError:
        return False
    else:
        return True


def _replace_parent_with_dict(prev_d, prev_k2, prev_k, value) -> bool:
    if prev_d is None or prev_k2 is None:
        return False
    prev_d[prev_k2] = {prev_k: value}
    return True


def deep_set(d, keys, value):
    """按点分隔字符串或键序列原地写入嵌套字典，并创建或替换非字典中间层。"""
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
                if exist and prev_k in d:
                    prev_d = d
                    d = d[prev_k]
                else:
                    exist = False
                    new = {}
                    d[prev_k] = new
                    d = new
            except TypeError:
                exist = False
                d = {}
                if not _replace_parent_with_dict(prev_d, prev_k2, prev_k, d):
                    return

            prev_k2 = prev_k
            prev_k = k
    except TypeError:
        return

    try:
        d[prev_k] = value
    except TypeError:
        _replace_parent_with_dict(prev_d, prev_k2, prev_k, value)
        return
    else:
        return


def deep_default(d, keys, value):
    """仅在末键缺失时写入默认值，并创建或替换非字典中间层。"""
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
                if exist and prev_k in d:
                    prev_d = d
                    d = d[prev_k]
                else:
                    exist = False
                    new = {}
                    d[prev_k] = new
                    d = new
            except TypeError:
                exist = False
                d = {}
                if not _replace_parent_with_dict(prev_d, prev_k2, prev_k, d):
                    return

            prev_k2 = prev_k
            prev_k = k
    except TypeError:
        return

    try:
        d.setdefault(prev_k, value)
    except AttributeError:
        _replace_parent_with_dict(prev_d, prev_k2, prev_k, value)
        return
    else:
        return


def deep_pop(d, keys, default=None):
    """从嵌套字典或列表弹出路径末项；路径无效时返回 default。"""
    if type(keys) is str:
        keys = keys.split(".")

    try:
        for k in keys[:-1]:
            d = d[k]
        # 不传 pop 默认值，才能同时支持列表索引。
        return d.pop(keys[-1])
    except KeyError:
        return default
    except TypeError:
        return default
    except IndexError:
        return default
    except AttributeError:
        return default


def deep_iter_depth1(data):
    """产出一层字典的 (key, value)；非映射输入不产出内容。"""
    try:
        yield from data.items()
    except AttributeError:
        return
    else:
        return


def deep_iter_depth2(data):
    """产出二层字典的 (key1, key2, value)；非映射输入不产出内容。"""
    try:
        for k1, v1 in data.items():
            if type(v1) is dict:
                for k2, v2 in v1.items():
                    yield k1, k2, v2
    except AttributeError:
        return


def deep_iter(data, min_depth=None, depth=3):
    """广度遍历嵌套字典，产出 min_depth 到 depth 的 (键路径, 值)。

    仅深入 dict；深度范围不满足 `1 <= min_depth <= depth` 时抛出 ValueError。
    """
    if min_depth is None:
        min_depth = depth
    _validate_depth_range(min_depth, depth)

    try:
        queue = deque([([], data.items())])
    except AttributeError:
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
