import copy
from collections.abc import Mapping
from typing import TYPE_CHECKING, cast, override

from module.bootstrap.configuration_compiler import CurrentConfigurationSchema
from module.config.config import AzurLaneConfig
from module.config.deep import deep_set
from module.config.utils import filepath_config, read_file

if TYPE_CHECKING:
    from module.config.deep import MutableDeepData, MutableDeepValue


def _merge_document(target: MutableDeepData, overrides: Mapping[str, object]) -> None:
    for key, value in overrides.items():
        existing = target.get(key)
        if isinstance(existing, dict) and isinstance(value, Mapping):
            _merge_document(existing, cast("Mapping[str, object]", value))
            continue
        target[key] = cast("MutableDeepValue", copy.deepcopy(value))


class InMemoryAzurLaneConfig(AzurLaneConfig):
    """只供单元测试使用，以内存文档覆盖生产配置的 load/save 边界。"""

    def __init__(
        self,
        config_name: str,
        document: Mapping[str, object],
        task: str | None = None,
    ) -> None:
        if not isinstance(document, Mapping):
            message = "configuration document must be a mapping"
            raise TypeError(message)
        if any(not isinstance(key, str) for key in document):
            message = "configuration document must use string field names"
            raise TypeError(message)
        raw = read_file(filepath_config("template"))
        _merge_document(raw, document)
        vars(self)["_memory_document"] = CurrentConfigurationSchema().parse(raw)
        super().__init__(config_name, task=task)

    @override
    def load(self) -> None:
        self.data = copy.deepcopy(self._memory_document)
        for path, value in self.modified.items():
            deep_set(self.data, keys=path, value=value)

    @override
    def save(self) -> bool:
        if not self.modified:
            return False
        for path, value in self.modified.items():
            deep_set(self.data, keys=path, value=value)
        self.modified.clear()
        self._memory_document = copy.deepcopy(self.data)
        return True


def in_memory_config(
    config_name: str,
    document: Mapping[str, object],
    task: str | None = None,
) -> AzurLaneConfig:
    return InMemoryAzurLaneConfig(config_name, document, task=task)
