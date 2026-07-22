import json
import os
import subprocess  # ruff:ignore[suspicious-subprocess-import] - 使用当前解释器验证隔离进程中的真实导入行为。
import sys
from pathlib import Path
from typing import cast

import numpy as np
import pytest
from PIL import Image

from module.base.button import Button
from module.base.template import Template
from module.project_paths import project_path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROBE_PREFIX = "PROJECT_PATHS="


def _run_probe(script: str, *, cwd: Path) -> dict[str, object]:
    environment = os.environ.copy()
    inherited_pythonpath = environment.get("PYTHONPATH")
    pythonpath = [str(PROJECT_ROOT)]
    if inherited_pythonpath:
        pythonpath.append(inherited_pythonpath)
    environment["PYTHONPATH"] = os.pathsep.join(pythonpath)
    creationflags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    result = subprocess.run(  # ruff:ignore[subprocess-without-shell-equals-true] - 隔离模块导入和 cwd 状态。
        [sys.executable, "-c", script],
        check=True,
        cwd=cwd,
        env=environment,
        capture_output=True,
        text=True,
        creationflags=creationflags,
    )
    for line in result.stdout.splitlines():
        if line.startswith(PROBE_PREFIX):
            return cast("dict[str, object]", json.loads(line.removeprefix(PROBE_PREFIX)))
    message = f"project path probe did not return a payload:\n{result.stdout}\n{result.stderr}"
    raise AssertionError(message)


def test_project_owned_runtime_files_resolve_from_repo_root_without_changing_cwd(tmp_path: Path) -> None:
    script = f"""
import json
from pathlib import Path

from module.config.utils import filepath_args, filepath_config, read_file
from module.base.resource import _preserved_ui_assets
from module.base.template import Template
from module.base.utils import load_image
from module.content.manifest import DEFAULT_EVENT_MANIFEST_PATH, load_default_event_manifests
from module.content.runtime_profile_catalog import (
    DEFAULT_RUNTIME_PROFILE_PATH,
    load_default_campaign_runtime_profile_registry,
)
from module.handler.fast_forward import event_stage_ids
from module.statistics.utils import load_folder
from module.ui.assets import MAIN_GOTO_CAMPAIGN
from module.webui.utils import filepath_icon
from module.map_detection.utils_assets import UI_MASK
from module.os.globe_detection import GLOBE_MAP

starting_cwd = Path.cwd()
args_path = filepath_args()
config_path = filepath_config("template")
shop_files = load_folder("./assets/shop/os_cost")
MAIN_GOTO_CAMPAIGN.ensure_template()
template = Template("./assets/cn/ui/MAIN_GOTO_CAMPAIGN.png")
template_image = template.image
mask_image = UI_MASK.image
globe_image = load_image(GLOBE_MAP)
preserved_assets = _preserved_ui_assets()
import module.webui.app

payload = {{
    "cwd": str(Path.cwd()),
    "starting_cwd": str(starting_cwd),
    "args_path": str(args_path),
    "args_loaded": bool(read_file(args_path)),
    "config_path": str(config_path),
    "config_loaded": bool(read_file(config_path)),
    "event_path": str(DEFAULT_EVENT_MANIFEST_PATH),
    "event_count": len(load_default_event_manifests()),
    "profile_path": str(DEFAULT_RUNTIME_PROFILE_PATH),
    "profile_count": len(load_default_campaign_runtime_profile_registry().profiles),
    "button_path": str(MAIN_GOTO_CAMPAIGN.file),
    "button_loaded": MAIN_GOTO_CAMPAIGN.image is not None,
    "template_shape": list(template_image.shape),
    "mask_shape": list(mask_image.shape),
    "globe_shape": list(globe_image.shape),
    "preserved_count": len(preserved_assets),
    "event_stages": event_stage_ids("event_20210819_cn"),
    "shop_paths": list(shop_files.values()),
    "icon_path": str(filepath_icon("alas")),
}}
print({PROBE_PREFIX!r} + json.dumps(payload))
"""

    payload = _run_probe(script, cwd=tmp_path)

    assert Path(cast("str", payload["cwd"])) == tmp_path
    assert payload["starting_cwd"] == payload["cwd"]
    assert Path(cast("str", payload["args_path"])) == PROJECT_ROOT / "module" / "config" / "argument" / "args.json"
    assert payload["args_loaded"] is True
    assert Path(cast("str", payload["config_path"])) == PROJECT_ROOT / "config" / "template.json"
    assert payload["config_loaded"] is True
    assert Path(cast("str", payload["event_path"])) == PROJECT_ROOT / "content" / "events"
    assert cast("int", payload["event_count"]) > 0
    assert Path(cast("str", payload["profile_path"])) == PROJECT_ROOT / "content" / "campaign-runtime-profiles.json"
    assert cast("int", payload["profile_count"]) > 0
    assert Path(cast("str", payload["button_path"])) == PROJECT_ROOT / "assets" / "cn" / "ui" / "MAIN_GOTO_CAMPAIGN.png"
    assert payload["button_loaded"] is True
    assert cast("list[int]", payload["template_shape"])[0:2] == [720, 1280]
    assert all(dimension > 0 for dimension in cast("list[int]", payload["mask_shape"])[0:2])
    assert all(dimension > 0 for dimension in cast("list[int]", payload["globe_shape"])[0:2])
    assert cast("int", payload["preserved_count"]) > 0
    assert "d1" in cast("list[str]", payload["event_stages"])
    shop_paths = [Path(path) for path in cast("list[str]", payload["shop_paths"])]
    assert shop_paths
    assert all(path.is_relative_to(PROJECT_ROOT / "assets" / "shop" / "os_cost") for path in shop_paths)
    assert Path(cast("str", payload["icon_path"])) == PROJECT_ROOT / "assets" / "gui" / "icon" / "alas.svg"


def test_absolute_external_resource_path_is_not_rebased(tmp_path: Path) -> None:
    image_path = tmp_path / "external.png"
    Image.new("RGB", (4, 4), color=(12, 34, 56)).save(image_path)

    template = Template(image_path)
    button = Button(
        area=(0, 0, 2, 2),
        color=(12, 34, 56),
        button=(0, 0, 2, 2),
        file=image_path,
    )
    button.ensure_template()

    assert template.file == image_path
    assert np.array_equal(template.image, np.full((4, 4, 3), (12, 34, 56), dtype=np.uint8))
    assert button.file == image_path
    assert isinstance(button.image, np.ndarray)
    assert button.image.shape == (2, 2, 3)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows drive-relative path semantics")
@pytest.mark.parametrize("value", [r"C:assets\\image.png", r"\assets\image.png"])
def test_ambiguous_windows_paths_are_rejected(value: str) -> None:
    with pytest.raises(ValueError, match="absolute or project-relative"):
        project_path(value)
