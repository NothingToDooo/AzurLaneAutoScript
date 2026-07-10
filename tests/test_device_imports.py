import importlib

from module.device.connection import Connection


def test_device_method_utils_imports() -> None:
    module = importlib.import_module("module.device.method.utils")

    assert hasattr(module, "retry_sleep")


def test_device_connection_imports() -> None:
    module = importlib.import_module("module.device.connection")

    assert hasattr(module, "Connection")


def test_legacy_device_services_do_not_inherit_connection() -> None:
    classes = (
        importlib.import_module("module.device.app_control").AppControl,
        importlib.import_module("module.device.method.minitouch").Minitouch,
        importlib.import_module("module.device.method.nemu_ipc").NemuIpc,
        importlib.import_module("module.device.platform.platform_base").PlatformBase,
        importlib.import_module("module.device.platform.platform_windows").PlatformWindows,
    )

    assert all(Connection not in cls.__mro__ for cls in classes)


def test_device_modules_import_in_independent_orders() -> None:
    names = (
        "module.device.services",
        "module.device.runtime",
        "module.device.method.minitouch",
        "module.device.method.nemu_ipc",
        "module.device.platform.platform_base",
        "module.device.platform.platform_windows",
        "module.device.device",
    )

    for name in names:
        assert importlib.import_module(name).__name__ == name
