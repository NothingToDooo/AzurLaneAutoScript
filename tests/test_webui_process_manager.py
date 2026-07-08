from types import SimpleNamespace

import module.webui.process_manager as process_manager_module
from module.webui.process_manager import ProcessManager


def _patch_process_boundary(monkeypatch, calls: list[tuple]):
    class _Logger:
        def critical(self, message):
            calls.append(("critical", message))

        def info(self, message):
            calls.append(("info", message))

        def exception(self, error):
            calls.append(("exception", str(error)))

    monkeypatch.setattr(process_manager_module, "set_file_logger", lambda name: calls.append(("file_logger", name)))
    monkeypatch.setattr(process_manager_module, "set_func_logger", lambda func: calls.append(("func_logger", func)))
    monkeypatch.setattr(process_manager_module, "remove_fake_pil_module", lambda: calls.append(("remove_fake_pil",)))
    monkeypatch.setattr(process_manager_module, "logger", _Logger())


def test_run_process_runs_alas_loop(monkeypatch) -> None:
    calls = []
    _patch_process_boundary(monkeypatch, calls)

    class _Alas:
        stop_event = None

        def __init__(self, config_name):
            calls.append(("init", config_name))

        def loop(self):
            calls.append(("loop",))

    monkeypatch.setattr(process_manager_module, "AzurLaneAutoScript", _Alas)

    ProcessManager.run_process("alas", "alas", SimpleNamespace(put=lambda item: item))

    assert ("init", "alas") in calls
    assert ("loop",) in calls
    assert ("info", "[alas] exited. Reason: Finish\n") in calls


def test_run_process_runs_builtin_task(monkeypatch) -> None:
    calls = []
    _patch_process_boundary(monkeypatch, calls)

    class _Alas:
        def __init__(self, config_name):
            calls.append(("init", config_name))

        def run(self, task, skip_first_screenshot=False):
            calls.append(("run", task, skip_first_screenshot))

    monkeypatch.setattr(process_manager_module, "AzurLaneAutoScript", _Alas)

    ProcessManager.run_process("alas", "Benchmark", SimpleNamespace(put=lambda item: item))

    assert ("run", "benchmark", True) in calls


def test_run_process_rejects_unknown_func(monkeypatch) -> None:
    calls = []
    _patch_process_boundary(monkeypatch, calls)

    ProcessManager.run_process("alas", "MissingMod", SimpleNamespace(put=lambda item: item))

    assert ("critical", "No function matched: MissingMod") in calls
