import re

_ACRONYM_BOUNDARY = re.compile(r"(.)([A-Z][a-z]+)")
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")


def camel_to_snake(name: str) -> str:
    name = _ACRONYM_BOUNDARY.sub(r"\1_\2", name)
    return _CAMEL_BOUNDARY.sub(r"\1_\2", name).lower()
