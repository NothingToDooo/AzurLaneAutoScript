from module.device.method import utils


class _Logger:
    def __init__(self):
        self.errors = []
        self.exceptions = []

    def error(self, error):
        self.errors.append(str(error))

    def exception(self, error):
        self.exceptions.append(str(error))


def test_handle_adb_error_retries_known_transient_errors(monkeypatch) -> None:
    logger = _Logger()
    monkeypatch.setattr(utils, "logger", logger)

    for text in [
        "device '127.0.0.1:59865' not found",
        "adb read timeout",
        "closed",
        "device offline",
        "USB device 127.0.0.1:7555 is offline",
        "rest",
    ]:
        assert utils.handle_adb_error(RuntimeError(text)) is True

    assert logger.errors == [
        "device '127.0.0.1:59865' not found",
        "adb read timeout",
        "closed",
        "device offline",
        "USB device 127.0.0.1:7555 is offline",
        "rest",
    ]
    assert logger.exceptions == []


def test_handle_adb_error_reports_unknown_errors(monkeypatch) -> None:
    logger = _Logger()
    reasons = []
    monkeypatch.setattr(utils, "logger", logger)
    monkeypatch.setattr(utils, "possible_reasons", lambda *items: reasons.extend(items))

    assert utils.handle_adb_error(RuntimeError("unknown adb failure")) is False

    assert logger.errors == []
    assert logger.exceptions == ["unknown adb failure"]
    assert reasons == [
        "Emulator died, please restart emulator",
        "Serial incorrect, no such device exists or emulator is not running",
    ]
