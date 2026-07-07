import re
from numbers import Number

import six

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
SORTABLE_KEY_TYPES = (*six.string_types, int, float, bool, tuple)


def sequential(lst):
    length = len(lst)
    if length == 0 or lst[0] != 0:
        return False
    for i in range(length):
        if i + 1 < length:
            if lst[i] + 1 != lst[i + 1]:
                return False
    return True


class ParseError(Exception):
    pass


class SLPP:
    def __init__(self):
        self.text = ""
        self.ch = ""
        self.at = 0
        self.len = 0
        self.depth = 0
        self.space = re.compile(r"\s", re.M)
        self.alnum = re.compile(r"\w", re.M)
        self.newline = "\n"
        self.tab = "\t"

    def decode(self, text):
        if not text or not isinstance(text, six.string_types):
            return None
        # 游戏脚本没有注释。
        # 删除注释可能导致错误，例如下面这类内容会被误认为注释：
        # `profiles = "现世与梦境夹缝中的蝴蝶，狂风与巨浪蹂躏中的小舟。`
        # `跨越虚无，驱散黑暗，为重樱带来希望和未来吧---------- ",`
        # reg = re.compile('--.*$', re.M)
        # text = reg.sub('', text, 0)
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
        elif six.PY2 and isinstance(obj, six.text_type):
            escaped = obj.encode("utf-8").replace(r'"', r"\"")
            s += f'"{escaped}"'
        elif six.PY3 and isinstance(obj, bytes):
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
                and len([x for x in obj if isinstance(x, Number) or (isinstance(x, six.string_types) and len(x) < 10)])
                == len(obj)
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
                    if self.ch != end:
                        s += "\\"
                s += self.ch
        raise ParseError(ERRORS["unexp_end_string"])

    def object(self):
        o = {}
        k = None
        idx = 0
        self.depth += 1
        self.next_chr()
        self.white()
        if self.ch and self.ch == "}":
            self.depth -= 1
            self.next_chr()
            return o  # 空表直接结束。
        while self.ch:
            self.white()
            if self.ch == "{":
                o[idx] = self.object()
                idx += 1
                continue
            if self.ch == "}":
                self.depth -= 1
                self.next_chr()
                if k is not None:
                    o[idx] = k
                if not any(isinstance(key, SORTABLE_KEY_TYPES) for key in o):
                    so = sorted(o)
                    if sequential(so):
                        ar = []
                        for key, value in o.items():
                            ar.insert(key, value)
                        o = ar
                return o  # 表对象解析完成。
            if self.ch == ",":
                self.next_chr()
                continue
            k = self.value()
            if self.ch == "]":
                self.next_chr()
            self.white()
            ch = self.ch
            if ch in ("=", ","):
                self.next_chr()
                self.white()
                if ch == "=":
                    o[k] = self.value()
                else:
                    o[idx] = k
                idx += 1
                k = None
        raise ParseError(ERRORS["unexp_end_table"])  # 表未正常结束。

    words = {"true": True, "false": False, "nil": None}

    def word(self):
        s = ""
        if self.ch != "\n":
            s = self.ch
        self.next_chr()
        while self.ch is not None and self.alnum.match(self.ch) and s not in self.words:
            s += self.ch
            self.next_chr()
        return self.words.get(s, s)

    def number(self):
        def next_digit(err):
            n = self.ch
            self.next_chr()
            if not self.ch or not self.ch.isdigit():
                raise ParseError(err)
            return n

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
                    if not self.ch or self.ch not in ("+", "-"):
                        raise ParseError(ERRORS["mfnumber_sci"])
                    n += next_digit(ERRORS["mfnumber_sci"])
                    n += self.digit()
        except ParseError as e:
            print(e)
            return 0
        try:
            return int(n, 0)
        except Exception:
            pass
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
