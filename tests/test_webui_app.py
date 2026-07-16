import json
from copy import deepcopy
from pathlib import Path
from threading import Event, RLock, Thread
from typing import TYPE_CHECKING, cast

import pytest

import module.webui.app as webui_app
from module.bootstrap.configuration_compiler import ConfigurationCompileError, ConfigurationDocument
from module.config.utils import filepath_args, read_file
from module.webui.app import AlasGUI, import_personal_configuration

if TYPE_CHECKING:
    from collections.abc import Callable

    from module.webui.utils import WebIOTaskHandler


def _template() -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads(Path("config/template.json").read_text(encoding="utf-8")),
    )


def _record_validation(
    candidates: list[ConfigurationDocument],
) -> Callable[[ConfigurationDocument], None]:
    def validate(candidate: ConfigurationDocument) -> None:
        candidates.append(deepcopy(candidate))

    return validate


def test_config_listeners_are_bound_once_per_session(monkeypatch: pytest.MonkeyPatch) -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.ALAS_ARGS = {}
    gui._config_listeners_initialized = False  # noqa: SLF001 - 验证 session 监听初始化边界。
    bindings: list[tuple[str, object]] = []

    monkeypatch.setattr(
        webui_app,
        "get_alas_config_listen_path",
        lambda _args: iter([["Task", "Group", "Field"]]),
    )
    monkeypatch.setattr(
        webui_app,
        "pin_on_change",
        lambda *, name, onchange: bindings.append((name, onchange)),
    )

    gui._init_config_listeners()  # noqa: SLF001 - 验证 session 监听初始化边界。
    gui._init_config_listeners()  # noqa: SLF001 - 验证 session 监听初始化边界。

    assert [name for name, _onchange in bindings] == ["Task_Group_Field"]


def test_failed_synchronous_save_keeps_pending_fields_for_the_next_candidate() -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.alive = True
    gui._pending_config = {}  # noqa: SLF001 - 验证跨字段候选在失败后继续累积。
    gui._config_save_lock = RLock()  # noqa: SLF001 - 绕过完整 UI 构造，仅初始化保存边界。
    gui._saving_config = False  # noqa: SLF001 - 验证同步保存状态机。

    attempts: list[dict[str, object]] = []

    def save(modified: dict[str, object]) -> bool:
        attempts.append(dict(modified))
        return len(attempts) == 2

    vars(gui)["_save_config"] = save

    gui.save_config_change(
        "Event.Campaign.Event",
        "event-next",
    )
    gui.save_config_change(
        "Event.Campaign.Name",
        "d3",
    )

    assert attempts == [
        {"Event.Campaign.Event": "event-next"},
        {
            "Event.Campaign.Event": "event-next",
            "Event.Campaign.Name": "d3",
        },
    ]
    assert gui._pending_config == {}  # noqa: SLF001 - 成功后不得遗留旧候选。


def test_config_change_saves_synchronously_without_a_background_worker() -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.alive = True
    gui._pending_config = {}  # noqa: SLF001 - 验证同步保存状态机。
    gui._config_save_lock = RLock()  # noqa: SLF001 - 绕过完整 UI 构造，仅初始化保存边界。
    gui._saving_config = False  # noqa: SLF001 - 验证同步保存状态机。
    saved: list[dict[str, object]] = []

    def save(modified: dict[str, object]) -> bool:
        saved.append(dict(modified))
        return True

    vars(gui)["_save_config"] = save

    gui.save_config_change("Alas.Optimization.ScreenshotInterval", 0.2)

    assert saved == [{"Alas.Optimization.ScreenshotInterval": 0.2}]
    assert gui._pending_config == {}  # noqa: SLF001 - 回调返回前已经完成保存。
    assert not hasattr(gui, "modified_config_queue")


