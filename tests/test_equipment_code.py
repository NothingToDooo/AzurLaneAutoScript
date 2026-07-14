from types import SimpleNamespace
from typing import cast

import pytest
import yaml

from module.equipment import equipment_code as equipment_code_module
from module.equipment.equipment_code import (
    EMPTY_CODE,
    FAST_INPUT_IME,
    EquipmentCodeHandler,
    is_equipment_code,
)
from module.exception import ScriptError


class _Device:
    def __init__(self) -> None:
        self.commands: list[tuple[str | int, ...]] = []
        self.checked_failures: set[tuple[str | int, ...]] = set()
        self.current_ime = "com.sohu.inputmethod/.SogouIME"

    def adb_shell(self, command: list[str | int]) -> str:
        self.commands.append(tuple(command))
        if command[:4] == ["ime", "list", "-s", "-a"]:
            return f"{FAST_INPUT_IME}\n{self.current_ime}"
        if command[:5] == ["settings", "get", "secure", "default_input_method"]:
            return self.current_ime
        if command[:2] == ["ime", "set"]:
            self.current_ime = str(command[2])
        return "Broadcast completed: result=0"

    def adb_shell_checked(self, command: list[str | int]) -> str:
        normalized = tuple(command)
        if normalized in self.checked_failures:
            message = f"ADB shell command failed: {normalized}"
            raise OSError(message)
        return self.adb_shell(command)


class _EquipmentCodeHarness(EquipmentCodeHandler):
    def exercise_fast_input(self) -> None:
        previous = self._enable_fast_input_ime()
        self._broadcast_input("ADB_INPUT_TEXT", text="encoded")
        self._broadcast_input("ADB_EDITOR_CODE", code=6)
        self._restore_input_method(previous)

    def apply_code(self, code: str | None = None) -> bool:
        return self._code_apply(code)

    def export_code(self) -> str | None:
        return self._code_export()


def _handler(config: str | None = None) -> _EquipmentCodeHarness:
    handler = object.__new__(_EquipmentCodeHarness)
    handler.config = SimpleNamespace(
        EquipmentCode_Config=config,
        EquipmentCode_ExportToConfig=True,
    )
    handler.device = _Device()
    return handler


def test_equipment_code_config_round_trip() -> None:
    handler = _handler("DD: code-dd\nbogue: null")

    assert handler.get_code("DD") == "code-dd"
    assert handler.get_code("bogue") is None

    handler.set_code("bogue", "code-bogue")

    assert yaml.safe_load(handler.config.EquipmentCode_Config) == {
        "DD": "code-dd",
        "bogue": "code-bogue",
    }


def test_equipment_code_rejects_non_mapping_yaml() -> None:
    handler = _handler("- not\n- a\n- mapping")

    with pytest.raises(ScriptError, match="Invalid EquipmentCode_Config"):
        handler.get_code("DD")


