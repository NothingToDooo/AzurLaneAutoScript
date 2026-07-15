import subprocess
import sys


def test_catalog_import_does_not_load_production_device_graph() -> None:
    script = "import sys; import module.task_registry; assert 'module.device.device' not in sys.modules"
    subprocess.run([sys.executable, "-c", script], check=True)  # noqa: S603
