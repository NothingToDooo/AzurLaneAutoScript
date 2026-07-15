from pathlib import Path

import pytest

from module.base.atomic import atomic_write, folder_rmtree


def test_folder_rmtree_removes_nested_directory(tmp_path: Path) -> None:
    root = tmp_path / "root"
    child = root / "child"
    child.mkdir(parents=True)
    (child / "file.txt").write_text("content", encoding="utf-8")

    assert folder_rmtree(root)
    assert not root.exists()


def test_folder_rmtree_treats_missing_path_as_removed(tmp_path: Path) -> None:
    assert folder_rmtree(tmp_path / "missing")


def test_folder_rmtree_removes_file_path(tmp_path: Path) -> None:
    file = tmp_path / "file.txt"
    file.write_text("content", encoding="utf-8")

    assert folder_rmtree(file)
    assert not file.exists()


def test_atomic_write_preserves_destination_when_replace_fails(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    destination = tmp_path / "state.json"
    destination.write_text("old", encoding="utf-8")
    replace_error = OSError("replace failed")
    written_temps: list[Path] = []

    def fail_replace(temp: Path, target: str | Path) -> None:
        written_temps.append(temp)
        assert temp.read_text(encoding="utf-8") == "new"
        assert Path(target).read_text(encoding="utf-8") == "old"
        raise replace_error

    monkeypatch.setattr(Path, "replace", fail_replace)

    with pytest.raises(OSError, match="replace failed") as raised:
        atomic_write(destination, "new")

    assert raised.value is replace_error
    assert destination.read_text(encoding="utf-8") == "old"
    assert len(written_temps) == 1
    assert not written_temps[0].exists()
