import logging
from collections.abc import Callable
from pathlib import Path
from typing import Literal, TypedDict, Unpack

from rich.console import Console, ConsoleRenderable, RenderableType
from rich.highlighter import RegexHighlighter
from rich.logging import RichHandler
from rich.style import Style
from rich.text import Text
from rich.theme import Theme

class HTMLConsole(Console): ...
class Highlighter(RegexHighlighter): ...

class RichRenderableHandler(RichHandler):
    def set_render_callback(self, func: Callable[[ConsoleRenderable], None] | None) -> None: ...
    def emit_renderable(self, renderable: ConsoleRenderable) -> None: ...

class RenderOptions:
    sep: str
    end: str
    justify: Literal["default", "left", "center", "right", "full"] | None
    emoji: bool | None
    markup: bool | None
    highlight: bool | None
    def __init__(
        self,
        sep: str = ...,
        end: str = ...,
        justify: Literal["default", "left", "center", "right", "full"] | None = ...,
        emoji: bool | None = ...,
        markup: bool | None = ...,
        highlight: bool | None = ...,
    ) -> None: ...

class RenderOptionSettings(TypedDict, total=False):
    sep: str
    end: str
    justify: Literal["default", "left", "center", "right", "full"] | None
    emoji: bool | None
    markup: bool | None
    highlight: bool | None

WEB_THEME: Theme

logger_debug: bool

file_formatter: logging.Formatter
console_formatter: logging.Formatter
web_formatter: logging.Formatter

stdout_console: Console
console_hdlr: RichHandler

def configure_file_logging(project_root: Path, *, name: str) -> Path: ...
def get_log_file() -> Path: ...
def set_func_logger(
    func: Callable[[ConsoleRenderable], None],
) -> None: ...
def render_options(
    options: RenderOptions | None = ...,
    settings: RenderOptionSettings | None = ...,
) -> RenderOptions: ...
def emit_renderables(
    *objects: RenderableType,
    **settings: Unpack[RenderOptionSettings],
) -> None: ...

class AlasLogger(logging.Logger):
    log_file: Path

    def rule(
        self,
        title: str | Text = "",
        *,
        characters: str = "-",
        style: str | Style = "rule.line",
        end: str = "\n",
        align: Literal["left", "center", "right"] = "center",
    ) -> None: ...
    def hr(
        self,
        title: object,
        level: int = 3,
    ) -> None: ...
    def attr(
        self,
        name: object,
        text: object,
    ) -> None: ...
    def attr_align(
        self,
        name: object,
        text: object,
        front: str = "",
        align: int = 22,
    ) -> None: ...
    def set_func_logger(
        self,
        func: Callable[[ConsoleRenderable], None],
    ) -> None: ...

logger: AlasLogger
