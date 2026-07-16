from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING, cast

from module.config.json_codec import (
    DuplicateJsonFieldError,
    NonFiniteJsonNumberError,
    StrictJsonDecodeError,
    decode_json,
)

if TYPE_CHECKING:
    from module.bootstrap.configuration_compiler import ConfigurationDocument


class ConfigurationLoadError(ValueError):
    pass


def parse_configuration_document(content: str, *, source: str = "configuration") -> ConfigurationDocument:
    """解析配置 JSON，并拒绝重复字段和非对象根节点。"""

    if not isinstance(content, str):
        message = "configuration content must be text"
        raise TypeError(message)
    if not isinstance(source, str) or not source.strip():
        message = "source must be a non-empty string"
        raise ValueError(message)
    try:
        value = decode_json(content)
    except DuplicateJsonFieldError as error:
        message = f"duplicate configuration field: {error.field}"
        raise ConfigurationLoadError(message) from error
    except NonFiniteJsonNumberError as error:
        message = f"configuration contains a non-finite JSON number: {error.constant}"
        raise ConfigurationLoadError(message) from error
    except StrictJsonDecodeError as error:
        message = f"failed to load configuration {source}: {error}"
        raise ConfigurationLoadError(message) from error
    if not isinstance(value, Mapping):
        message = f"configuration {source} must contain a JSON object"
        raise ConfigurationLoadError(message)
    if any(not isinstance(key, str) for key in value):
        message = f"configuration {source} must use string field names"
        raise ConfigurationLoadError(message)
    return cast("ConfigurationDocument", value)


class JsonConfigurationDocumentSource:
    """读取唯一的 config/alas.json。"""

    __slots__ = ("_path",)

    def __init__(self, path: Path) -> None:
        if not isinstance(path, Path):
            message = "path must be a Path"
            raise TypeError(message)
        self._path = path

    def load(self) -> ConfigurationDocument:
        try:
            content = self._path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            message = f"failed to load configuration {self._path}: {error}"
            raise ConfigurationLoadError(message) from error
        return parse_configuration_document(content, source=str(self._path))
