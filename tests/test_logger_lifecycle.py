import json
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from uuid import uuid4

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBE_PREFIX = "LOGGER_LIFECYCLE="


def _run_python(script: str, *args: str, cwd: Path) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    inherited_pythonpath = environment.get("PYTHONPATH")
    pythonpath = [str(PROJECT_ROOT)]
    if inherited_pythonpath:
        pythonpath.append(inherited_pythonpath)
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    return subprocess.run(  # ruff:ignore[subprocess-without-shell-equals-true] - 使用当前解释器隔离 logger 模块状态。
        [sys.executable, "-c", script, *args],
        check=True,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        creationflags=creationflags,
    )


def _probe_payload(output: str) -> dict[str, object]:
    for line in output.splitlines():
        if line.startswith(PROBE_PREFIX):
            return cast("dict[str, object]", json.loads(line.removeprefix(PROBE_PREFIX)))
    message = f"logger lifecycle probe did not return a payload:\n{output}"
    raise AssertionError(message)


def test_import_does_not_change_cwd_or_create_a_log_file(tmp_path: Path) -> None:
    probe_name = f"logger_import_{uuid4().hex}"
    today = datetime.now(tz=UTC).astimezone().date()
    legacy_log_file = PROJECT_ROOT / "log" / f"{today}_{probe_name}.txt"
    script = f"""
import json
import sys
from pathlib import Path

sys.argv = [sys.argv[1]]
from module.logger import get_log_file

try:
    log_file = get_log_file()
except RuntimeError:
    log_file = None
print({PROBE_PREFIX!r} + json.dumps({{"cwd": str(Path.cwd()), "log_file": log_file}}))
"""

    try:
        result = _run_python(script, probe_name, cwd=tmp_path)
        legacy_log_created = legacy_log_file.exists()
    finally:
        legacy_log_file.unlink(missing_ok=True)

    payload = _probe_payload(result.stdout)
    assert Path(cast("str", payload["cwd"])) == tmp_path
    assert payload["log_file"] is None
    assert not legacy_log_created


def test_explicit_configuration_writes_to_project_log_without_changing_cwd(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    message = f"logger-message-{uuid4().hex}"
    script = f"""
import json
import sys
from pathlib import Path

from module.logger import configure_file_logging, get_log_file, logger

log_file = configure_file_logging(Path(sys.argv[1]), name="probe")
logger.info(sys.argv[2])
for handler in logger.handlers:
    handler.flush()
print(
    {PROBE_PREFIX!r}
    + json.dumps(
        {{"cwd": str(Path.cwd()), "log_file": str(log_file), "reported": str(get_log_file())}}
    )
)
"""

    result = _run_python(script, str(project_root), message, cwd=tmp_path)

    payload = _probe_payload(result.stdout)
    log_file = Path(cast("str", payload["log_file"]))
    assert Path(cast("str", payload["cwd"])) == tmp_path
    assert log_file.is_absolute()
    assert log_file.parent == project_root / "log"
    assert Path(cast("str", payload["reported"])) == log_file
    assert message in log_file.read_text(encoding="utf-8")