def test_config_change_waits_for_the_session_save_lock() -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.alive = True
    gui._pending_config = {}  # noqa: SLF001 - 验证跨线程保存边界。
    gui._config_save_lock = RLock()  # noqa: SLF001 - 绕过完整 UI 构造，仅初始化保存边界。
    gui._saving_config = False  # noqa: SLF001 - 验证同步保存状态机。
    worker_started = Event()
    save_entered = Event()

    def save(_modified: dict[str, object]) -> bool:
        save_entered.set()
        return True

    def change_config() -> None:
        worker_started.set()
        gui.save_config_change("Alas.Optimization.ScreenshotInterval", 0.2)

    vars(gui)["_save_config"] = save
    with gui._config_save_lock:  # noqa: SLF001 - 主线程占有锁时，回调线程不得进入保存。
        worker = Thread(target=change_config)
        worker.start()
        assert worker_started.wait(timeout=1)
        assert not save_entered.wait(timeout=0.1)

    assert save_entered.wait(timeout=1)
    worker.join(timeout=1)
    assert not worker.is_alive()


def test_config_change_after_session_stop_does_not_write() -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.alive = True
    gui._pending_config = {}  # noqa: SLF001 - 验证 session 停止边界。
    gui._config_save_lock = RLock()  # noqa: SLF001 - 绕过完整 UI 构造，仅初始化保存边界。
    gui._saving_config = False  # noqa: SLF001 - 验证 session 停止边界。
    attempts: list[dict[str, object]] = []

    class _TaskHandler:
        stopped = False

        def stop(self) -> None:
            self.stopped = True

    handler = _TaskHandler()
    gui.task_handler = cast("WebIOTaskHandler", handler)
    vars(gui)["_save_config"] = lambda modified: attempts.append(dict(modified)) or False

    gui.save_config_change("Event.Campaign.Event", "event-next")
    gui.stop()
    gui.save_config_change("Event.Campaign.Name", "d3")

    assert handler.stopped is True
    assert attempts == [{"Event.Campaign.Event": "event-next"}]
    assert gui._pending_config == {"Event.Campaign.Event": "event-next"}  # noqa: SLF001


def test_reentrant_config_change_is_saved_after_the_active_candidate() -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.alive = True
    gui._pending_config = {}  # noqa: SLF001 - 验证同步保存防重入。
    gui._config_save_lock = RLock()  # noqa: SLF001 - 绕过完整 UI 构造，仅初始化保存边界。
    gui._saving_config = False  # noqa: SLF001 - 验证同步保存防重入。
    attempts: list[dict[str, object]] = []

    def save(modified: dict[str, object]) -> bool:
        attempts.append(dict(modified))
        if len(attempts) == 1:
            gui.save_config_change("Event.Campaign.Name", "d3")
        return True

    vars(gui)["_save_config"] = save

    gui.save_config_change("Event.Campaign.Event", "event-next")

    assert attempts == [
        {"Event.Campaign.Event": "event-next"},
        {"Event.Campaign.Name": "d3"},
    ]
    assert gui._pending_config == {}  # noqa: SLF001 - 重入变化也必须在返回前完成。


def test_webui_field_save_validates_full_current_schema_before_writing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.ALAS_ARGS = read_file(filepath_args())
    vars(gui)["pin_remove_invalid_mark"] = lambda _paths: None
    vars(gui)["pin_set_invalid_mark"] = lambda _paths: None
    monkeypatch.setattr(webui_app, "read_config_file", lambda _name: _template())
    monkeypatch.setattr(
        webui_app,
        "write_config_file",
        lambda *_args: pytest.fail("invalid configuration must not be written"),
    )

    with pytest.raises(ConfigurationCompileError, match=r"Research\.Research\.UseCube"):
        gui._save_config_unchecked(  # noqa: SLF001 - 验证写入前的完整 schema 边界。
            {"Research.Research.UseCube": "removed-option"}
        )


