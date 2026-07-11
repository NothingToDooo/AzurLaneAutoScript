from typing import TYPE_CHECKING

import pytest

from dev_tools.utils import LuaLoader

if TYPE_CHECKING:
    from pathlib import Path


def test_lua_loader_reads_utf8_file(tmp_path: Path) -> None:
    folder = tmp_path / "zh-CN" / "sharecfg"
    folder.mkdir(parents=True)
    (folder / "items.lua").write_text('{\n[1] = {name = "测试"},\n}\n', encoding="utf-8")
    loader = LuaLoader(tmp_path)

    assert loader.load("sharecfg/items.lua") == {1: {"name": "测试"}}


def test_lua_loader_preserves_missing_file_error(tmp_path: Path) -> None:
    loader = LuaLoader(tmp_path)

    with pytest.raises(FileNotFoundError):
        loader.load("missing.lua")
