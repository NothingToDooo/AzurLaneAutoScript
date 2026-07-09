from typing import Protocol, cast

from rich.console import Console, RenderableType

from module.logger import RenderOptions, RichRenderableHandler, logger, render_options


class _PrintableLogger(Protocol):
    def print(self, *objects: RenderableType, **kwargs) -> None: ...


def test_render_options_override_existing_options() -> None:
    options = render_options(RenderOptions(sep="|"), {"end": ""})

    assert options.sep == "|"
    assert options.end == ""


def test_print_accepts_keyword_settings() -> None:
    console = Console(no_color=True, width=80)
    renderables = []
    handler = RichRenderableHandler(
        console=console,
        func=renderables.append,
        show_time=False,
        show_level=False,
        show_path=False,
    )

    previous_handlers = logger.handlers
    try:
        logger.handlers = [handler]
        cast("_PrintableLogger", logger).print("a", "b", sep="|", end="")
    finally:
        logger.handlers = previous_handlers
        handler.close()

    assert renderables
