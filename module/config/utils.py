import json
import random
import string
from datetime import datetime, timedelta
from pathlib import Path

import yaml
from yaml.representer import SafeRepresenter

from module.base.atomic import atomic_read_bytes, atomic_read_text, atomic_write
from module.logger import logger

LANGUAGES = ["zh-CN"]
DEFAULT_TIME = datetime(2020, 1, 1, 0, 0)


def str_presenter(dumper, data):
    if len(data.splitlines()) > 1:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, str_presenter)
SafeRepresenter.add_representer(str, str_presenter)


def filepath_args(filename="args"):
    return f"./module/config/argument/{filename}.json"


def filepath_argument(filename):
    return f"./module/config/argument/{filename}.yaml"


def filepath_i18n(lang):
    return (Path("./module/config/i18n") / f"{lang}.json").as_posix()


def filepath_config(filename):
    return (Path("./config") / f"{filename}.json").as_posix()


def filepath_code():
    return "./module/config/config_generated.py"


def read_file(file):
    """读取 YAML 或 JSON；文件不存在、为空或扩展名不支持时返回空字典。"""
    logger.debug(f"read: {file}")
    if file.endswith(".json"):
        content = atomic_read_bytes(file)
        if not content:
            return {}
        return json.loads(content)
    if file.endswith(".yaml"):
        content = atomic_read_text(file)
        data = list(yaml.safe_load_all(content))
        if len(data) == 1:
            data = data[0]
        if not data:
            data = {}
        return data
    logger.warning(f"Unsupported config file extension: {file}")
    return {}


def write_file(file, data):
    """原子写入 YAML 或 JSON；不支持的扩展名只记录警告。"""
    logger.debug(f"write: {file}")
    if file.endswith(".json"):
        content = json.dumps(data, indent=2, ensure_ascii=False, sort_keys=False, default=str)
        atomic_write(file, content)
    elif file.endswith(".yaml"):
        if isinstance(data, list):
            content = yaml.safe_dump_all(
                data, default_flow_style=False, encoding="utf-8", allow_unicode=True, sort_keys=False
            )
        else:
            content = yaml.safe_dump(
                data, default_flow_style=False, encoding="utf-8", allow_unicode=True, sort_keys=False
            )
        atomic_write(file, content)
    else:
        logger.warning(f"Unsupported config file extension: {file}")


def iter_folder(folder, is_dir=False, ext=None):
    """产出目录项路径；is_dir 仅取目录，ext 按 `.yaml` 形式筛选文件。"""
    for sub in Path(folder).iterdir():
        if is_dir:
            if sub.is_dir():
                yield sub.as_posix()
        elif ext is not None:
            if not sub.is_dir() and sub.suffix == ext:
                yield sub.as_posix()
        else:
            yield sub.as_posix()


def alas_template():
    return ["template"] if Path("./config/template.json").exists() else []


def alas_instance():
    """列出 template 以外的顶层 JSON 实例；没有实例时回退为 `alas`。"""
    out = []
    for path in Path("./config").iterdir():
        name = path.stem
        extension = path.suffix
        mod_name = Path(name).suffix
        mod_name = mod_name[1:]
        if name != "template" and extension == ".json" and mod_name == "":
            out.append(name)

    if not out:
        out = ["alas"]

    return out


def _parse_numeric_value(value: str):
    parser = float if "." in value else int
    try:
        return parser(value)
    except ValueError:
        return value


def _parse_datetime_value(value: str):
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return value


def _parse_string_value(value: str):
    if value == "":
        return None
    if value in {"true", "True"}:
        return True
    if value in {"false", "False"}:
        return False

    parsed = _parse_numeric_value(value)
    if parsed != value:
        return parsed

    return _parse_datetime_value(value)


def parse_value(value, data):
    """把配置字符串转换成 bool、数字或 datetime；非法选项回退到定义的默认值。"""
    if "option" in data and value not in data["option"]:
        return data["value"]
    if not isinstance(value, str):
        return value
    return _parse_string_value(value)


def data_to_type(data, **kwargs):
    """按值类型映射 UI 控件：bool→checkbox、有选项→select、Filter→textarea，其余为 input。"""
    kwargs.update(data)
    if isinstance(kwargs["value"], bool):
        return "checkbox"
    if kwargs.get("option"):
        return "select"
    if "Filter" in kwargs["arg"]:
        return "textarea"
    return "input"


def data_to_path(data):
    """返回 `<func>.<group>.<arg>` 路径。"""
    return ".".join([data.get(attr, "") for attr in ["func", "group", "arg"]])


def path_to_arg(path):
    return path.replace(".", "_")


def dict_to_kv(dictionary, allow_none=True):
    """把字典格式化为 `path='Scheduler.ServerUpdate', value=True` 形式。"""
    return ", ".join([f"{k}={v!r}" for k, v in dictionary.items() if allow_none or v is not None])


