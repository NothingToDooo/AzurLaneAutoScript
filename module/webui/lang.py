from module.config.deep import deep_iter
from module.config.utils import filepath_i18n, read_file
from module.logger import logger

LANG = "zh-CN"
dic_lang: dict[str, str] = {}


def t(s, *args, **kwargs):
    """
    Get translation.
    other args, kwargs pass to .format()
    """
    return _t(s).format(*args, **kwargs)


def _t(s):
    """
    Get translation.
    """
    try:
        return dic_lang[s]
    except KeyError:
        logger.warning(f"Language key ({s}) not found")
        return s


def reload():
    dic_lang.clear()
    for path, value in deep_iter(read_file(filepath_i18n(LANG)), depth=3):
        dic_lang[".".join(path)] = value
