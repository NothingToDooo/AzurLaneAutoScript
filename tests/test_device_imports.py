import importlib


def test_device_method_utils_imports() -> None:
    module = importlib.import_module("module.device.method.utils")

    assert hasattr(module, "retry_sleep")


def test_device_connection_imports() -> None:
    module = importlib.import_module("module.device.connection")

    assert hasattr(module, "Connection")