def test_equipment_code_clear_exports_missing_code(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _handler("DD: null")
    applied: list[str | None] = []

    def apply(code: str | None = None) -> bool:
        assert handler.last_code == "MC8xLzIvMy80XDA="
        applied.append(code)
        return True

    monkeypatch.setattr(handler, "equipment_code_supported", lambda: True)
    monkeypatch.setattr(handler, "_code_enter", lambda: None)
    monkeypatch.setattr(handler, "current_ship", lambda: "DD")
    monkeypatch.setattr(handler, "_code_export", lambda: "MC8xLzIvMy80XDA=")
    monkeypatch.setattr(handler, "_code_apply", apply)

    assert handler.code_clear() is True
    assert handler.last_code == "MC8xLzIvMy80XDA="
    assert handler.get_code("DD") == "MC8xLzIvMy80XDA="
    assert applied == [None]


def test_equipment_code_clear_keeps_saved_code_for_restore(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _handler("DD: saved-code")
    applied: list[str | None] = []

    def apply(code: str | None = None) -> bool:
        assert handler.last_code == "saved-code"
        applied.append(code)
        return True

    monkeypatch.setattr(handler, "equipment_code_supported", lambda: True)
    monkeypatch.setattr(handler, "_code_enter", lambda: None)
    monkeypatch.setattr(handler, "current_ship", lambda: "DD")
    monkeypatch.setattr(handler, "_code_export", lambda: pytest.fail("saved code must not be exported again"))
    monkeypatch.setattr(handler, "_code_apply", apply)

    assert handler.code_clear() is True
    assert handler.last_code == "saved-code"
    assert applied == [None]


def test_equipment_code_clear_without_code_or_export_does_not_clear(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _handler("DD: null")
    handler.config.EquipmentCode_ExportToConfig = False
    exports: list[None] = []
    applied: list[str | None] = []
    monkeypatch.setattr(handler, "equipment_code_supported", lambda: True)
    monkeypatch.setattr(handler, "_code_enter", lambda: None)
    monkeypatch.setattr(handler, "current_ship", lambda: "DD")
    monkeypatch.setattr(handler, "_code_export", lambda: exports.append(None))
    monkeypatch.setattr(handler, "_code_apply", lambda code=None: not applied.append(code))

    assert handler.code_clear() is False
    assert handler.last_code is None
    assert exports == []
    assert applied == []


def test_equipment_code_apply_falls_back_to_last_export(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _handler("ranger: null")
    handler.last_code = "MC8xLzIvMy80XDA="
    applied: list[str | None] = []
    monkeypatch.setattr(handler, "equipment_code_supported", lambda: True)
    monkeypatch.setattr(handler, "_code_enter", lambda: None)
    monkeypatch.setattr(handler, "current_ship", lambda: "ranger")
    monkeypatch.setattr(handler, "_code_apply", lambda code=None: not applied.append(code))

    assert handler.code_apply() is True
    assert applied == ["MC8xLzIvMy80XDA="]


def test_code_apply_retries_without_input_when_preview_clear_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _handler()
    clear_attempts: list[None] = []

    def clear_preview() -> bool:
        clear_attempts.append(None)
        return False

    monkeypatch.setattr(handler, "_code_preview_clear", clear_preview)
    monkeypatch.setattr(handler, "_code_input", lambda _code: pytest.fail("input must wait for preview clear"))
    monkeypatch.setattr(handler, "_code_confirm", lambda: pytest.fail("confirm must wait for preview clear"))

    assert handler.apply_code("MC8xLzIvMy80XDA=") is False
    assert len(clear_attempts) == 5


def test_fast_input_ime_uses_adb_and_restores_previous_ime() -> None:
    handler = _handler()
    device = cast("_Device", handler.device)

    handler.exercise_fast_input()

    assert device.current_ime == "com.sohu.inputmethod/.SogouIME"
    assert ("ime", "enable", FAST_INPUT_IME) in device.commands
    assert ("am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "text", "encoded") in device.commands
    assert ("am", "broadcast", "-a", "ADB_EDITOR_CODE", "--ei", "code", 6) in device.commands


def test_fast_input_ime_surfaces_checked_shell_failure() -> None:
    handler = _handler()
    device = cast("_Device", handler.device)
    device.checked_failures.add(("ime", "set", FAST_INPUT_IME))

    with pytest.raises(ScriptError, match="Unable to set FastInputIME"):
        handler.exercise_fast_input()

    assert not any(command[:3] == ("am", "broadcast", "-a") for command in device.commands)


def test_equipment_code_shape_validation() -> None:
    assert is_equipment_code(EMPTY_CODE) is True
    assert is_equipment_code("not-base64") is False


def test_export_waits_for_clipboard_sequence_change(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _handler()
    info_bar_results = iter([False, True])
    monkeypatch.setattr(handler, "handle_info_bar", lambda: False)
    monkeypatch.setattr(handler, "info_bar_count", lambda: int(next(info_bar_results)))
    monkeypatch.setattr(handler, "appear_then_click", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(handler, "loop", lambda **_kwargs: iter([None, None, None]))
    sequences = iter([10, 10, 11])
    clipboard_reads: list[None] = []
    monkeypatch.setattr(equipment_code_module, "read_windows_clipboard_sequence", lambda: next(sequences))
    monkeypatch.setattr(
        equipment_code_module,
        "read_windows_clipboard_text",
        lambda: "MC8xLzIvMy80XDA=" if not clipboard_reads.append(None) else None,
    )

    assert handler.export_code() == "MC8xLzIvMy80XDA="
    assert len(clipboard_reads) == 1


def test_export_does_not_read_clipboard_without_success_info_bar(monkeypatch: pytest.MonkeyPatch) -> None:
    handler = _handler()
    clipboard_reads: list[None] = []
    monkeypatch.setattr(handler, "handle_info_bar", lambda: False)
    monkeypatch.setattr(handler, "info_bar_count", lambda: 0)
    monkeypatch.setattr(handler, "appear_then_click", lambda *_args, **_kwargs: True)
    monkeypatch.setattr(handler, "loop", lambda **_kwargs: iter([None, None]))
    monkeypatch.setattr(equipment_code_module, "read_windows_clipboard_sequence", lambda: 10)
    monkeypatch.setattr(
        equipment_code_module,
        "read_windows_clipboard_text",
        lambda: "MC8xLzIvMy80XDA=" if not clipboard_reads.append(None) else None,
    )

    assert handler.export_code() is None
    assert clipboard_reads == []
