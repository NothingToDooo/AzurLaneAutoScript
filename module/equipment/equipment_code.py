import base64
import ctypes
import re
import sys
from collections.abc import Mapping

import yaml

from module.base.timer import Timer
from module.equipment import assets as equipment_assets
from module.exception import ScriptError
from module.logger import logger
from module.retire.assets import TEMPLATE_BOGUE, TEMPLATE_HERMES, TEMPLATE_LANGLEY, TEMPLATE_RANGER
from module.storage import assets as storage_assets
from module.storage.storage import StorageHandler

EMPTY_CODE = "MC8wLzAvMC8wXDA="
FAST_INPUT_IME = "com.github.uiautomator/.FastInputIME"
EQUIPMENT_CODE_CONFIG_INVALID_MESSAGE = "Invalid EquipmentCode_Config"
EQUIPMENT_CODE_CLIPBOARD_MESSAGE = "Unable to read equipment code from the Windows clipboard"
EQUIPMENT_PREVIEW = (
    equipment_assets.EQUIPMENT_CODE_EQUIP_0,
    equipment_assets.EQUIPMENT_CODE_EQUIP_1,
    equipment_assets.EQUIPMENT_CODE_EQUIP_2,
    equipment_assets.EQUIPMENT_CODE_EQUIP_3,
    equipment_assets.EQUIPMENT_CODE_EQUIP_4,
    equipment_assets.EQUIPMENT_CODE_EQUIP_5,
)


def read_windows_clipboard_sequence() -> int | None:
    """返回 Windows 剪贴板变更序号；不可用时返回 None。"""
    if sys.platform != "win32":
        return None
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    return int(user32.GetClipboardSequenceNumber())


def read_windows_clipboard_text() -> str | None:
    """读取 MuMu 同步到 Windows 的 Unicode 文本剪贴板。"""
    if sys.platform != "win32":
        return None

    user32 = ctypes.WinDLL("user32", use_last_error=True)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    user32.GetClipboardData.restype = ctypes.c_void_p
    kernel32.GlobalLock.argtypes = [ctypes.c_void_p]
    kernel32.GlobalLock.restype = ctypes.c_void_p
    kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

    if not user32.OpenClipboard(None):
        return None
    try:
        handle = user32.GetClipboardData(13)  # CF_UNICODETEXT
        if not handle:
            return None
        pointer = kernel32.GlobalLock(handle)
        if not pointer:
            return None
        try:
            return ctypes.wstring_at(pointer)
        finally:
            kernel32.GlobalUnlock(handle)
    finally:
        user32.CloseClipboard()


def is_equipment_code(value: str | None) -> bool:
    if not value:
        return False
    try:
        decoded = base64.b64decode(value, validate=True)
    except ValueError:
        return False
    return decoded.count(b"/") >= 4


