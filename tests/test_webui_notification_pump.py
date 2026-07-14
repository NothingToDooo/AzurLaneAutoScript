import threading
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Self

import module.notify.pump as pump_module
import module.webui.app as webui_app
from module.notify import NotificationSpoolPump

if TYPE_CHECKING:
    import pytest


@dataclass(slots=True)
class _Session:
    flush_calls: list[tuple[str | None, int, int]] = field(default_factory=list)
    close_calls: int = 0
    close_error: Exception | None = None
    flush_error: Exception | None = None
    flushed: threading.Event | None = None

    def flush(
        self,
        *,
        instance_name: str | None = None,
        max_intents: int = 32,
        max_deliveries: int = 4,
    ) -> object:
        self.flush_calls.append((instance_name, max_intents, max_deliveries))
        if self.flushed is not None:
            self.flushed.set()
        if self.flush_error is not None:
            raise self.flush_error
        return object()

    def close(self) -> None:
        self.close_calls += 1
        if self.close_error is not None:
            raise self.close_error

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *args: object) -> None:
        del args
        self.close()


def test_run_once_uses_a_bounded_fresh_session_and_closes_it() -> None:
    sessions: list[_Session] = []

    def build() -> _Session:
        session = _Session()
        sessions.append(session)
        return session

    pump = NotificationSpoolPump(build, max_intents=7, max_deliveries=2)

    pump.run_once()
    pump.run_once()

    assert len(sessions) == 2
    assert sessions[0] is not sessions[1]
    assert [session.flush_calls for session in sessions] == [[(None, 7, 2)], [(None, 7, 2)]]
    assert [session.close_calls for session in sessions] == [1, 1]


def test_one_pump_failure_is_logged_and_the_next_tick_still_runs(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = RuntimeError("SMTP connection failed")
    logged: list[Exception] = []
    monkeypatch.setattr(pump_module.logger, "exception", logged.append)
    sessions = [_Session(flush_error=failure), _Session()]
    pump = NotificationSpoolPump(lambda: sessions.pop(0))

    pump.run_once()
    pump.run_once()

    assert sessions == []
    assert logged == [failure]


def test_session_close_failure_is_logged_and_contained(monkeypatch: pytest.MonkeyPatch) -> None:
    failure = OSError("notification spool close failed")
    logged: list[Exception] = []
    monkeypatch.setattr(pump_module.logger, "exception", logged.append)
    pump = NotificationSpoolPump(lambda: _Session(close_error=failure))

    pump.run_once()

    assert logged == [failure]


def test_background_pump_runs_without_live_instance_processes_and_stops() -> None:
    flushed = threading.Event()
    sessions: list[_Session] = []

    def build() -> _Session:
        session = _Session(flushed=flushed)
        sessions.append(session)
        return session

    pump = NotificationSpoolPump(build, interval_seconds=60)

    pump.start()
    assert flushed.wait(timeout=2)
    pump.stop()

    assert not pump.running
    assert len(sessions) == 1
    assert sessions[0].close_calls == 1


def test_start_during_timed_out_stop_restarts_after_the_old_worker_exits() -> None:
    first_started = threading.Event()
    release_first = threading.Event()
    replacement_flushed = threading.Event()
    sessions: list[_Session] = []

    class _BlockingSession(_Session):
        def flush(
            self,
            *,
            instance_name: str | None = None,
            max_intents: int = 32,
            max_deliveries: int = 4,
        ) -> object:
            self.flush_calls.append((instance_name, max_intents, max_deliveries))
            first_started.set()
            assert release_first.wait(timeout=2)
            return object()

    def build() -> _Session:
        session = _BlockingSession() if not sessions else _Session(flushed=replacement_flushed)
        sessions.append(session)
        return session

    pump = NotificationSpoolPump(build, interval_seconds=60, shutdown_timeout_seconds=0.01)
    pump.start()
    assert first_started.wait(timeout=2)

    pump.stop()
    assert pump.running
    pump.start()
    release_first.set()

    assert replacement_flushed.wait(timeout=2)
    pump.stop()
    assert not pump.running
    assert len(sessions) == 2


def test_webui_lifecycle_starts_and_stops_the_global_notification_pump(monkeypatch: pytest.MonkeyPatch) -> None:
    events: list[str] = []

    class _Pump:
        @staticmethod
        def start() -> None:
            events.append("pump-start")

        @staticmethod
        def stop() -> None:
            events.append("pump-stop")

    monkeypatch.setattr(webui_app, "_notification_spool_pump", _Pump())
    monkeypatch.setattr(webui_app.State, "init", lambda: events.append("state-init"))
    monkeypatch.setattr(webui_app.State, "clearup", lambda: events.append("state-clear"))
    monkeypatch.setattr(webui_app.lang, "reload", lambda: events.append("lang-reload"))
    monkeypatch.setattr(webui_app.task_handler, "start", lambda: events.append("tasks-start"))
    monkeypatch.setattr(webui_app.task_handler, "stop", lambda: events.append("tasks-stop"))
    monkeypatch.setattr(webui_app.ProcessManager, "stop_all", lambda: events.append("processes-stop"))

    webui_app.startup()
    webui_app.clearup()

    assert events == [
        "state-init",
        "lang-reload",
        "pump-start",
        "tasks-start",
        "processes-stop",
        "pump-stop",
        "state-clear",
        "tasks-stop",
    ]
