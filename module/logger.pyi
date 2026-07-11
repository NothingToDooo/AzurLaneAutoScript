import logging
from collections.abc import Callable

from rich.console import Console, ConsoleRenderable, RenderableType
from rich.highlighter import RegexHighlighter
from rich.logging import RichHandler
from rich.theme import Theme

class HTMLConsole(Console): ...
class Highlighter(RegexHighlighter): ...

class RichRenderableHandler(RichHandler):
    def __init__(
        self,
        *args,
        func: Callable[[ConsoleRenderable], None] | None = ...,
        **kwargs,
    ) -> None: ...
    def emit_renderable(self, renderable: ConsoleRenderable) -> None: ...

class RenderOptions:
    sep: str
    end: str
    justify: object
    emoji: object
    markup: object
    highlight: object
    def __init__(
        self,
        sep: str = ...,
        end: str = ...,
        justify: object = ...,
        emoji: object = ...,
        markup: object = ...,
        highlight: object = ...,
    ) -> None: ...

WEB_THEME: Theme

logger_debug: bool
pyw_name: str

file_formatter: logging.Formatter
console_formatter: logging.Formatter
web_formatter: logging.Formatter

stdout_console: Console
console_hdlr: RichHandler

def set_file_logger(
    name: str = ...,
) -> None: ...
def get_log_file() -> str: ...
def set_func_logger(
    func: Callable[[ConsoleRenderable], None],
) -> None: ...
def render_options(
    options: RenderOptions | None = ...,
    settings: dict[str, object] | None = ...,
) -> RenderOptions: ...
def emit_renderables(
    *objects: RenderableType,
    **kwargs,
) -> None: ...

class __logger(logging.Logger):
    log_file: str

    def rule(
        self,
        title: str = "",
        *,
        characters: str = "-",
        style: str = "rule.line",
        end: str = "\n",
        align: str = "center",
    ) -> None: ...
    def hr(
        self,
        title,
        level: int = 3,
    ) -> None: ...
    def attr(
        self,
        name,
        text,
    ) -> None: ...
    def attr_align(
        self,
        name,
        text,
        front="",
        align: int = 22,
    ) -> None: ...
    def set_file_logger(
        self,
        name: str = ...,
    ) -> None: ...
    def set_func_logger(
        self,
        func: Callable[[ConsoleRenderable], None],
    ) -> None: ...

logger: __logger
