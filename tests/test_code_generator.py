from __future__ import annotations

from typing import TYPE_CHECKING

from module.config.code_generator import CodeGenerator

if TYPE_CHECKING:
    from pathlib import Path


def test_code_generator_write_preserves_exact_line_endings(tmp_path: Path) -> None:
    output = tmp_path / "generated.py"
    generator = CodeGenerator()
    generator.add("first")
    generator.add("last", newline=False)

    assert generator.write(output.as_posix()) is None
    assert output.read_bytes() == b"first\nlast"
