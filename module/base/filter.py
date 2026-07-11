import re

from module.logger import logger


class Filter:
    def __init__(self, regex, attr, preset=()):
        if isinstance(regex, str):
            regex = re.compile(regex)
        self.regex = regex
        self.attr = attr
        self.preset = tuple(p.lower() for p in preset)
        self.filter_raw = []
        self.filter = []

    def load(self, string):
        """用 `>` 连接筛选项，同时接受 `＞﹥›˃ᐳ❯` 等近似字符。"""
        string = str(string)
        string = re.sub(r"[ \t\r\n]", "", string)
        string = re.sub(r"[＞﹥›˃ᐳ❯]", ">", string)
        self.filter_raw = string.split(">")
        self.filter = [self.parse_filter(f) for f in self.filter_raw]

    def is_preset(self, filter_value):
        return len(filter_value) and filter_value.lower() in self.preset

    def apply(self, objs, func=None):
        """按已加载条件筛选对象并保留预设字符串；func 返回真时保留对应对象。"""
        out = []
        for raw_filter, parsed_filter in zip(self.filter_raw, self.filter, strict=True):
            if self.is_preset(raw_filter):
                preset = raw_filter.lower()
                if preset not in out:
                    out.append(preset)
            else:
                for obj in objs:
                    if self.apply_filter_to_obj(obj=obj, filter_value=parsed_filter) and obj not in out:
                        out.append(obj)

        if func is not None:
            objs, out = out, []
            for obj in objs:
                if isinstance(obj, str) or func(obj):
                    out.append(obj)
                else:
                    # 回调拒绝的对象不进入结果。
                    pass

        return out

    def applys(self, objs, funcs):
        return self.apply(objs, func=lambda x: all(func(x) for func in funcs))

    def apply_filter_to_obj(self, obj, filter_value):
        for attr, value in zip(self.attr, filter_value, strict=True):
            if not value:
                continue
            if str(getattr(obj, attr)).lower() != str(value):
                return False

        return True

    def parse_filter(self, string):
        string = string.replace(" ", "").lower()
        result = re.search(self.regex, string)

        if self.is_preset(string):
            return [string]

        if result and len(string) and result.span()[1]:
            return [result.group(index + 1) for index, attr in enumerate(self.attr)]
        logger.warning(f'Invalid filter: "{string}". This selector does not match the regex, nor a preset.')
        # 无效筛选器用不可能匹配的哨兵表示，避免意外选中对象。
        return ["1nVa1d"] + [None] * (len(self.attr) - 1)
