from typing import TYPE_CHECKING

import pytest
import yaml

from module.content.errors import ContentValidationError
from module.content.yaml_loader import load_strict_yaml_mapping

if TYPE_CHECKING:
    from pathlib import Path


def test_strict_yaml_loader_wraps_file_read_errors(tmp_path: Path) -> None:
    path = tmp_path / "missing.yaml"

    with pytest.raises(ContentValidationError) as caught:
        load_strict_yaml_mapping(path)

    assert str(caught.value).startswith(f"{path}:$: ")
    assert isinstance(caught.value.__cause__, FileNotFoundError)


def test_strict_yaml_loader_is_disposed_after_success_and_parse_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    disposed: list[yaml.SafeLoader] = []
    original_dispose = yaml.SafeLoader.dispose

    def tracked_dispose(loader: yaml.SafeLoader) -> None:
        disposed.append(loader)
        original_dispose(loader)

    monkeypatch.setattr(yaml.SafeLoader, "dispose", tracked_dispose)
    valid_path = tmp_path / "valid.yaml"
    valid_path.write_text("root: value\n", encoding="utf-8")
    invalid_path = tmp_path / "invalid.yaml"
    invalid_path.write_text("root: [\n", encoding="utf-8")

    assert load_strict_yaml_mapping(valid_path) == {"root": "value"}
    with pytest.raises(ContentValidationError):
        load_strict_yaml_mapping(invalid_path)

    assert len(disposed) == 2
