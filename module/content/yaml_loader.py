from collections.abc import Mapping
from typing import TYPE_CHECKING, cast

import yaml
from yaml.resolver import BaseResolver

from module.content.errors import ContentValidationError

if TYPE_CHECKING:
    from pathlib import Path


class _StrictLoader(yaml.SafeLoader):
    pass


def _construct_unique_mapping(
    loader: _StrictLoader,
    node: yaml.MappingNode,
    *,
    deep: object = False,
) -> dict[object, object]:
    mapping: dict[object, object] = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=bool(deep))
        if key in mapping:
            message = f"duplicate YAML key: {key}"
            raise ContentValidationError(message)
        mapping[key] = loader.construct_object(value_node, deep=bool(deep))
    return mapping


_StrictLoader.add_constructor(BaseResolver.DEFAULT_MAPPING_TAG, _construct_unique_mapping)


def load_strict_yaml_mapping(path: Path) -> Mapping[object, object]:
    """读取只允许唯一 mapping key 的 YAML 根节点。"""

    try:
        loader = _StrictLoader(path.read_text(encoding="utf-8"))
        try:
            raw = loader.get_single_data()
        finally:
            loader.dispose()
    except ContentValidationError:
        raise
    except (OSError, yaml.YAMLError) as error:
        message = f"{path}:$: {error}"
        raise ContentValidationError(message) from error
    if not isinstance(raw, Mapping):
        message = f"{path}:$: must be a mapping"
        raise ContentValidationError(message)
    return cast("Mapping[object, object]", raw)
