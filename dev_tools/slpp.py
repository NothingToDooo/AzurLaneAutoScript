import re
from contextlib import suppress
from numbers import Number
from typing import ClassVar

# 来源：https://github.com/LmeSzinc/slpp，原项目：https://github.com/SirAnthony/slpp。
# 稀疏数字键表保持为字典，避免错误压缩为列表。


ERRORS = {
    "unexp_end_string": "Unexpected end of string while parsing Lua string.",
    "unexp_end_table": "Unexpected end of table while parsing Lua string.",
    "mfnumber_minus": "Malformed number (no digits after initial minus).",
    "mfnumber_dec_point": "Malformed number (no digits after decimal point).",
    "mfnumber_sci": "Malformed number (bad scientific format).",
}
type LuaScalar = str | int | float | bool | None
type LuaKey = str | int | float | bool
type LuaValue = LuaScalar | list[LuaValue] | LuaTable
type LuaTable = dict[LuaKey, LuaValue]
type LuaEncodable = LuaScalar | bytes | list[LuaEncodable] | tuple[LuaEncodable, ...] | dict[LuaKey, LuaEncodable]


class ParseError(Exception):
    pass


class SLPP:
    def __init__(self) -> None:
        self.text = ""
        self.ch: str | None = ""
        self.at = 0
        self.len = 0
        self.depth = 0
        self.space = re.compile(r"\s", re.MULTILINE)
        self.alnum = re.compile(r"\w", re.MULTILINE)
        self.newline = "\n"
        self.tab = "\t"

    def decode(self, text: str) -> LuaValue:
        if not text:
            return None
        # 不能用正则删除 Lua 注释，字符串中的连续短横线会被误伤。
        self.text = text
        self.at, self.ch, self.depth = 0, "", 0
        self.len = len(text)
        self.next_chr()
        return self.value()

    def decode_table(self, text: str) -> LuaTable:
        value = self.decode(text)
        if not isinstance(value, dict):
            message = "Expected a Lua table."
            raise ParseError(message)
        return value

    def encode(self, obj: LuaEncodable) -> str:
        self.depth = 0
        return self.__encode(obj)

    def __encode(self, obj: LuaEncodable) -> str:
        s = ""
        tab = self.tab
        newline = self.newline

        if isinstance(obj, str):
            escaped = obj.replace(r'"', r"\"")
            s += f'"{escaped}"'
        elif isinstance(obj, bytes):
            escaped = "".join(rf"\x{c:02x}" for c in obj)
            s += f'"{escaped}"'
        elif isinstance(obj, bool):
            s += str(obj).lower()
        elif obj is None:
            s += "nil"
        elif isinstance(obj, Number):
            s += str(obj)
        elif isinstance(obj, (list, tuple, dict)):
            self.depth += 1
            if len(obj) == 0 or (
                not isinstance(obj, dict)
                and len([x for x in obj if isinstance(x, Number) or (isinstance(x, str) and len(x) < 10)]) == len(obj)
            ):
                newline = tab = ""
            dp = tab * self.depth
            s += f"{tab * (self.depth - 2)}{{{newline}"
            separator = f",{newline}"
            if isinstance(obj, dict):
                if all(isinstance(k, int) for k in obj):
                    contents = [f"{dp}[{k}] = {self.__encode(v)}" for k, v in obj.items()]
                else:
                    contents = [f"{dp}{k} = {self.__encode(v)}" for k, v in obj.items()]
                s += separator.join(contents)
            else:
                s += separator.join([dp + self.__encode(el) for el in obj])
            self.depth -= 1
            s += f"{newline}{tab * self.depth}}}"
        return s

    def white(self) -> None:
        while self.ch:
            if self.space.match(self.ch):
                self.next_chr()
            else:
                break

    def next_chr(self) -> bool | None:
        if self.at >= self.len:
            self.ch = None
            return None
        self.ch = self.text[self.at]
        self.at += 1
        return True

    def value(self) -> LuaValue:
        self.white()
        if not self.ch:
            return None
        if self.ch == "{":
            return self.object()
        if self.ch == "[":
            self.next_chr()
        if self.ch in ['"', "'", "["]:
            return self.string(self.ch)
        if self.ch.isdigit() or self.ch == "-":
            return self.number()
        return self.word()

    def string(self, end: str | None = None) -> str:
        s = ""
        start = self.ch
        if end == "[":
            end = "]"
        if start in ['"', "'", "["]:
            while self.next_chr():
                if self.ch == end:
                    self.next_chr()
                    if start != "[" or self.ch == "]":
                        return s
                if self.ch == "\\" and start == end:
                    self.next_chr()
                    if self.ch is None:
                        break
                    if self.ch != end:
                        s += "\\"
                if self.ch is None:
                    break
                s += self.ch
        raise ParseError(ERRORS["unexp_end_string"])

    def _consume_empty_object(self) -> bool:
        if self.ch != "}":
            return False
        self.depth -= 1
        self.next_chr()
        return True

    def _close_object(self, data: LuaTable, pending_key: LuaValue, index: int) -> LuaTable:
        self.depth -= 1
        self.next_chr()
        if pending_key is not None:
            data[index] = pending_key
        return data

    def _read_object_item(self, data: LuaTable, index: int) -> tuple[LuaValue, int]:
        key = self.value()
        if self.ch == "]":
            self.next_chr()
        self.white()

        separator = self.ch
        if separator not in ("=", ","):
            return key, index

        self.next_chr()
        self.white()
        if separator == "=":
            if not isinstance(key, (str, int, float, bool)):
                message = "Lua table keys must be scalar values."
                raise ParseError(message)
            data[key] = self.value()
        else:
            data[index] = key
        return None, index + 1

    def object(self) -> LuaTable:
        data: LuaTable = {}
        pending_key: LuaValue = None
        index = 0
        self.depth += 1
        self.next_chr()
        self.white()
        if self._consume_empty_object():
            return data
        while self.ch:
            self.white()
            if self.ch == "{":
                data[index] = self.object()
                index += 1
                continue
            if self.ch == "}":
                return self._close_object(data, pending_key, index)
            if self.ch == ",":
                self.next_chr()
                continue
            pending_key, index = self._read_object_item(data, index)
        raise ParseError(ERRORS["unexp_end_table"])

    words: ClassVar[dict[str, LuaScalar]] = {"true": True, "false": False, "nil": None}

    def word(self) -> LuaScalar:
        s = ""
        ch = self.ch
        if ch is None:
            return s
        if ch != "\n":
            s = ch
        self.next_chr()
        while True:
            ch = self.ch
            if ch is None or not self.alnum.match(ch) or s in self.words:
                break
            s += ch
            self.next_chr()
        return self.words.get(s, s)

    def _next_number_token(self, error: str) -> str:
        token = self.ch or ""
        self.next_chr()
        if not token or not self.ch or not self.ch.isdigit():
            raise ParseError(error)
        return token

    def _number_text(self) -> str:
        n = ""
        if self.ch == "-":
            n += self._next_number_token(ERRORS["mfnumber_minus"])
        n += self.digit()
        if n == "0" and self.ch in ["x", "X"]:
            n += self.ch
            self.next_chr()
            return n + self.hex()
        if self.ch == ".":
            n += self._next_number_token(ERRORS["mfnumber_dec_point"])
            n += self.digit()
        if self.ch in ["e", "E"]:
            n += self.ch
            self.next_chr()
            if self.ch not in ("+", "-"):
                raise ParseError(ERRORS["mfnumber_sci"])
            n += self._next_number_token(ERRORS["mfnumber_sci"])
            n += self.digit()
        return n

    def number(self) -> int | float:
        n = self._number_text()
        with suppress(ValueError):
            return int(n, 0)
        return float(n)

    def digit(self) -> str:
        n = ""
        while self.ch and self.ch.isdigit():
            n += self.ch
            self.next_chr()
        return n

    def hex(self) -> str:
        n = ""
        while self.ch and (self.ch in "ABCDEFabcdef" or self.ch.isdigit()):
            n += self.ch
            self.next_chr()
        return n


slpp = SLPP()
