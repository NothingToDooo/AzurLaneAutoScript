from rich.console import Console

from module.logger import RenderOptions, RichRenderableHandler, emit_renderables, logger, render_options


def test_render_options_override_existing_options() -> None:
    options = render_options(RenderOptions(sep="|"), {"end": ""})

    assert options.sep == "|"
    assert options.end == ""


def test_emit_renderables_accepts_keyword_settings() -> None:
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
        emit_renderables("a", "b", sep="|", end="")
    finally:
        logger.handlers = previous_handlers
        handler.close()

    assert renderables
