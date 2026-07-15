import re
from dataclasses import dataclass
from typing import Self

from module.content.errors import ContentValidationError

_CELL_NODE = re.compile(r"^([A-Z]+)([1-9][0-9]*)$")


@dataclass(frozen=True, slots=True, order=True)
class CellId:
    x: int
    y: int

    def __post_init__(self) -> None:
        if type(self.x) is not int or self.x < 0 or type(self.y) is not int or self.y < 0:
            message = "cell coordinates must be non-negative integers"
            raise ContentValidationError(message)

    @classmethod
    def parse(cls, node: object) -> Self:
        """把规范的 A1 节点解析为 CellId。"""

        match = _CELL_NODE.fullmatch(node) if isinstance(node, str) else None
        if match is None:
            message = "must be a valid uppercase grid node"
            raise ContentValidationError(message)
        letters, row = match.groups()
        column = 0
        for letter in letters:
            column = column * 26 + ord(letter) - ord("A") + 1
        return cls(column - 1, int(row) - 1)

    @property
    def node(self) -> str:
        column = self.x + 1
        letters = ""
        while column:
            column, remainder = divmod(column - 1, 26)
            letters = chr(ord("A") + remainder) + letters
        return f"{letters}{self.y + 1}"

    def __str__(self) -> str:
        return self.node
