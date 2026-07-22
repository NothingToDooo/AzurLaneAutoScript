from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from os import PathLike

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def project_path(path: str | PathLike[str]) -> Path:
    """把仓库内相对路径锚定到唯一项目根；绝对外部路径保持不变。"""

    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    if candidate.drive or candidate.root:
        message = f"project path must be absolute or project-relative: {candidate}"
        raise ValueError(message)
    return PROJECT_ROOT / candidate
