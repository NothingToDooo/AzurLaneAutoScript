import json
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from module.config.config_updater import build_template
from module.config.configuration_file import iter_config_save_updates, read_config_file, write_config_file

if TYPE_CHECKING:
    import pytest


def test_build_template_matches_checked_in_current_template(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    expected = json.loads(Path("config/template.json").read_text(encoding="utf-8"))
    generated = build_template()
    (tmp_path / "config").mkdir()
    monkeypatch.chdir(tmp_path)

    write_config_file("template", generated)

    actual = json.loads((tmp_path / "config" / "template.json").read_text(encoding="utf-8"))
    assert actual == expected


def test_read_file_returns_current_document_without_migration(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    document = {"UnknownLegacyField": {"Value": 1}}
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "alas.json").write_text(json.dumps(document), encoding="utf-8")
    monkeypatch.chdir(tmp_path)

    assert read_config_file("alas") == document


def test_emotion_value_save_updates_its_record_timestamp() -> None:
    updates = list(iter_config_save_updates("Main.Emotion.Fleet1Value"))

    assert len(updates) == 1
    path, timestamp = updates[0]
    assert path == "Main.Emotion.Fleet1Record"
    assert isinstance(timestamp, str)
    assert datetime.fromisoformat(timestamp).tzinfo is None
    assert list(iter_config_save_updates("Main.Campaign.Name")) == []
