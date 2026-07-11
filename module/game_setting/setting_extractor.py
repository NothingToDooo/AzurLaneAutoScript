import os
import re
import textwrap
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from tqdm import tqdm

from module.base.decorator import cached_property

if TYPE_CHECKING:
    from collections.abc import Iterator

REGEX_SETTING = re.compile(r"PlayerPrefs.Get(\w{1,10})\((.*)\)")
REGEX_SETTING_KEY = re.compile(r'"(.*?)"')


def _comment_lines(text: str) -> list[str]:
    return [
        f"# 来源：{line}" for line in textwrap.wrap(text, width=108, break_long_words=False, break_on_hyphens=False)
    ]


def _strip_code(string: str) -> Iterator[str]:
    nested = 0
    for word in string:
        if word == "(":
            nested += 1
        if word == ")":
            if nested == 1:
                yield word
                return
            nested -= 1
        yield word


def strip_code(string: str) -> str:
    return "".join(list(_strip_code(string)))


@dataclass
class Field:
    formatter: type[int | float | str]
    default: int | float | str | None
    regex: str


_LUA_TYPE_DEFAULTS = {
    "Int": 0,
    "String": repr(""),
    "Float": 0.0,
}


def _parse_lua_int_default(value: str) -> int:
    try:
        return int(value)
    except ValueError:
        return 0


def _parse_lua_float_default(value: str) -> float:
    try:
        return float(value)
    except ValueError:
        return 0.0


def _parse_lua_default(typ: str, value: str) -> int | float | str | None:
    if typ == "Int":
        return _parse_lua_int_default(value)
    if typ == "String":
        return repr(value)
    if typ == "Float":
        return _parse_lua_float_default(value)
    return None


@dataclass
class LuaSetting:
    raw: str
    # Lua 类型仅接受 Int、String 或 Float。
    typ: str
    # 形如 `AUTOFIGHT_BATTERY_SAVEMODE, 0` 或 `world_help_progress`。
    code: str
    duplicate: bool = False

    @cached_property
    def setting_code(self) -> str:
        return self.code.rsplit(",", 1)[0].strip(" ") if "," in self.code else self.code.strip(" ")

    @cached_property
    def default(self) -> int | float | str | None:
        if "," not in self.code:
            return _LUA_TYPE_DEFAULTS.get(self.typ)

        _name, default = self.code.split(",", 1)
        return _parse_lua_default(self.typ, default.strip(' ",'))

    @cached_property
    def key(self) -> str:
        # 形如 `"autoBotIsAcitve" .. AutoBotCommand.GetAutoBotMark(slot0)` 或 `"world_help_progress"`。
        res = REGEX_SETTING_KEY.search(self.setting_code)
        if res:
            return res.group(1).replace(".", "_").replace("%", "_").replace("-", "_").replace(":", "_").strip("_")
        return ""

    @cached_property
    def formatter(self) -> str:
        if self.typ == "Int":
            return "int"
        if self.typ == "String":
            return "str"
        if self.typ == "Float":
            return "float"
        return "str"

    @cached_property
    def regex(self) -> str:
        pieces = self.setting_code.split("..")

        def iter_piece() -> Iterator[str]:
            for piece in pieces:
                res = REGEX_SETTING_KEY.search(piece)
                if res:
                    yield res.group(1)
                else:
                    yield "(.*)"

        return repr("".join(list(iter_piece())))

    @cached_property
    def generated(self) -> list[str]:
        if self.key == "":
            return [*_comment_lines(self.raw), "# 未识别"]
        if self.duplicate:
            return [*_comment_lines(self.raw), "# 重复项"]

        return [
            *_comment_lines(self.raw),
            f"{self.key} = Field(formatter={self.formatter}, default={self.default}, regex={self.regex})",
        ]


class SettingExtractor:
    @staticmethod
    def iter_setting_from_file(file: str | Path) -> Iterator[LuaSetting]:
        with Path(file).open(encoding="utf8") as f:
            data = list(f.readlines())

        for raw_row in data:
            row = raw_row.strip()
            res = REGEX_SETTING.search(row)
            if res:
                row = strip_code(res.group(0))
                res = REGEX_SETTING.search(row)
                if res:
                    yield LuaSetting(raw=row, typ=res.group(1), code=res.group(2))

    @staticmethod
    def iter_file_from_folder(folder: str) -> Iterator[str]:
        for path, _folders, files in os.walk(folder):
            for filename in files:
                yield f"{path}/{filename}"

    def iter_generated_lines(self, folder: str) -> Iterator[str]:
        dic_settings: set[str] = set()
        yield "from module.game_setting.setting_extractor import Field"
        yield ""
        yield "# 本文件由 module/game_setting/setting_extractor.py 自动生成。"
        yield "# 不要手动修改。"
        yield ""
        yield ""
        yield "class GameSettingsGenerated:"
        files = list(self.iter_file_from_folder(folder))
        for file in tqdm(files):
            settings = list(self.iter_setting_from_file(file))
            if not settings:
                continue
            yield ""
            f = file.removeprefix(folder).replace("\\", "/")
            yield f"    # {f}"
            for setting in settings:
                if setting.key in dic_settings:
                    setting.duplicate = True
                dic_settings.add(setting.key)
                for line in setting.generated:
                    yield f"    {line}"

    def generate(self, folder: str, output: str | Path = "./module/game_setting/setting_generated.py") -> None:
        lines = [line + "\n" for line in self.iter_generated_lines(folder)]
        with Path(output).open(mode="w", encoding="utf8") as f:
            f.writelines(lines)


if __name__ == "__main__":
    # AzurLaneLuaScripts\CN 的路径。
    FOLDER = r""
    ex = SettingExtractor()
    ex.generate(FOLDER)
