import re

_ACRONYM_BOUNDARY = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")


def camel_to_snake(name: str) -> str:
    """把任务名从 CamelCase 转成模块函数使用的 snake_case。"""
    name = _ACRONYM_BOUNDARY.sub(r"\1_\2", name)
    return _CAMEL_BOUNDARY.sub(r"\1_\2", name).lower()
