from datetime import UTC, datetime
from typing import TYPE_CHECKING

import pytest

from module.application import (
    AbortRequested,
    AbortToken,
    CancellationSource,
    ExecutionMode,
    RunMetadata,
    Succeeded,
    TaskContext,
    TaskId,
    TaskResult,
)
from module.maintenance import UncensoredPayload, UncensoredSettings, UncensoredTask

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path


class _Assets:
    def __init__(
        self,
        calls: list[str],
        payload: UncensoredPayload,
        *,
        after_build: Callable[[], None] | None = None,
    ) -> None:
        self._calls = calls
        self._payload = payload
        self._after_build = after_build

    def build(self, cancellation: CancellationSource) -> UncensoredPayload:
        cancellation.raise_if_requested()
        self._calls.append("build")
        if self._after_build is not None:
            self._after_build()
        return self._payload


class _Installer:
    def __init__(self, calls: list[str], *, error: RuntimeError | None = None) -> None:
        self._calls = calls
        self._error = error
        self.installed: tuple[UncensoredPayload, str] | None = None

    def install(
        self,
        payload: UncensoredPayload,
        package_name: str,
        cancellation: CancellationSource,
    ) -> None:
        cancellation.raise_if_requested()
        self._calls.append("install")
        self.installed = (payload, package_name)
        if self._error is not None:
            raise self._error


class _App:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def start(self, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        self._calls.append("start")

    def stop(self, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        self._calls.append("stop")


class _Login:
    def __init__(self, calls: list[str]) -> None:
        self._calls = calls

    def ensure_logged_in(self, cancellation: CancellationSource) -> None:
        cancellation.raise_if_requested()
        self._calls.append("login")


def _context(abort: AbortToken | None = None) -> TaskContext:
    return TaskContext(
        task_id=TaskId("azur_lane_uncensored"),
        started_at=datetime(2026, 7, 13, tzinfo=UTC),
        mode=ExecutionMode.DIRECT_COMMAND,
        metadata=RunMetadata(settings_revision=1, content_revision="content-1"),
        abort=AbortToken() if abort is None else abort,
    )


def _task(
    calls: list[str],
    payload: UncensoredPayload,
    *,
    assets: _Assets | None = None,
    installer: _Installer | None = None,
) -> tuple[UncensoredTask, _Installer]:
    selected_installer = _Installer(calls) if installer is None else installer
    return (
        UncensoredTask(
            _Assets(calls, payload) if assets is None else assets,
            selected_installer,
            _App(calls),
            _Login(calls),
            UncensoredSettings("com.bilibili.azurlane"),
        ),
        selected_installer,
    )


def test_uncensored_builds_pushes_and_restarts_the_current_game_package(tmp_path: Path) -> None:
    calls: list[str] = []
    payload = UncensoredPayload((tmp_path / "uncensored-files").resolve())
    task, installer = _task(calls, payload)

    result = task.run(_context())

    assert calls == ["build", "install", "stop", "start", "login"]
    assert installer.installed == (payload, "com.bilibili.azurlane")
    assert result == TaskResult(outcome=Succeeded())


def test_uncensored_abort_after_build_prevents_push_and_restart(tmp_path: Path) -> None:
    calls: list[str] = []
    abort = AbortToken()
    payload = UncensoredPayload((tmp_path / "uncensored-files").resolve())

    def request_abort() -> None:
        abort.request("manual stop")

    assets = _Assets(calls, payload, after_build=request_abort)
    task, _installer = _task(calls, payload, assets=assets)

    with pytest.raises(AbortRequested, match="manual stop"):
        task.run(_context(abort))

    assert calls == ["build"]


def test_uncensored_install_failure_prevents_app_restart(tmp_path: Path) -> None:
    calls: list[str] = []
    payload = UncensoredPayload((tmp_path / "uncensored-files").resolve())
    installer = _Installer(calls, error=RuntimeError("adb push failed"))
    task, _installer = _task(calls, payload, installer=installer)

    with pytest.raises(RuntimeError, match="adb push failed"):
        task.run(_context())

    assert calls == ["build", "install"]
