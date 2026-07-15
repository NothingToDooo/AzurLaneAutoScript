import subprocess
import sys

import pytest


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
