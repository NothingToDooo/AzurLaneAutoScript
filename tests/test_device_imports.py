import importlib
import subprocess
import sys

import pytest

from module.device.app_service import AppController
from module.device.connection import Connection
from module.device.minitouch_service import MinitouchController
from module.device.nemu_ipc_service import NemuIpcCapture


def test_device_method_utils_imports() -> None:
    module = importlib.import_module("module.device.method.utils")

    assert hasattr(module, "retry_sleep")


def test_device_connection_imports() -> None:
    module = importlib.import_module("module.device.connection")

    assert hasattr(module, "Connection")


def test_owned_device_services_do_not_inherit_connection() -> None:
    classes = (AppController, MinitouchController, NemuIpcCapture)

    assert all(Connection not in cls.__mro__ for cls in classes)


@pytest.mark.parametrize(
    "statement",
    [
        "import module.device.services",
        "import module.device.runtime",
        "import module.device.app_service",
        "import module.device.minitouch_service",
        "import module.device.nemu_ipc_service",
        "import module.device.device",
    ],
)
def test_device_modules_import_in_cold_interpreters(statement: str) -> None:
    result = subprocess.run(  # noqa: S603
        [sys.executable, "-c", statement],
        capture_output=True,
        check=False,
        text=True,
        timeout=20,
    )

    assert result.returncode == 0, result.stderr
