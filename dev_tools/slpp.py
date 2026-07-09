import re
from contextlib import suppress
from numbers import Number
from typing import Any, ClassVar

"""
SLPP is a simple lua-python data structures parser.

This is my fork of SLPP, https://github.com/LmeSzinc/slpp
Origin repository here, https://github.com/SirAnthony/slpp

I found some error in it
lua example: '{点={2={0={叫={醒={我={this=true}}}}}}}'
wrong result: {'点': {2: [{'叫': {'醒': {'我': {'this': True}}}}]}}
fixed result: {'点': {2: {0: {'叫': {'醒': {'我': {'this': True}}}}}}}

They seems to treat this as a feature not a bug, https://github.com/SirAnthony/slpp/issues/21
So I made my own fork for Alas.
"""


ERRORS = {
    "unexp_end_string": "Unexpected end of string while parsing Lua string.",
    "unexp_end_table": "Unexpected end of table while parsing Lua string.",
    "mfnumber_minus": "Malformed number (no digits after initial minus).",
    "mfnumber_dec_point": "Malformed number (no digits after decimal point).",
    "mfnumber_sci": "Malformed number (bad scientific format).",
}
SORTABLE_KEY_TYPES = (str, int, float, bool, tuple)


def sequential(lst):
    return bool(lst) and lst == list(range(len(lst)))


class ParseError(Exception):
    pass


class SLPP:
    def __init__(self):
        self.text = ""
        self.ch: str | None = ""
        self.at = 0
        self.len = 0
        self.depth = 0
        self.space = re.compile(r"\s", re.MULTILINE)
        self.alnum = re.compile(r"\w", re.MULTILINE)
        self.newline = "\n"
        self.tab = "\t"

    def decode(self, text):
        if not text or not isinstance(text, str):
            return None
        # 游戏脚本没有注释。
        # 删除注释可能导致错误，例如下面这类内容会被误认为注释：
        # `profiles = "现世与梦境夹缝中的蝴蝶，狂风与巨浪蹂躏中的小舟。`
        # `跨越虚无，驱散黑暗，为重樱带来希望和未来吧---------- ",`
        # 早期尝试用 "--.*$" 正则删注释，后来确认会误伤包含长破折号的文本。
        self.text = text
        self.at, self.ch, self.depth = 0, "", 0
        self.len = len(text)
        self.next_chr()
        return self.value()

    def encode(self, obj):
        self.depth = 0
        return self.__encode(obj)

    def __encode(self, obj):
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

    def white(self):
        while self.ch:
            if self.space.match(self.ch):
                self.next_chr()
            else:
                break

    def next_chr(self):
        if self.at >= self.len:
            self.ch = None
            return None
        self.ch = self.text[self.at]
        self.at += 1
        return True

    def value(self):
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

    def string(self, end=None):
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

    def _consume_empty_object(self):
        if self.ch != "}":
            return False
        self.depth -= 1
        self.next_chr()
        return True

    def _object_as_sequence(self, data):
        if any(isinstance(key, SORTABLE_KEY_TYPES) for key in data):
            return data
        keys = sorted(data)
        if not sequential(keys):
            return data
        result = []
        for key, value in data.items():
            result.insert(key, value)
        return result

    def _close_object(self, data, pending_key, index):
        self.depth -= 1
        self.next_chr()
        if pending_key is not None:
            data[index] = pending_key
        return self._object_as_sequence(data)

    def _read_object_item(self, data, index):
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
            data[key] = self.value()
        else:
            data[index] = key
        return None, index + 1

    def object(self):
        data = {}
        pending_key = None
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
        raise ParseError(ERRORS["unexp_end_table"])  # 表未正常结束。

    words: ClassVar[dict[str, Any]] = {"true": True, "false": False, "nil": None}

    def word(self):
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

    def number(self):
        def next_digit(err):
            n = self.ch
            self.next_chr()
            if not self.ch or not self.ch.isdigit():
                raise ParseError(err)
            return n

        def require_exponent_sign():
            if not self.ch or self.ch not in ("+", "-"):
                raise ParseError(ERRORS["mfnumber_sci"])

        n = ""
        try:
            if self.ch == "-":
                n += next_digit(ERRORS["mfnumber_minus"])
            n += self.digit()
            if n == "0" and self.ch in ["x", "X"]:
                n += self.ch
                self.next_chr()
                n += self.hex()
            else:
                if self.ch and self.ch == ".":
                    n += next_digit(ERRORS["mfnumber_dec_point"])
                    n += self.digit()
                if self.ch and self.ch in ["e", "E"]:
                    n += self.ch
                    self.next_chr()
                    require_exponent_sign()
                    n += next_digit(ERRORS["mfnumber_sci"])
                    n += self.digit()
        except ParseError as e:
            print(e)
            return 0
        with suppress(ValueError):
            return int(n, 0)
        return float(n)

    def digit(self):
        n = ""
        while self.ch and self.ch.isdigit():
            n += self.ch
            self.next_chr()
        return n

    def hex(self):
        n = ""
        while self.ch and (self.ch in "ABCDEFabcdef" or self.ch.isdigit()):
            n += self.ch
            self.next_chr()
        return n


slpp = SLPP()
