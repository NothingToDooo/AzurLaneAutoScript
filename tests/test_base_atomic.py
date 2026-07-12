from __future__ import annotations

from typing import TYPE_CHECKING

from module.base.atomic import folder_rmtree

if TYPE_CHECKING:
    from pathlib import Path


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
