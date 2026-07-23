class RuntimeCompositionError(RuntimeError):
    """运行时组合边界无法构造一致的 Task。"""


class SettingsDocumentError(RuntimeCompositionError):
    """持久化 settings 不符合当前严格 schema。"""


class TaskStateDocumentError(RuntimeCompositionError):
    """持久化 task state 不符合当前严格 schema。"""


class FactoryCoverageError(RuntimeCompositionError):
    """Task factory 与 catalog 不具备精确的一一覆盖关系。"""


class UnknownTaskError(RuntimeCompositionError):
    """请求的 TaskId 不在当前 catalog。"""


class InvalidTaskFactoryError(RuntimeCompositionError):
    """Task factory 没有返回有效的 Task。"""


class RecoveryLimitExceededError(RuntimeError):
    """同一调度任务连续耗尽可恢复失败预算。"""

    def __init__(self, task_id: str, attempts: int, last_error: Exception) -> None:
        self.task_id = task_id
        self.attempts = attempts
        self.last_error = last_error
        super().__init__(f"Task {task_id!r} failed {attempts} consecutive times; recovery limit exhausted")
        self.__cause__ = last_error
