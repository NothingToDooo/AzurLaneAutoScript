import hashlib
from dataclasses import dataclass
from pathlib import Path


def _require_revision_namespace(value: str) -> None:
    if not isinstance(value, str):
        message = "namespace must be a string"
        raise TypeError(message)
    if not value or value != value.strip() or any(character.isspace() for character in value):
        message = "namespace must be trimmed, non-empty, and contain no whitespace"
        raise ValueError(message)


@dataclass(frozen=True, slots=True)
class RevisionTree:
    root: Path
    suffixes: frozenset[str]

    def __post_init__(self) -> None:
        if not isinstance(self.root, Path):
            message = "root must be a Path"
            raise TypeError(message)
        if not isinstance(self.suffixes, frozenset) or not self.suffixes:
            message = "suffixes must be a non-empty frozenset"
            raise TypeError(message)
        if any(
            not isinstance(suffix, str)
            or not suffix.startswith(".")
            or suffix != suffix.lower()
            or suffix != suffix.strip()
            for suffix in self.suffixes
        ):
            message = "suffixes must contain normalized lowercase file suffixes"
            raise ValueError(message)


class SourceTreeRevisionSource:
    """以相对路径与文件内容计算可复现的 content/client profile revision。"""

    __slots__ = ("_namespace", "_trees")

    def __init__(self, namespace: str, trees: tuple[RevisionTree, ...]) -> None:
        _require_revision_namespace(namespace)
        if not isinstance(trees, tuple) or not trees:
            message = "trees must be a non-empty tuple"
            raise TypeError(message)
        if any(not isinstance(tree, RevisionTree) for tree in trees):
            message = "trees must contain only RevisionTree values"
            raise TypeError(message)
        roots = tuple(tree.root.resolve() for tree in trees)
        if len(roots) != len(set(roots)):
            message = "revision tree roots must not repeat"
            raise ValueError(message)
        self._namespace = namespace
        self._trees = trees

    def current(self) -> str:
        digest = hashlib.sha256()
        file_count = 0
        for tree_index, tree in enumerate(self._trees):
            root = tree.root.resolve(strict=True)
            if not root.is_dir():
                message = f"revision tree root must be a directory: {root}"
                raise NotADirectoryError(message)
            paths = sorted(
                (path for path in root.rglob("*") if path.is_file() and path.suffix.lower() in tree.suffixes),
                key=lambda path: path.relative_to(root).as_posix(),
            )
            for path in paths:
                resolved = path.resolve(strict=True)
                try:
                    relative = resolved.relative_to(root).as_posix()
                except ValueError as error:
                    message = f"revision file must stay inside its root: {path}"
                    raise ValueError(message) from error
                content = resolved.read_bytes()
                identity = f"{tree_index}:{relative}".encode()
                digest.update(len(identity).to_bytes(8, "big"))
                digest.update(identity)
                digest.update(len(content).to_bytes(8, "big"))
                digest.update(content)
                file_count += 1
        if file_count == 0:
            message = "revision source must contain at least one matching file"
            raise ValueError(message)
        return f"{self._namespace}-sha256:{digest.hexdigest()}"