class EquipmentCodeHandler(StorageHandler):
    last_code: str | None = None

    def _load_code_config(self) -> dict[str, str | None]:
        raw = self.config.EquipmentCode_Config
        if raw is None or not raw.strip():
            return {}

        result: dict[str, str | None] = {}
        try:
            documents = list(yaml.safe_load_all(raw))
        except yaml.YAMLError as error:
            logger.error(EQUIPMENT_CODE_CONFIG_INVALID_MESSAGE)
            raise ScriptError(EQUIPMENT_CODE_CONFIG_INVALID_MESSAGE) from error

        for document in documents:
            if document is None:
                continue
            if not isinstance(document, Mapping):
                logger.error(EQUIPMENT_CODE_CONFIG_INVALID_MESSAGE)
                raise ScriptError(EQUIPMENT_CODE_CONFIG_INVALID_MESSAGE)
            for name, code in document.items():
                if not isinstance(name, str) or (code is not None and not isinstance(code, str)):
                    logger.error(EQUIPMENT_CODE_CONFIG_INVALID_MESSAGE)
                    raise ScriptError(EQUIPMENT_CODE_CONFIG_INVALID_MESSAGE)
                result[name] = code
        return result

    def get_code(self, name: str) -> str | None:
        code = self._load_code_config().get(name)
        if code is None:
            logger.info(f"Equipment code is not configured for {name}")
        return code

    def set_code(self, name: str, code: str) -> None:
        config = self._load_code_config()
        config[name] = code
        self.config.EquipmentCode_Config = yaml.safe_dump(config, allow_unicode=True, sort_keys=False).strip()

    def current_ship(self) -> str:
        """识别宝石队当前舰船；普通航母按模板区分，其他舰船按 DD 处理。"""
        for _ in self.loop():
            if not self.appear(equipment_assets.EMPTY_SHIP_R):
                break

        if TEMPLATE_BOGUE.match(self.device.image, scaling=1.46):
            logger.info("Bogue detected")
            return "bogue"
        if TEMPLATE_HERMES.match(self.device.image, scaling=124 / 89):
            logger.info("Hermes detected")
            return "hermes"
        if TEMPLATE_RANGER.match(self.device.image, scaling=4 / 3):
            logger.info("Ranger detected")
            return "ranger"
        if TEMPLATE_LANGLEY.match(self.device.image, scaling=25 / 21):
            logger.info("Langley detected")
            return "langley"

        logger.warning("Unknown ship detected, assuming DD")
        return "DD"

    def _code_enter(self) -> None:
        for _ in self.loop():
            if self.appear(equipment_assets.EQUIPMENT_CODE_PAGE_CHECK, offset=(5, 5)):
                return
            if self.appear_then_click(equipment_assets.EQUIPMENT_CODE_ENTRANCE, offset=(5, 5), interval=1):
                continue

    def is_code_preview_loaded(self) -> bool:
        max_index = 5 if self.appear(equipment_assets.EQUIPMENT_CODE_EQUIP_5_LOCKED, offset=(5, 5)) else 6
        return any(not self.appear(EQUIPMENT_PREVIEW[index], offset=(5, 5)) for index in range(max_index))

    def _code_preview_clear(self) -> bool:
        for _ in self.loop(timeout=2):
            if not self.is_code_preview_loaded():
                return True
            if self.appear_then_click(equipment_assets.EQUIPMENT_CODE_CLEAR, offset=(5, 5), interval=1):
                continue
        return False

    def _available_input_methods(self) -> set[str]:
        output = self.device.adb_shell(["ime", "list", "-s", "-a"])
        return {line.strip() for line in output.splitlines() if line.strip()}

    def equipment_code_supported(self) -> bool:
        if FAST_INPUT_IME in self._available_input_methods():
            return True
        logger.error(f"EquipmentCode requires {FAST_INPUT_IME} on the current MuMu instance")
        return False

    def _current_input_method(self) -> str:
        return self.device.adb_shell(["settings", "get", "secure", "default_input_method"]).strip()

    def _input_method_shown(self) -> bool:
        output = self.device.adb_shell(["dumpsys", "input_method"])
        return "mInputShown=true" in output

    def _enable_fast_input_ime(self) -> str:
        previous = self._current_input_method()
        if previous == FAST_INPUT_IME:
            return previous
        self.device.adb_shell(["ime", "enable", FAST_INPUT_IME])
        self.device.adb_shell(["ime", "set", FAST_INPUT_IME])
        return previous

    def _restore_input_method(self, previous: str) -> None:
        if previous and previous not in {FAST_INPUT_IME, "null"}:
            self.device.adb_shell(["ime", "set", previous])

    def _broadcast_input(self, action: str, *, text: str | None = None, code: int | None = None) -> None:
        command = ["am", "broadcast", "-a", action]
        if text is not None:
            command.extend(["--es", "text", text])
        if code is not None:
            command.extend(["--ei", "code", code])
        output = self.device.adb_shell(command)
        if re.search(r"(?:Exception|Error):", output):
            message = f"FastInputIME broadcast failed: {action}"
            raise ScriptError(message)

    def _code_input(self, code: str) -> bool:
        logger.info(f"Code input: {code}")
        previous_ime = self._enable_fast_input_ime()
        click_timer = Timer(1, count=3)
        try:
            for _ in self.loop(timeout=10):
                if self._current_input_method() == FAST_INPUT_IME and self._input_method_shown():
                    break
                if click_timer.reached_and_reset():
                    self.device.click(equipment_assets.EQUIPMENT_CODE_TEXTBOX)
            else:
                logger.warning("Equipment code input field did not gain focus")
                return False

            encoded = base64.b64encode(code.encode()).decode()
            self._broadcast_input("ADB_CLEAR_TEXT")
            self._broadcast_input("ADB_INPUT_TEXT", text=encoded)
            self._broadcast_input("ADB_EDITOR_CODE", code=6)
        finally:
            self._restore_input_method(previous_ime)

        for _ in self.loop(timeout=10, skip_first=False):
            if self.is_code_preview_loaded():
                return True
            if self.appear_then_click(equipment_assets.EQUIPMENT_CODE_ENTER, offset=(5, 5), interval=3):
                continue
        logger.warning("Equipment code load failed")
        return False

    def _code_confirm(self) -> bool:
        logger.info("Code apply")
        for _ in self.loop(timeout=10):
            if self.appear(equipment_assets.EQUIPMENT_CODE_ENTRANCE, offset=(5, 5)):
                return True
            if self.appear(storage_assets.EQUIPMENT_FULL, offset=(30, 30)):
                return False
            if self.handle_popup_confirm("EQUIPMENT_CODE"):
                continue
            if self.appear_then_click(equipment_assets.EQUIPMENT_CODE_CONFIRM, offset=(5, 5), interval=3):
                continue
        return False

    def _code_apply(self, code: str | None = None) -> bool:
        for _ in range(5):
            if not self._code_preview_clear():
                continue
            if code is not None and code != EMPTY_CODE and not self._code_input(code):
                continue
            if self._code_confirm():
                logger.info("Equipment code apply complete")
                return True
            self.handle_storage_full()
        return False

    def _code_export(self) -> str | None:
        sequence_before = read_windows_clipboard_sequence()
        if sequence_before is None:
            logger.error(EQUIPMENT_CODE_CLIPBOARD_MESSAGE)
            return None

        self.handle_info_bar()
        exported = False
        for _ in self.loop(timeout=10):
            if self.info_bar_count():
                exported = True
                break
            if self.appear_then_click(equipment_assets.EQUIPMENT_CODE_EXPORT, offset=(5, 5), interval=3):
                continue
        if not exported:
            logger.error("Equipment code export did not finish")
            return None

        for _ in self.loop(timeout=5, skip_first=False):
            if read_windows_clipboard_sequence() == sequence_before:
                continue
            code = read_windows_clipboard_text()
            if is_equipment_code(code):
                return code

        logger.error(EQUIPMENT_CODE_CLIPBOARD_MESSAGE)
        return None

    def code_clear(self, name: str | None = None) -> bool:
        if not self.equipment_code_supported():
            return False

        self._code_enter()
        name = self.current_ship() if name is None else name
        code = self.get_code(name)
        if code is None and self.config.EquipmentCode_ExportToConfig:
            code = self._code_export()
            if code is None:
                return False
            self.set_code(name, code)
        if code is None:
            logger.error(f"No equipment code is available for {name}, refuse to clear equipments")
            return False

        self.last_code = code
        return self._code_apply()

    def code_apply(self, name: str | None = None) -> bool:
        if not self.equipment_code_supported():
            return False

        self._code_enter()
        name = self.current_ship() if name is None else name
        code = self.get_code(name) or self.last_code
        if code is None:
            logger.error(f"No equipment code is available for {name}")
            return False
        return self._code_apply(code)
