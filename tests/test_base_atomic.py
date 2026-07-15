from pathlib import Path

import pytest

from module.base.atomic import atomic_failure_cleanup, atomic_write, folder_rmtree, is_tmp_file


@pytest.mark.parametrize(
    "filename",
    [
        "reportABC123.tmp",
        "state.json-ABC123.tmp",
        "state.json.ＡＢＣ１２３.tmp",
        "state.json.ABC12.tmp",
        "state.json.ABC123.tmp.bak",
    ],
)
def test_is_tmp_file_rejects_similar_names(filename: str) -> None:
    assert not is_tmp_file(filename)


def test_is_tmp_file_accepts_atomic_suffix() -> None:
    assert is_tmp_file("state.json.ABC123.tmp")


def test_atomic_failure_cleanup_does_not_remove_similar_user_file(tmp_path: Path) -> None:
    folder = tmp_path / "config"
    folder.mkdir()
    user_file = folder / "reportABC123.tmp"
    atomic_temp = folder / "alas.json.ABC123.tmp"
    user_file.write_text("keep", encoding="utf-8")
    atomic_temp.write_text("discard", encoding="utf-8")

    atomic_failure_cleanup(folder)

    assert user_file.read_text(encoding="utf-8") == "keep"
    assert not atomic_temp.exists()


def test_atomic_failure_cleanup_does_not_remove_root_file(tmp_path: Path) -> None:
    root_file = tmp_path / "config"
    root_file.write_text("keep", encoding="utf-8")

    atomic_failure_cleanup(root_file)

    assert root_file.read_text(encoding="utf-8") == "keep"


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
