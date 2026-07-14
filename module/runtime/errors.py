class RuntimeCompositionError(RuntimeError):
    """运行时组合边界无法构造一致的 Task。"""


class RuntimeRestartRequiredError(RuntimeError):
    """候选配置修改了进程组装期绑定字段，不能在当前 runtime 内发布。"""


class ConfigurationPublicationConflictError(RuntimeError):
    """配置控制面在有限重试内持续遭遇并发发布。"""


class ConfigurationDocumentError(RuntimeCompositionError):
    """完整运行配置的 settings 或 schedule 不满足当前严格 schema。"""


class SettingsDocumentError(RuntimeCompositionError):
    """持久化 settings 不符合当前严格 schema。"""


class TaskStateDocumentError(RuntimeCompositionError):
    """持久化 task state 不符合当前严格 schema。"""


class MissingSettingsError(RuntimeCompositionError):
    """实例尚未发布 settings snapshot。"""


class FactoryCoverageError(RuntimeCompositionError):
    """Task factory 与 catalog 不具备精确的一一覆盖关系。"""


class UnknownTaskError(RuntimeCompositionError):
    """请求的 TaskId 不在当前 catalog。"""


class ExecutionModeMismatchError(RuntimeCompositionError):
    """请求入口与 catalog 声明的 execution mode 不一致。"""


class InvalidTaskFactoryError(RuntimeCompositionError):
    """Task factory 没有返回有效的 Task。"""
