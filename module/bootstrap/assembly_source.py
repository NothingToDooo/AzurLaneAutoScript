from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, cast

from module.bootstrap.task_factories import GameTaskDependencies
from module.config.json_codec import (
    DuplicateJsonFieldError,
    NonFiniteJsonNumberError,
    StrictJsonDecodeError,
    decode_json,
)
from module.diagnostics import ScreenshotHistory

if TYPE_CHECKING:
    from module.bootstrap.configuration_compiler import ConfigurationDocument


class ConfigurationLoadError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GameRuntimeBundle:
    tasks: GameTaskDependencies
    screenshots: ScreenshotHistory
    content_revision: str

    def __post_init__(self) -> None:
        if not isinstance(self.tasks, GameTaskDependencies):
            message = "tasks must be GameTaskDependencies"
            raise TypeError(message)
        if not isinstance(self.screenshots, ScreenshotHistory):
            message = "screenshots must be a ScreenshotHistory"
            raise TypeError(message)
        if not isinstance(self.content_revision, str):
            message = "content_revision must be a string"
            raise TypeError(message)
        if not self.content_revision or self.content_revision != self.content_revision.strip():
            message = "content_revision must be trimmed and non-empty"
            raise ValueError(message)


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
