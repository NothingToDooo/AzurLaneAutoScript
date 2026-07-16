import json
import random
import string
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, NotRequired, Protocol, TypedDict, cast

import yaml
from yaml.representer import SafeRepresenter

from module.base.atomic import atomic_read_bytes, atomic_read_text, atomic_write
from module.config.json_codec import (
    DuplicateJsonFieldError,
    NonFiniteJsonNumberError,
    StrictJsonDecodeError,
    decode_json,
)
from module.logger import logger

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping, Sequence

    from yaml.nodes import ScalarNode

    from module.config.deep import MutableDeepData, MutableDeepValue

type FilePath = str | Path
type TimeScalar = int | float
type TimeInput = TimeScalar | str | tuple[TimeScalar, TimeScalar]
type InputType = Literal["checkbox", "select", "textarea", "input"]


class ScalarRepresenter(Protocol):
    def represent_scalar(self, tag: str, value: str, style: str | None = None) -> ScalarNode: ...


class ArgumentDefinition(TypedDict):
    value: MutableDeepValue
    option: NotRequired[list[MutableDeepValue]]


LANGUAGES = ["zh-CN"]
DEFAULT_TIME = datetime(2020, 1, 1, 0, 0)


def str_presenter(dumper: ScalarRepresenter, data: str) -> ScalarNode:
    if len(data.splitlines()) > 1:
        return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")
    return dumper.represent_scalar("tag:yaml.org,2002:str", data)


yaml.add_representer(str, str_presenter)
SafeRepresenter.add_representer(str, str_presenter)


def filepath_args(filename: str = "args") -> str:
    return f"./module/config/argument/{filename}.json"


def filepath_argument(filename: str) -> str:
    return f"./module/config/argument/{filename}.yaml"


def filepath_i18n(lang: str) -> str:
    return (Path("./module/config/i18n") / f"{lang}.json").as_posix()


def filepath_config(filename: str) -> str:
    return (Path("./config") / f"{filename}.json").as_posix()


def filepath_code() -> str:
    return "./module/config/config_generated.py"


def read_file(file: FilePath) -> MutableDeepData:
    """读取 YAML 或 JSON；文件不存在、为空或扩展名不支持时返回空字典。"""
    file = Path(file)
    logger.debug(f"read: {file}")
    if file.suffix == ".json":
        content = atomic_read_bytes(file)
        if not content:
            return {}
        try:
            decoded = decode_json(content)
        except DuplicateJsonFieldError as error:
            message = f"duplicate JSON field: {error.field}"
            raise ValueError(message) from error
        except NonFiniteJsonNumberError as error:
            message = f"JSON contains a non-finite number: {error.constant}"
            raise ValueError(message) from error
        except StrictJsonDecodeError as error:
            raise ValueError(str(error)) from error
        return cast("MutableDeepData", decoded)
    if file.suffix == ".yaml":
        content = atomic_read_text(file)
        data = list(yaml.safe_load_all(content))
        if len(data) == 1:
            data = data[0]
        if not data:
            data = {}
        return cast("MutableDeepData", data)
    logger.warning(f"Unsupported config file extension: {file}")
    return {}


def _encode_json_value(value: object) -> str:
    if isinstance(value, datetime):
        return str(value)
    message = f"unsupported JSON value type: {type(value).__name__}"
    raise TypeError(message)


def write_file(file: FilePath, data: MutableDeepData | list[MutableDeepData]) -> None:
    """原子写入 YAML 或 JSON；不支持的扩展名只记录警告。"""
    file = Path(file)
    logger.debug(f"write: {file}")
    if file.suffix == ".json":
        content = json.dumps(
            data,
            allow_nan=False,
            indent=2,
            ensure_ascii=False,
            sort_keys=False,
            default=_encode_json_value,
        )
        atomic_write(file, content)
    elif file.suffix == ".yaml":
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


def iter_folder(folder: FilePath, *, is_dir: bool = False, ext: str | None = None) -> Iterable[str]:
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


