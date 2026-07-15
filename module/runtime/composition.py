from collections.abc import Iterable, Mapping

from module.runtime.errors import FactoryCoverageError
from module.runtime.factories import TaskFactory, TaskFactoryRegistry
from module.task_registry import TASK_CATALOG, TaskDefinition


def compose_task_factories(
    groups: Iterable[Mapping[str, TaskFactory]],
    *,
    content_revision: str,
    catalog: Mapping[str, TaskDefinition] = TASK_CATALOG,
) -> TaskFactoryRegistry:
    """合并互斥领域 factory group，并由 registry 强制验证 catalog 精确覆盖。"""

    if isinstance(groups, Mapping | str | bytes):
        message = "groups must be an iterable of factory mappings"
        raise TypeError(message)
    merged: dict[str, TaskFactory] = {}
    for index, group in enumerate(groups):
        if not isinstance(group, Mapping):
            message = f"factory group {index} must be a mapping"
            raise TypeError(message)
        duplicate = sorted(set(merged) & set(group))
        if duplicate:
            message = f"duplicate task factories across groups: {duplicate}"
            raise FactoryCoverageError(message)
        merged.update(group)
    return TaskFactoryRegistry(
        catalog=catalog,
        factories=merged,
        content_revision=content_revision,
    )
