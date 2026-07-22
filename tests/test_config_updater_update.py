import json
from datetime import datetime
from typing import TYPE_CHECKING

import module.config.configuration_file as configuration_file_module
from module.config.config_updater import build_template
from module.config.configuration_file import iter_config_save_updates, read_config_file, write_config_file
from module.project_paths import PROJECT_ROOT

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_build_template_matches_checked_in_current_template(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = json.loads((PROJECT_ROOT / "config" / "template.json").read_text(encoding="utf-8"))
    generated = build_template()
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    monkeypatch.setattr(configuration_file_module, "filepath_config", lambda name: config_dir / f"{name}.json")

    write_config_file("template", generated)

    actual = json.loads((config_dir / "template.json").read_text(encoding="utf-8"))
    assert actual == expected


def test_read_file_returns_current_document_without_migration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = {"UnknownLegacyField": {"Value": 1}}
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "alas.json").write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.setattr(configuration_file_module, "filepath_config", lambda name: config_dir / f"{name}.json")

    assert read_config_file("alas") == document


def test_emotion_value_save_updates_its_record_timestamp() -> None:
    updates = list(iter_config_save_updates("Main.Emotion.Fleet1Value"))

    assert len(updates) == 1
    path, timestamp = updates[0]
    assert path == "Main.Emotion.Fleet1Record"
    assert isinstance(timestamp, str)
    assert datetime.fromisoformat(timestamp).tzinfo is None
    assert list(iter_config_save_updates("Main.Campaign.Name")) == []
