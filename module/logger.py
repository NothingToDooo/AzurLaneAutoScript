import datetime
import logging
from dataclasses import dataclass
from functools import wraps
from typing import TYPE_CHECKING, ClassVar, Literal, TypedDict, Unpack, cast

from rich.console import Console, ConsoleOptions, ConsoleRenderable, NewLine, RenderableType
from rich.highlighter import NullHighlighter, RegexHighlighter
from rich.logging import RichHandler
from rich.rule import Rule
from rich.style import Style
from rich.theme import Theme
from rich.traceback import Traceback

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path
    from typing import Concatenate

    from rich.text import Text

    class AlasLogger(logging.Logger):
        log_file: Path

        def hr(self, title: object, level: int = 3) -> None: ...

        def attr(self, name: object, text: object) -> None: ...

        def attr_align(self, name: object, text: object, front: str = "", align: int = 22) -> None: ...

        def set_func_logger(self, func: Callable[[ConsoleRenderable], None]) -> None: ...

        def rule(
            self,
            title: str | Text = "",
            *,
            characters: str = "─",
            style: str | Style = "rule.line",
            end: str = "\n",
            align: Literal["left", "center", "right"] = "center",
        ) -> None: ...


def empty_function(*args: object, **kwargs: object) -> None:
    del args, kwargs


# cnocr 会设置根日志器；禁用 basicConfig 可避免同一消息重复输出。
vars(logging)["basicConfig"] = empty_function
logging.raiseExceptions = True

RichHandler.KEYWORDS = []


class RichFileHandler(RichHandler):
    _file_handler: logging.FileHandler | None = None

    def set_file_handler(self, file_handler: logging.FileHandler) -> None:
        self._file_handler = file_handler

    def close(self) -> None:
        if self._file_handler is not None:
            self._file_handler.close()
            self._file_handler = None
        super().close()


class RichRenderableHandler(RichHandler):
    _func: Callable[[ConsoleRenderable], None] | None = None

    def set_render_callback(self, func: Callable[[ConsoleRenderable], None] | None) -> None:
        self._func = func

    def emit_renderable(self, renderable: ConsoleRenderable) -> None:
        if self._func is not None:
            self._func(renderable)

    def emit(self, record: logging.LogRecord) -> None:
        message = self.format(record)
        traceback = None
        if self.rich_tracebacks and record.exc_info and record.exc_info != (None, None, None):
            exc_type, exc_value, exc_traceback = record.exc_info
            if exc_type is not None and exc_value is not None:
                traceback = Traceback.from_exception(
                    exc_type,
                    exc_value,
                    exc_traceback,
                    width=self.tracebacks_width,
                    extra_lines=self.tracebacks_extra_lines,
                    theme=self.tracebacks_theme,
                    word_wrap=self.tracebacks_word_wrap,
                    show_locals=self.tracebacks_show_locals,
                    locals_max_length=self.locals_max_length,
                    locals_max_string=self.locals_max_string,
                )
            message = record.getMessage()
            if self.formatter:
                record.message = record.getMessage()
                formatter = self.formatter
                if hasattr(formatter, "usesTime") and formatter.usesTime():
                    record.asctime = formatter.formatTime(record, formatter.datefmt)
                message = formatter.formatMessage(record)

        message_renderable = self.render_message(record, message)
        log_renderable = self.render(record=record, traceback=traceback, message_renderable=message_renderable)

        self.emit_renderable(log_renderable)

    def handle(self, record: logging.LogRecord) -> bool:
        if not self._func:
            return True
        return super().handle(record)


class HTMLConsole(Console):
    @property
    def options(self) -> ConsoleOptions:
        return ConsoleOptions(
            max_height=self.size.height,
            size=self.size,
            legacy_windows=False,
            min_width=1,
            max_width=self.width,
            encoding="utf-8",
            is_terminal=False,
        )


class Highlighter(RegexHighlighter):
    base_style = "web."
    highlights: ClassVar[list[str]] = [
        (
            r"(?P<time>([0-1]{1}\d{1}|[2]{1}[0-3]{1})(?::)?"
            r"([0-5]{1}\d{1})(?::)?([0-5]{1}\d{1})(.\d+\b))"
        ),
        r"(?P<brace>[\{\[\(\)\]\}])",
        r"\b(?P<bool_true>True)\b|\b(?P<bool_false>False)\b|\b(?P<none>None)\b",
        r"(?P<path>(([A-Za-z]\:)|.)?\B([\/\\][\w\.\-\_\+]+)*[\/\\])(?P<filename>[\w\.\-\_\+]*)?",
    ]


