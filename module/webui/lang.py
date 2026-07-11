from module.config.deep import DeepValue, deep_iter
from module.config.utils import filepath_i18n, read_file
from module.logger import logger

LANG = "zh-CN"
dic_lang: dict[str, str] = {}


def t(s: str, *args: DeepValue, **kwargs: DeepValue) -> str:
    return _t(s).format(*args, **kwargs)


def _t(s: str) -> str:
    try:
        return dic_lang[s]
    except KeyError:
        logger.warning(f"Language key ({s}) not found")
        return s


def reload() -> None:
    dic_lang.clear()
    for path, value in deep_iter(read_file(filepath_i18n(LANG)), depth=3):
        if not isinstance(value, str):
            message = f"Language value at {'.'.join(path)} must be a string"
            raise TypeError(message)
        dic_lang[".".join(path)] = value