def data_to_type(data: ArgumentDefinition, *, arg: str) -> InputType:
    """按值类型映射 UI 控件：bool→checkbox、有选项→select、Filter→textarea，其余为 input。"""
    if isinstance(data["value"], bool):
        return "checkbox"
    if data.get("option"):
        return "select"
    if "Filter" in arg:
        return "textarea"
    return "input"


def data_to_path(data: Mapping[str, str]) -> str:
    """返回 `<func>.<group>.<arg>` 路径。"""
    return ".".join([data.get(attr, "") for attr in ["func", "group", "arg"]])


def path_to_arg(path: str) -> str:
    return path.replace(".", "_")


def dict_to_kv(dictionary: Mapping[str, MutableDeepValue], *, allow_none: bool = True) -> str:
    """把字典格式化为日志键值。"""
    return ", ".join([f"{key}={value!r}" for key, value in dictionary.items() if allow_none or value is not None])


def server_time_offset() -> timedelta:
    """个人国区分支默认本机时间就是服务器时间。"""
    return timedelta()


def random_normal_distribution_int(a: TimeScalar, b: TimeScalar, n: int = 3) -> int:
    """不依赖 NumPy，取 n 个闭区间 [a, b] 内均匀随机整数的均值模拟正态分布。"""
    a = round(a)
    b = round(b)
    if a < b:
        output = sum(random.randint(a, b) for _ in range(n)) / n
        return round(output)
    return b


def ensure_time(second: TimeInput, n: int = 3, precision: int = 3) -> TimeScalar:
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


def get_os_next_reset() -> datetime:
    diff = server_time_offset()
    server_now = datetime.now() - diff
    server_reset = (server_now.replace(day=1) + timedelta(days=32)).replace(
        day=1, hour=0, minute=0, second=0, microsecond=0
    )
    return server_reset + diff


def get_os_reset_remain() -> int:
    next_reset = get_os_next_reset()
    now = datetime.now()
    logger.attr("OpsiNextReset", next_reset)

    remain = int((next_reset - now).total_seconds() // 86400)
    logger.attr("ResetRemain", remain)
    return remain


def get_server_next_update(daily_trigger: str | Sequence[str]) -> datetime:
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


def get_server_last_update(daily_trigger: str | Sequence[str]) -> datetime:
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


def nearest_future(future: Sequence[datetime | str], interval: int = 120) -> datetime:
    """返回最早未来时间；相邻时间差小于 interval 秒时合并到较晚者。"""
    future = [datetime.fromisoformat(f) if isinstance(f, str) else f for f in future]
    future = sorted(future)
    next_run = future[0]
    for finish in future:
        if finish - next_run < timedelta(seconds=interval):
            next_run = finish

    return next_run


def get_nearest_weekday_date(target: int) -> datetime:
    """返回下一个 target 星期的零点；target 为 0～6，当天也顺延到下一周。"""
    diff = server_time_offset()
    server_now = datetime.now() - diff

    days_ahead = target - server_now.weekday()
    if days_ahead <= 0:
        days_ahead += 7
    server_reset = (server_now + timedelta(days=days_ahead)).replace(hour=0, minute=0, second=0, microsecond=0)

    return server_reset + diff


def get_server_weekday() -> int:
    diff = server_time_offset()
    server_now = datetime.now() - diff
    return server_now.weekday()


def get_server_monthday() -> int:
    diff = server_time_offset()
    server_now = datetime.now() - diff
    return server_now.day


def random_id(length: int = 32) -> str:
    return "".join(random.sample(string.ascii_lowercase + string.digits, length))


def to_list(text: str, length: int = 1) -> list[int]:
    """把逗号分隔整数转为列表；单个整数会重复到 length，例如 `3`→`[3, 3]`。"""
    if text.isdigit():
        return [int(text)] * length
    return [int(letter.strip()) for letter in text.split(",")]


def type_to_str(typ: type[MutableDeepValue] | MutableDeepValue) -> str:
    """把类型或对象转为不含尖括号的类型名，避免被解析为 HTML 标签。"""
    if not isinstance(typ, type):
        typ = type(typ).__name__
    return str(typ)


if __name__ == "__main__":
    get_os_reset_remain()
