from dataclasses import dataclass

from module.content.errors import ContentValidationError


@dataclass(frozen=True, slots=True, order=True)
class CellId:
    x: int
    y: int

    def __post_init__(self) -> None:
        if type(self.x) is not int or self.x < 0 or type(self.y) is not int or self.y < 0:
            message = "cell coordinates must be non-negative integers"
            raise ContentValidationError(message)

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
