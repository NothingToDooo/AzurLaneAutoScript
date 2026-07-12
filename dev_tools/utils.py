import re
from os import PathLike
from pathlib import Path

from tqdm import tqdm

from dev_tools.slpp import LuaTable, LuaValue, slpp

type FilePath = str | PathLike[str]


class LuaLoader:
    """仅加载已解密的国区 Lua 脚本。"""

    server_alias = (("zh-CN", "zh-cn", "cn", "CN"),)

    def __init__(self, folder: FilePath, server: str = "zh-CN") -> None:
        self.folder = folder
        self._server = ""
        self.server = server

    @property
    def server(self) -> str:
        return self._server

    @server.setter
    def server(self, value: str) -> None:
        self._server = self.get_alias(value)

    def get_alias(self, server: str) -> str:
        for alias_list in self.server_alias:
            if server in alias_list:
                for alias in alias_list:
                    folder = Path(self.folder) / alias
                    if folder.is_dir():
                        return alias

        return server

    def filepath(self, path: FilePath) -> str:
        return (Path(self.folder) / self.server / path).as_posix()

    @staticmethod
    def _find_matching_brace(text: str, start_index: int) -> int:
        depth = 0
        in_string = None
        escape = False
        for i in range(start_index, len(text)):
            ch = text[i]
            if in_string:
                if escape:
                    escape = False
                elif ch == "\\":
                    escape = True
                elif ch == in_string:
                    in_string = None
            elif ch in ('"', "'"):
                in_string = ch
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return i
        return -1

    @staticmethod
    def _infer_base_name(file: FilePath, keyword: str | None) -> str:
        if keyword:
            keyword = keyword.strip()
            if keyword.startswith("pg.base."):
                return keyword[len("pg.base.") :]
            if keyword.startswith("pg."):
                return keyword[len("pg.") :]
            return keyword
        return Path(file).stem

    def _load_pg_base_entries(self, text: str, base_name: str) -> LuaTable:
        pattern = rf"pg\.base\.{re.escape(base_name)}\[(\d+)\]\s*=\s*\{{"
        result: LuaTable = {}
        for m in re.finditer(pattern, text):
            start = m.end() - 1
            end = self._find_matching_brace(text, start)
            if end == -1:
                continue
            table_text = text[start : end + 1]
            result[int(m.group(1))] = slpp.decode_table(table_text)
        return result

    def _load_file(self, file: FilePath, keyword: str | None = None) -> LuaTable:
        text = Path(self.filepath(file)).read_text(encoding="utf-8")

        if "pg.base." in text:
            base_name = self._infer_base_name(file, keyword)
            if not base_name:
                m = re.search(r"pg\.base\.([A-Za-z0-9_]+)\[", text)
                base_name = m.group(1) if m else None
            if base_name:
                result = self._load_pg_base_entries(text, base_name)
                if result:
                    return result

        result: LuaTable = {}
        if text.startswith("_G"):
            text = "{" + text + "}"
            result = slpp.decode_table(text)
        else:
            if keyword:
                print(f"Finding keyword: {keyword}")
                pattern = rf"^{re.escape(keyword)}.*?\{{\s*\n(.*?)^\}}"
            else:
                pattern = r"\{\s*\n(.*?)^\}"
            m = re.search(pattern, text, re.DOTALL | re.MULTILINE)
            if m:
                result = slpp.decode_table("{" + m.group(1) + "}")
        return result

    def load(self, path: FilePath, keyword: str | None = None) -> LuaTable:
        """读取相对 `{folder}/{server}` 的 Lua 文件或目录，并返回合并后的字典。"""
        print(f"Loading {path}")
        if Path(self.filepath(path)).is_dir():
            result: LuaTable = {}
            for file in tqdm(Path(self.filepath(path)).iterdir()):
                result.update(self._load_file(f"./{path}/{file.name}", keyword=keyword))
        else:
            result = self._load_file(path, keyword=keyword)

        print(f"{len(result.keys())} items loaded")
        return result


def require_lua_table(value: LuaValue, *, context: str) -> LuaTable:
    if not isinstance(value, dict):
        message = f"{context} must be a Lua table"
        raise TypeError(message)
    return value


def require_lua_int(value: LuaValue, *, context: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        message = f"{context} must be an integer"
        raise TypeError(message)
    return value


def require_lua_str(value: LuaValue, *, context: str) -> str:
    if not isinstance(value, str):
        message = f"{context} must be a string"
        raise TypeError(message)
    return value


if __name__ == "__main__":
    lua = LuaLoader(r"xxx/AzurLaneData", server="zh-CN")
    res = lua.load("./sharecfg/item_data_statistics.lua")