def test_webui_field_save_does_not_replace_empty_value_with_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.ALAS_ARGS = read_file(filepath_args())
    vars(gui)["pin_remove_invalid_mark"] = lambda _paths: None
    vars(gui)["pin_set_invalid_mark"] = lambda _paths: None
    monkeypatch.setattr(webui_app, "read_config_file", lambda _name: _template())
    monkeypatch.setattr(
        webui_app,
        "write_config_file",
        lambda *_args: pytest.fail("invalid configuration must not be written"),
    )

    with pytest.raises(ConfigurationCompileError, match=r"ScreenshotInterval"):
        gui._save_config_unchecked(  # noqa: SLF001 - 空输入必须显式报错，不能静默恢复默认值。
            {"Alas.Optimization.ScreenshotInterval": ""}
        )


def test_webui_field_save_accepts_scheduler_number_and_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.ALAS_ARGS = read_file(filepath_args())
    vars(gui)["pin_remove_invalid_mark"] = lambda _paths: None
    vars(gui)["pin_set_invalid_mark"] = lambda _paths: None
    document = _template()
    validated: list[ConfigurationDocument] = []
    written: list[dict[str, object]] = []

    class _Manager:
        alive = False

    monkeypatch.setattr(webui_app, "toast", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(webui_app, "read_config_file", lambda _name: deepcopy(document))
    monkeypatch.setattr(webui_app, "validate_personal_configuration", _record_validation(validated))
    monkeypatch.setattr(webui_app.ProcessManager, "instance", _Manager)
    monkeypatch.setattr(
        webui_app,
        "write_config_file",
        lambda _name, saved: written.append(cast("dict[str, object]", saved)),
    )

    gui._save_config_unchecked(  # noqa: SLF001 - 验证 interval 的 int | range 持久化契约。
        {
            "Commission.Scheduler.SuccessInterval": "30",
            "Hard.Scheduler.FailureInterval": "15-30",
        }
    )

    assert len(written) == 1
    assert len(validated) == 2
    assert validated[-1] == written[0]
    commission = cast("dict[str, object]", written[0]["Commission"])
    commission_scheduler = cast("dict[str, object]", commission["Scheduler"])
    hard = cast("dict[str, object]", written[0]["Hard"])
    hard_scheduler = cast("dict[str, object]", hard["Scheduler"])
    assert commission_scheduler["SuccessInterval"] == 30
    assert hard_scheduler["FailureInterval"] == "15-30"


def test_webui_field_save_preserves_state_written_during_process_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.ALAS_ARGS = read_file(filepath_args())
    vars(gui)["pin_remove_invalid_mark"] = lambda _paths: None
    vars(gui)["pin_set_invalid_mark"] = lambda _paths: None
    before_stop = _template()
    after_stop = deepcopy(before_stop)
    main = cast("dict[str, object]", after_stop["Main"])
    scheduler = cast("dict[str, object]", main["Scheduler"])
    scheduler["NextRun"] = "2026-07-16 01:02:03"
    storage = cast("dict[str, object]", main["Storage"])
    storage["Storage"] = {"progress": {"wave": 4}}
    reads = iter([before_stop, after_stop])
    validated: list[ConfigurationDocument] = []
    written: list[dict[str, object]] = []

    class _Manager:
        alive = True

        def stop(self) -> None:
            self.alive = False

    manager = _Manager()
    monkeypatch.setattr(webui_app, "toast", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(webui_app, "read_config_file", lambda _name: deepcopy(next(reads)))
    monkeypatch.setattr(webui_app, "validate_personal_configuration", _record_validation(validated))
    monkeypatch.setattr(webui_app.ProcessManager, "instance", lambda: manager)
    monkeypatch.setattr(
        webui_app,
        "write_config_file",
        lambda _name, document: written.append(cast("dict[str, object]", document)),
    )

    gui._save_config_unchecked(  # noqa: SLF001 - 验证停机后的最新状态参与最终写入。
        {"Alas.Optimization.ScreenshotInterval": 0.2}
    )

    assert len(written) == 1
    assert len(validated) == 2
    assert validated[-1] == written[0]
    first_main = cast("dict[str, object]", validated[0]["Main"])
    assert cast("dict[str, object]", first_main["Scheduler"])["NextRun"] != "2026-07-16 01:02:03"
    saved = written[0]
    saved_alas = cast("dict[str, object]", saved["Alas"])
    saved_optimization = cast("dict[str, object]", saved_alas["Optimization"])
    assert saved_optimization["ScreenshotInterval"] == 0.2
    saved_main = cast("dict[str, object]", saved["Main"])
    assert cast("dict[str, object]", saved_main["Scheduler"])["NextRun"] == "2026-07-16 01:02:03"
    assert cast("dict[str, object]", saved_main["Storage"])["Storage"] == {"progress": {"wave": 4}}


def test_webui_field_save_reloads_after_a_concurrent_process_exit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.ALAS_ARGS = read_file(filepath_args())
    vars(gui)["pin_remove_invalid_mark"] = lambda _paths: None
    vars(gui)["pin_set_invalid_mark"] = lambda _paths: None
    before_exit = _template()
    after_exit = deepcopy(before_exit)
    main = cast("dict[str, object]", after_exit["Main"])
    scheduler = cast("dict[str, object]", main["Scheduler"])
    scheduler["NextRun"] = "2026-07-16 02:03:04"
    reads = iter([before_exit, after_exit])
    written: list[dict[str, object]] = []

    class _Manager:
        alive = False

    monkeypatch.setattr(webui_app, "toast", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(webui_app, "read_config_file", lambda _name: deepcopy(next(reads)))
    monkeypatch.setattr(webui_app, "validate_personal_configuration", lambda _candidate: None)
    monkeypatch.setattr(webui_app.ProcessManager, "instance", _Manager)
    monkeypatch.setattr(
        webui_app,
        "write_config_file",
        lambda _name, document: written.append(cast("dict[str, object]", document)),
    )

    gui._save_config_unchecked(  # noqa: SLF001 - 已退出进程的最终运行状态也必须从磁盘重读。
        {"Alas.Optimization.ScreenshotInterval": 0.2}
    )

    assert len(written) == 1
    saved_main = cast("dict[str, object]", written[0]["Main"])
    assert cast("dict[str, object]", saved_main["Scheduler"])["NextRun"] == "2026-07-16 02:03:04"


def test_webui_field_save_revalidates_gameplay_fields_written_during_stop(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gui = AlasGUI.__new__(AlasGUI)
    gui.ALAS_ARGS = read_file(filepath_args())
    vars(gui)["pin_remove_invalid_mark"] = lambda _paths: None
    vars(gui)["pin_set_invalid_mark"] = lambda _paths: None
    before_stop = _template()
    after_stop = deepcopy(before_stop)
    event = cast("dict[str, object]", after_stop["Event"])
    campaign = cast("dict[str, object]", event["Campaign"])
    campaign["Name"] = "missing-stage"
    reads = iter([before_stop, after_stop])
    validated: list[ConfigurationDocument] = []
    real_validator = webui_app.validate_personal_configuration

    class _Manager:
        alive = True

        def stop(self) -> None:
            self.alive = False

    manager = _Manager()

    def validate_after_stop(candidate: ConfigurationDocument) -> None:
        validated.append(deepcopy(candidate))
        if len(validated) == 2:
            real_validator(candidate)

    monkeypatch.setattr(webui_app, "read_config_file", lambda _name: deepcopy(next(reads)))
    monkeypatch.setattr(webui_app, "validate_personal_configuration", validate_after_stop)
    monkeypatch.setattr(webui_app.ProcessManager, "instance", lambda: manager)
    monkeypatch.setattr(
        webui_app,
        "write_config_file",
        lambda *_args: pytest.fail("invalid post-stop configuration must not be written"),
    )

    with pytest.raises(ConfigurationCompileError, match="missing-stage"):
        gui._save_config_unchecked(  # noqa: SLF001 - 最终候选必须重新走内容和 factory 校验。
            {"Alas.Optimization.ScreenshotInterval": 0.2}
        )

    assert len(validated) == 2
    first_event = cast("dict[str, object]", validated[0]["Event"])
    second_event = cast("dict[str, object]", validated[1]["Event"])
    assert cast("dict[str, object]", first_event["Campaign"])["Name"] != "missing-stage"
    assert cast("dict[str, object]", second_event["Campaign"])["Name"] == "missing-stage"


def test_webui_import_validates_then_replaces_personal_configuration(tmp_path: Path) -> None:
    destination = tmp_path / "alas.json"
    destination.write_text("old", encoding="utf-8")
    calls: list[str] = []
    document = _template()

    def stop_before_replace() -> None:
        assert destination.read_text(encoding="utf-8") == "old"
        calls.append("stop")

    import_personal_configuration(
        json.dumps(document, ensure_ascii=False).encode(),
        destination,
        before_replace=stop_before_replace,
    )

    assert json.loads(destination.read_text(encoding="utf-8")) == document
    assert calls == ["stop"]


@pytest.mark.parametrize(
    "invalid_kind",
    ["unknown-field", "invalid-option", "factory-range"],
)
def test_webui_import_rejects_invalid_configuration_without_overwriting(
    invalid_kind: str,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "alas.json"
    destination.write_text("original", encoding="utf-8")
    document = _template()
    if invalid_kind == "unknown-field":
        document["LegacyTask"] = {}
    elif invalid_kind == "invalid-option":
        research = cast("dict[str, object]", document["Research"])
        settings = cast("dict[str, object]", research["Research"])
        settings["UseCube"] = "removed-option"
    elif invalid_kind == "factory-range":
        tactical = cast("dict[str, object]", document["Tactical"])
        student = cast("dict[str, object]", tactical["AddNewStudent"])
        student["MinLevel"] = 0
    calls: list[str] = []

    with pytest.raises(ConfigurationCompileError):
        import_personal_configuration(
            json.dumps(document, ensure_ascii=False).encode(),
            destination,
            before_replace=lambda: calls.append("stop"),
        )

    assert destination.read_text(encoding="utf-8") == "original"
    assert calls == []


def test_webui_import_does_not_stop_or_overwrite_when_content_validation_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "alas.json"
    destination.write_text("original", encoding="utf-8")
    document = _template()
    event = cast("dict[str, object]", document["Event"])
    campaign = cast("dict[str, object]", event["Campaign"])
    campaign["Name"] = "missing-stage"
    validated: list[ConfigurationDocument] = []
    calls: list[str] = []

    def reject_content_reference(candidate: ConfigurationDocument) -> None:
        validated.append(deepcopy(candidate))
        message = "$ compiled task settings are invalid: missing-stage"
        raise ConfigurationCompileError(message)

    monkeypatch.setattr(webui_app, "validate_personal_configuration", reject_content_reference)

    with pytest.raises(ConfigurationCompileError, match="missing-stage"):
        import_personal_configuration(
            json.dumps(document, ensure_ascii=False).encode(),
            destination,
            before_replace=lambda: calls.append("stop"),
        )

    assert validated == [document]
    assert destination.read_text(encoding="utf-8") == "original"
    assert calls == []


def test_webui_import_does_not_replace_config_when_process_cannot_stop(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "alas.json"
    destination.write_text("original", encoding="utf-8")
    document = _template()
    validated: list[ConfigurationDocument] = []

    monkeypatch.setattr(webui_app, "validate_personal_configuration", _record_validation(validated))

    def fail_to_stop() -> None:
        message = "process still alive"
        raise RuntimeError(message)

    with pytest.raises(RuntimeError, match="process still alive"):
        import_personal_configuration(
            json.dumps(document, ensure_ascii=False).encode(),
            destination,
            before_replace=fail_to_stop,
        )

    assert validated == [document]
    assert destination.read_text(encoding="utf-8") == "original"
