import typing as t
from pathlib import Path


class TabWrapper:
    def __init__(self, generator, prefix="", suffix="", newline=True):
        self.generator = generator
        self.prefix = prefix
        self.suffix = suffix
        self.newline = newline

        self.nested = False

    def __enter__(self):
        if not self.nested and self.prefix:
            self.generator.add(self.prefix, newline=self.newline)
        self.generator.tab_count += 1
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.generator.tab_count -= 1
        if self.suffix:
            self.generator.add(self.suffix)

    def __repr__(self):
        return self.prefix

    def set_nested(self, suffix=""):
        self.nested = True
        self.suffix += suffix


class CodeGenerator:
    def __init__(self):
        self.tab_count = 0
        self.lines = []

    def generate(self) -> t.Iterable[str]:
        yield ""

    def add(self, line, comment=False, newline=True):
        self.lines.append(self._line_with_tabs(line, comment=comment, newline=newline))

    def write(self, file: str):
        lines = "".join(self.lines)
        Path(file).write_text(lines, encoding="utf-8", newline="")

    def _line_with_tabs(self, line, comment=False, newline=True):
        if comment:
            line = "# " + line
        out = "    " * self.tab_count + line
        if newline:
            out += "\n"
        return out

    def _repr(self, obj):
        if isinstance(obj, str) and "\n" in obj:
            out = '"""\n'
            with self.tab():
                for raw_line in obj.strip().split("\n"):
                    line = raw_line.strip()
                    out += self._line_with_tabs(line)
            out += self._line_with_tabs('"""', newline=False)
            return out
        return repr(obj)

    def tab(self):
        return TabWrapper(self)

    def empty(self):
        self.add("")

    def import_(self, text, empty=2):
        for raw_line in text.strip().split("\n"):
            line = raw_line.strip()
            self.add(line)
        for _ in range(empty):
            self.empty()

    def value(self, key=None, value=None, type_=None, **kwargs):
        if key is not None:
            if type_ is not None:
                self.add(f"{key}: {type_} = {self._repr(value)}")
            else:
                self.add(f"{key} = {self._repr(value)}")
        for kw_key, kw_value in kwargs.items():
            self.value(kw_key, kw_value)

    def comment(self, text):
        for raw_line in text.strip().split("\n"):
            line = raw_line.strip()
            self.add(line, comment=True)

    def list_(self, key=None):
        if key is not None:
            return TabWrapper(self, prefix=str(key) + " = [", suffix="]")
        return TabWrapper(self, prefix="[", suffix="]", newline=False)

    def list_item(self, value):
        if isinstance(value, TabWrapper):
            value.set_nested(suffix=",")
            self.add(f"{self._repr(value)}")
            return value
        self.add(f"{self._repr(value)},")
        return None

    def dict_(self, key=None):
        if key is not None:
            return TabWrapper(self, prefix=str(key) + " = {", suffix="}")
        return TabWrapper(self, prefix="{", suffix="}", newline=False)

    def dict_item(self, key=None, value=None):
        if isinstance(value, TabWrapper):
            value.set_nested(suffix=",")
            if key is not None:
                self.add(f"{self._repr(key)}: {self._repr(value)}")
            return value
        if key is not None:
            self.add(f"{self._repr(key)}: {self._repr(value)},")
        return None

    def object_(self, object_class, key=None):
        if key is not None:
            return TabWrapper(self, prefix=f"{key} = {object_class}(", suffix=")")
        return TabWrapper(self, prefix=f"{object_class}(", suffix=")", newline=False)

    def object_attr(self, key=None, value=None):
        if isinstance(value, TabWrapper):
            value.set_nested(suffix=",")
            if key is None:
                self.add(f"{self._repr(value)}")
            else:
                self.add(f"{key}={self._repr(value)}")
            return value
        if key is None:
            self.add(f"{self._repr(value)},")
        else:
            self.add(f"{key}={self._repr(value)},")
        return None

    def class_(self, name, inherit=None):
        if inherit is not None:
            return TabWrapper(self, prefix=f"class {name}({inherit}):")
        return TabWrapper(self, prefix=f"class {name}:")

    def def_(self, name, args=""):
        return TabWrapper(self, prefix=f"def {name}({args}):")


generator = CodeGenerator()
import_ = generator.import_
value = generator.value
comment = generator.comment
dict_ = generator.dict_
dict_item = generator.dict_item
