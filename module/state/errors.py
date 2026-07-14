class StateStoreError(RuntimeError):
    """状态库操作失败。"""


class SchemaVersionError(StateStoreError):
    """状态库 schema 与当前代码不一致。"""


class RevisionConflictError(StateStoreError):
    """settings 的乐观锁版本不匹配。"""

    def __init__(self, *, expected_revision: int, actual_revision: int | None) -> None:
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision
        message = f"settings revision conflict: expected {expected_revision}, actual {actual_revision}"
        super().__init__(message)


class RunStateError(StateStoreError):
    """run 不存在或不允许当前状态转换。"""


class OutboxStateError(StateStoreError):
    """outbox 消息不存在或不允许当前状态转换。"""


class InterruptedRunError(RuntimeError):
    """进程退出前未能提交终态的 run。"""


class CorruptStateError(StateStoreError):
    """数据库内容违反持久化契约。"""
