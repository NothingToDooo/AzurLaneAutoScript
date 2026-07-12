from pathlib import Path
from typing import TYPE_CHECKING, NotRequired, TypedDict

import module.logger
from dev_tools.utils import LuaLoader, require_lua_int, require_lua_str, require_lua_table
from module.base.utils import location2node
from module.os.map_data import DIC_OS_MAP

if TYPE_CHECKING:
    from dev_tools.slpp import LuaTable
    from module.base.type_alias import FilePath

# 导入 module.logger 会切换到项目根目录。
_ = module.logger


class OSChapterData(TypedDict):
    shape: NotRequired[str]
    hazard_level: int
    cn: str
    area_pos: NotRequired[tuple[int, int]]
    offset_pos: NotRequired[tuple[int, int]]
    region: NotRequired[int]


class OSMapPosition(TypedDict):
    area_pos: tuple[int, int]
    offset_pos: tuple[int, int]
    region: int


class OSChapter:
    def __init__(self) -> None:
        self.chapter: dict[int, OSChapterData] = {}
        data = LOADER.load("sharecfg/world_chapter_random.lua")
        for index, chapter_value in data.items():
            if not isinstance(index, int) or index >= 200:
                continue
            chapter = require_lua_table(chapter_value, context=f"world chapter {index}")
            self.chapter[index] = {
                "cn": require_lua_str(chapter["name"], context=f"world chapter {index} name"),
                "hazard_level": require_lua_int(chapter["hazard_level"], context=f"world chapter {index} hazard level"),
            }

        for index, name in self.extract_chapter_name("zh-CN").items():
            self.chapter[index]["cn"] = name
        for index, shape in self.extract_map_size().items():
            self.chapter[index]["shape"] = shape
        new: dict[int, OSChapterData] = {}
        for index, chapter in self.chapter.items():
            fallback_shape = DIC_OS_MAP[index]["shape"]
            if not isinstance(fallback_shape, str):
                message = f"DIC_OS_MAP[{index}].shape must be a string"
                raise TypeError(message)
            new[index] = {
                # world_chapter_template.lua 结构变过，缺失尺寸时沿用旧地图数据。
                "shape": chapter.get("shape", fallback_shape),
                "hazard_level": chapter["hazard_level"],
                "cn": chapter["cn"],
            }
        self.chapter = new

        for index, data in self.extract_map_position().items():
            self.chapter[index].update(data)

    @staticmethod
    def extract_chapter_name(server: str) -> dict[int, str]:
        LOADER.server = server
        data = LOADER.load("sharecfg/world_chapter_random.lua")
        out: dict[int, str] = {}
        for index, chapter_value in data.items():
            if not isinstance(index, int) or index >= 200:
                continue
            chapter = require_lua_table(chapter_value, context=f"world chapter {index}")
            name = require_lua_str(chapter["name"], context=f"world chapter {index} name")
            name = name.replace("é", "e")  # OCR 识别不了字母 "é"。
            out[index] = name

        # Zone 40000 is zone 154
        for index, chapter_value in data.items():
            if index == 40000:
                chapter = require_lua_table(chapter_value, context="world chapter 40000")
                name = require_lua_str(chapter["name"], context="world chapter 40000 name")
                print(server, name)
                out[154] = name

        return out

    def extract_map_size(self, server: str = "zh-CN") -> dict[int, str]:
        LOADER.server = server
        data = LOADER.load("sharecfgdata/world_chapter_template.lua")
        out: dict[int, str] = {}
        for full_index, chapter_value in data.items():
            if not isinstance(full_index, int):
                continue
            chapter = require_lua_table(chapter_value, context=f"world chapter template {full_index}")
            if full_index // 1000000 != 1 or not chapter["map_sight"]:
                continue
            index = (full_index % 1000000) // 1000
            if index < 10:
                index -= 1
            grids = require_lua_table(chapter["grids"], context=f"world chapter template {full_index} grids")
            shape = self.parse_map_data(grids)
            out[index] = location2node(shape)

        return out

    @staticmethod
    def parse_map_data(grids: LuaTable) -> tuple[int, int]:
        coordinates = [require_lua_table(grid, context="world map grid") for grid in grids.values()]
        y = [require_lua_int(grid[0], context="world map grid y") for grid in coordinates]
        x = [require_lua_int(grid[1], context="world map grid x") for grid in coordinates]
        return (max(x) - min(x), max(y) - min(y))

    @staticmethod
    def extract_map_position(server: str = "zh-CN") -> dict[int, OSMapPosition]:
        LOADER.server = server
        data = LOADER.load("sharecfg/world_chapter_colormask.lua")
        out: dict[int, OSMapPosition] = {}
        for chapter_value in data.values():
            chapter = require_lua_table(chapter_value, context="world chapter color mask")
            if "serial_number" not in chapter:
                continue
            index = require_lua_int(chapter["serial_number"], context="world chapter serial number")
            if index < 10:
                index -= 1

            area = require_lua_table(chapter["area_pos"], context=f"world chapter {index} area position")
            offset = require_lua_table(chapter["offset_pos"], context=f"world chapter {index} offset position")
            out[index] = {
                "area_pos": (
                    require_lua_int(area[0], context=f"world chapter {index} area x"),
                    require_lua_int(area[1], context=f"world chapter {index} area y"),
                ),
                "offset_pos": (
                    require_lua_int(offset[0], context=f"world chapter {index} offset x"),
                    require_lua_int(offset[1], context=f"world chapter {index} offset y"),
                ),
                "region": require_lua_int(chapter["regions"], context=f"world chapter {index} region"),
            }

        return out

    def encode(self) -> list[str]:
        lines = [
            "# This file was automatically generated by dev_tools/os_extract.py.",
            "# Don't modify it manually.",
            "",
            "DIC_OS_MAP = {",
        ]
        for index, chapter in self.chapter.items():
            lines.append(f"    {index}: {chapter!s},")
        lines.append("}")
        return lines

    def write(self, file: FilePath) -> None:
        print(f"writing {file}")
        with Path(file).open("w", encoding="utf-8") as f:
            f.writelines(f"{text}\n" for text in self.encode())


"""
这是用于抽取大型作战地图数据的开发工具。

先克隆 https://github.com/AzurLaneTools/AzurLaneLuaScripts 获取解密后的 Lua 脚本。
Arguments:
    FILE: Lua 脚本仓库路径，例如 'xxx/AzurLaneLuaScripts'
    SAVE: 保存目标，例如 'module/os/map_data.py'
"""
FOLDER = ""
SAVE = "module/os/map_data.py"

LOADER = LuaLoader(FOLDER)


def main() -> None:
    OSChapter().write(SAVE)


if __name__ == "__main__":
    main()