WEB_THEME = Theme(
    {
        "web.brace": Style(bold=True),
        "web.bool_true": Style(color="bright_green", italic=True),
        "web.bool_false": Style(color="bright_red", italic=True),
        "web.none": Style(color="magenta", italic=True),
        "web.path": Style(color="magenta"),
        "web.filename": Style(color="bright_magenta"),
        "web.str": Style(color="green", italic=False, bold=False),
        "web.time": Style(color="cyan"),
        "rule.text": Style(bold=True),
    }
)


logger_debug = False
logger = cast("AlasLogger", logging.getLogger("alas"))
logger.setLevel(logging.DEBUG if logger_debug else logging.INFO)
_logger_state: dict[str, Path | None] = {"log_file": None}
file_formatter = logging.Formatter(
    fmt="%(asctime)s.%(msecs)03d | %(levelname)s | %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
)
console_formatter = logging.Formatter(fmt="%(asctime)s.%(msecs)03d │ %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
web_formatter = logging.Formatter(fmt="%(asctime)s.%(msecs)03d │ %(message)s", datefmt="%H:%M:%S")

stdout_console = console = Console()
console_hdlr = RichHandler(
    show_path=False,
    show_time=False,
    rich_tracebacks=True,
    tracebacks_show_locals=True,
    tracebacks_extra_lines=3,
)
console_hdlr.setFormatter(console_formatter)
logger.addHandler(console_hdlr)


def configure_file_logging(project_root: Path, *, name: str) -> Path:
    log_dir = project_root.resolve() / "log"
    log_dir.mkdir(parents=True, exist_ok=True)
    today = datetime.datetime.now(tz=datetime.UTC).astimezone().date()
    log_file = log_dir / f"{today}_{name}.txt"
    file_handler = logging.FileHandler(log_file, mode="a", encoding="utf-8")

    file_console = Console(
        file=file_handler.stream,
        no_color=True,
        highlight=False,
        width=119,
    )

    hdlr = RichFileHandler(
        console=file_console,
        show_path=False,
        show_time=False,
        show_level=False,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        tracebacks_extra_lines=3,
        highlighter=NullHighlighter(),
    )
    hdlr.set_file_handler(file_handler)
    hdlr.setFormatter(file_formatter)

    for handler in logger.handlers[:]:
        if isinstance(handler, (logging.FileHandler, RichFileHandler)):
            logger.removeHandler(handler)
            handler.close()
    logger.addHandler(hdlr)
    _logger_state["log_file"] = log_file
    vars(logger)["log_file"] = log_file
    logger.hr("Start", level=0)
    return log_file


def get_log_file() -> Path:
    log_file = _logger_state["log_file"]
    if log_file is None:
        msg = "File logger is not initialized"
        raise RuntimeError(msg)
    return log_file


def set_func_logger(func: Callable[[ConsoleRenderable], None]) -> None:
    console = HTMLConsole(
        force_terminal=False,
        force_interactive=False,
        width=80,
        color_system="truecolor",
        markup=False,
        safe_box=False,
        highlighter=Highlighter(),
        theme=WEB_THEME,
    )
    hdlr = RichRenderableHandler(
        console=console,
        show_path=False,
        show_time=False,
        show_level=True,
        rich_tracebacks=True,
        tracebacks_show_locals=True,
        tracebacks_extra_lines=2,
        highlighter=Highlighter(),
    )
    hdlr.set_render_callback(func)
    hdlr.setFormatter(web_formatter)
    logger.handlers = [h for h in logger.handlers if not isinstance(h, RichRenderableHandler)]
    logger.addHandler(hdlr)


@dataclass(frozen=True, slots=True)
class RenderOptions:
    sep: str = " "
    end: str = "\n"
    justify: Literal["default", "left", "center", "right", "full"] | None = None
    emoji: bool | None = None
    markup: bool | None = None
    highlight: bool | None = None


class RenderOptionSettings(TypedDict, total=False):
    sep: str
    end: str
    justify: Literal["default", "left", "center", "right", "full"] | None
    emoji: bool | None
    markup: bool | None
    highlight: bool | None


def render_options(
    options: RenderOptions | None = None,
    settings: RenderOptionSettings | None = None,
) -> RenderOptions:
    options = RenderOptions() if options is None else options
    if not settings:
        return options
    return RenderOptions(
        sep=settings.get("sep", options.sep),
        end=settings.get("end", options.end),
        justify=settings.get("justify", options.justify),
        emoji=settings.get("emoji", options.emoji),
        markup=settings.get("markup", options.markup),
        highlight=settings.get("highlight", options.highlight),
    )


def _get_renderables(
    self: Console,
    *objects: RenderableType,
    **settings: Unpack[RenderOptionSettings],
) -> list[ConsoleRenderable]:
    """参考 rich.console.Console.print() 收集可渲染对象。"""
    options = render_options(settings=settings)
    if not objects:
        objects = (NewLine(),)

    render_hooks = self._render_hooks[:]
    with self:
        renderables = self._collect_renderables(
            objects,
            options.sep,
            options.end,
            justify=options.justify,
            emoji=options.emoji,
            markup=options.markup,
            highlight=options.highlight,
        )
        for hook in render_hooks:
            renderables = hook.process_renderables(renderables)
    return renderables


def emit_renderables(*objects: RenderableType, **settings: Unpack[RenderOptionSettings]) -> None:
    for hdlr in logger.handlers:
        if isinstance(hdlr, RichRenderableHandler):
            for renderable in _get_renderables(hdlr.console, *objects, **settings):
                hdlr.emit_renderable(renderable)
        elif isinstance(hdlr, RichHandler):
            hdlr.console.print(*objects, **settings)


def rule(
    title: str | Text = "",
    *,
    characters: str = "─",
    style: str | Style = "rule.line",
    end: str = "\n",
    align: Literal["left", "center", "right"] = "center",
) -> None:
    rule = Rule(title=title, characters=characters, style=style, end=end, align=align)
    emit_renderables(rule)


def hr(title: object, level: int = 3) -> None:
    title = str(title).upper()
    if level == 1:
        logger.rule(title, characters="═")
        logger.info(title)
    if level == 2:
        logger.rule(title, characters="─")
        logger.info(title)
    if level == 3:
        logger.info("[bold]<<< %s >>>[/bold]", title, extra={"markup": True})
    if level == 0:
        logger.rule(characters="═")
        logger.rule(title, characters=" ")
        logger.rule(characters="═")


def attr(name: object, text: object) -> None:
    logger.info("[%s] %s", name, text)


def attr_align(name: object, text: object, front: str = "", align: int = 22) -> None:
    name = str(name).rjust(align)
    if front:
        name = front + name[len(front) :]
    logger.info("%s: %s", name, text)


class LoggerDemoError(Exception):
    pass


LOGGER_DEMO_ERROR_MESSAGE = "Exception"


def show() -> None:
    logger.info("INFO")
    logger.warning("WARNING")
    logger.debug("DEBUG")
    logger.error("ERROR")
    logger.critical("CRITICAL")
    logger.hr("hr0", 0)
    logger.hr("hr1", 1)
    logger.hr("hr2", 2)
    logger.hr("hr3", 3)
    logger.info(r"Brace { [ ( ) ] }")
    logger.info(r"True, False, None")
    logger.info(r"F:/alas/gui.py, F:/alas/alas.py, ./relative/path/log.txt")
    raise LoggerDemoError(LOGGER_DEMO_ERROR_MESSAGE)


def error_convert[**P, ReturnT](
    func: Callable[Concatenate[object, P], ReturnT],
) -> Callable[Concatenate[object, P], ReturnT]:
    @wraps(func)
    def error_wrapper(msg: object, *args: P.args, **kwargs: P.kwargs) -> ReturnT:
        if isinstance(msg, Exception):
            msg = f"{type(msg).__name__}: {msg}"
        return func(msg, *args, **kwargs)

    return error_wrapper


vars(logger)["error"] = error_convert(logger.error)
vars(logger)["hr"] = hr
vars(logger)["attr"] = attr
vars(logger)["attr_align"] = attr_align
vars(logger)["set_func_logger"] = set_func_logger
vars(logger)["rule"] = rule