def server_time_offset() -> timedelta:
    """个人国区分支默认本机时间就是服务器时间。"""
    return timedelta()


def random_normal_distribution_int(a, b, n=3):
    """不依赖 NumPy，取 n 个闭区间 [a, b] 内均匀随机整数的均值模拟正态分布。"""
    if a < b:
        output = sum(random.randint(a, b) for _ in range(n)) / n
        return round(output)
    return b


def ensure_time(second, n=3, precision=3):
    """把秒数或 `10,30`、`10-30`、(10, 30) 归一化为秒；区间按近似正态分布取值。"""
    if isinstance(second, tuple):
        multiply = 10**precision
        return random_normal_distribution_int(second[0] * multiply, second[1] * multiply, n) / multiply
    if isinstance(second, str):
        if "," in second:
            lower, upper = second.replace(" ", "").split(",")
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        if "-" in second:
            lower, upper = second.replace(" ", "").split("-")
            lower, upper = int(lower), int(upper)
            return ensure_time((lower, upper), n=n, precision=precision)
        return int(second)
    return second


def get_os_next_reset():
    diff = server_time_offset()
    server_now = datetime.now() - diff
    server_reset = (server_now.replace(day=1) + timedelta(days=32)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    return server_reset + diff


def get_os_reset_remain():
    next_reset = get_os_next_reset()
    now = datetime.now()
    logger.attr("OpsiNextReset", next_reset)

    remain = int((next_reset - now).total_seconds() // 86400)
    logger.attr("ResetRemain", remain)
    return remain


def get_server_next_update(daily_trigger):
    """接受 `HH:MM` 列表或逗号分隔字符串，返回最近的下一次服务器触发时间。"""
    if isinstance(daily_trigger, str):
        daily_trigger = daily_trigger.replace(" ", "").split(",")
    if not daily_trigger:
        msg = "daily_trigger must not be empty"
        raise ValueError(msg)

    diff = server_time_offset()
    local_now = datetime.now()
    trigger = []
    for t in daily_trigger:
        h, m = [int(x) for x in t.split(":")]
        future = local_now.replace(hour=h, minute=m, second=0, microsecond=0) + diff
        s = (future - local_now).total_seconds() % 86400
        future = local_now + timedelta(seconds=s)
        trigger.append(future)
    return min(trigger)


def get_server_last_update(daily_trigger):
    """接受 `HH:MM` 列表或逗号分隔字符串，返回最近的上一次服务器触发时间。"""
    if isinstance(daily_trigger, str):
        daily_trigger = daily_trigger.replace(" ", "").split(",")
    if not daily_trigger:
        msg = "daily_trigger must not be empty"
        raise ValueError(msg)

    diff = server_time_offset()
    local_now = datetime.now()
    trigger = []
    for t in daily_trigger:
        h, m = [int(x) for x in t.split(":")]
        future = local_now.replace(hour=h, minute=m, second=0, microsecond=0) + diff
        s = (future - local_now).total_seconds() % 86400 - 86400
        future = local_now + timedelta(seconds=s)
        trigger.append(future)
    return max(trigger)


def nearest_future(future, interval=120):
    """返回最早未来时间；相邻时间差小于 interval 秒时合并到较晚者。"""
    future = [datetime.fromisoformat(f) if isinstance(f, str) else f for f in future]
    future = sorted(future)
    next_run = future[0]
    for finish in future:
        if finish - next_run < timedelta(seconds=interval):
            next_run = finish

    return next_run


def get_nearest_weekday_date(target):
    """返回下一个 target 星期的零点；target 为 0～6，当天也顺延到下一周。"""
    diff = server_time_offset()
    server_now = datetime.now() - diff

    days_ahead = target - server_now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    server_reset = (server_now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)

    return server_reset + diff


def get_server_weekday():
    diff = server_time_offset()
    server_now = datetime.now() - diff
    return server_now.weekday()


def get_server_monthday():
    diff = server_time_offset()
    server_now = datetime.now() - diff
    return server_now.day


def random_id(length=32):
    return "".join(random.sample(string.ascii_lowercase + string.digits, length))


def to_list(text, length=1):
    """把逗号分隔整数转为列表；单个整数会重复到 length，例如 `3`→`[3, 3]`。"""
    if text.isdigit():
        return [int(text)] * length
    return [int(letter.strip()) for letter in text.split(",")]


def type_to_str(typ):
    """把类型或对象转为不含尖括号的类型名，避免被解析为 HTML 标签。"""
    if not isinstance(typ, type):
        typ = type(typ).__name__
    return str(typ)


if __name__ == "__main__":
    get_os_reset_remain()
