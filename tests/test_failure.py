import pytest

from module.base.failure import cleanup_scope, preserve_cleanup_failure, raise_cleanup_errors


class _CleanupSignal(BaseException):
    """测试 BaseException 也不会截断其后的清理步骤。"""


def test_raise_cleanup_errors_returns_when_cleanup_succeeds() -> None:
    assert raise_cleanup_errors((), message="unused") is None


def test_raise_cleanup_errors_preserves_one_error_identity() -> None:
    error = RuntimeError("cleanup failed")

    with pytest.raises(RuntimeError) as raised:
        raise_cleanup_errors((error,), message="unused")

    assert raised.value is error


def test_raise_cleanup_errors_preserves_all_errors_and_group_kind() -> None:
    first = RuntimeError("first cleanup failed")
    second = OSError("second cleanup failed")

    with pytest.raises(ExceptionGroup) as raised:
        raise_cleanup_errors((first, second), message="cleanup failed")

    assert type(raised.value) is ExceptionGroup
    assert raised.value.exceptions == (first, second)

    signal = _CleanupSignal("cleanup interrupted")
    with pytest.raises(BaseExceptionGroup) as base_raised:
        raise_cleanup_errors((first, signal), message="cleanup failed")

    assert type(base_raised.value) is BaseExceptionGroup
    assert base_raised.value.exceptions == (first, signal)


def test_preserve_cleanup_failure_keeps_primary_and_cleanup_errors() -> None:
    primary = ValueError("operation failed")
    cleanup_error = OSError("cleanup failed")

    def fail_cleanup() -> None:
        raise cleanup_error

    with pytest.raises(ExceptionGroup) as raised:
        preserve_cleanup_failure(primary, fail_cleanup, message="operation and cleanup failed")

    assert raised.value.exceptions == (primary, cleanup_error)


def test_cleanup_scope_runs_cleanup_on_success_and_preserves_double_failure() -> None:
    calls: list[str] = []

    with cleanup_scope(lambda: calls.append("cleanup"), message="unused"):
        calls.append("body")

    assert calls == ["body", "cleanup"]

    primary = RuntimeError("body failed")
    cleanup_error = OSError("cleanup failed")

    def fail_cleanup() -> None:
        raise cleanup_error

    with (
        pytest.raises(ExceptionGroup) as raised,
        cleanup_scope(
            fail_cleanup,
            message="body and cleanup failed",
        ),
    ):
        raise primary

    assert raised.value.exceptions == (primary, cleanup_error)
