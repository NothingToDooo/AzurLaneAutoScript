from typing import TYPE_CHECKING

import pytest

from module.bootstrap.revisions import RevisionTree, SourceTreeRevisionSource

if TYPE_CHECKING:
    from pathlib import Path


def _source(root: Path) -> SourceTreeRevisionSource:
    return SourceTreeRevisionSource(
        "content",
        (RevisionTree(root, frozenset({".py", ".yaml"})),),
    )


def test_source_tree_revision_is_stable_and_changes_with_path_or_content(tmp_path: Path) -> None:
    root = tmp_path / "content"
    root.mkdir()
    stage = root / "stage.yaml"
    stage.write_text("stage: one\n", encoding="utf-8")
    ignored = root / "notes.md"
    ignored.write_text("ignored", encoding="utf-8")

    original = _source(root).current()
    assert _source(root).current() == original
    assert original.startswith("content-sha256:")

    ignored.write_text("still ignored", encoding="utf-8")
    assert _source(root).current() == original

    stage.write_text("stage: two\n", encoding="utf-8")
    changed_content = _source(root).current()
    assert changed_content != original

    stage.rename(root / "renamed.yaml")
    assert _source(root).current() != changed_content


def test_source_tree_revision_rejects_empty_matching_file_set(tmp_path: Path) -> None:
    root = tmp_path / "empty"
    root.mkdir()
    with pytest.raises(ValueError, match="at least one matching file"):
        _source(root).current()
