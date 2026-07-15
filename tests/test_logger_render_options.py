from io import StringIO

from rich.console import Console

from module.logger import RenderOptions, RichRenderableHandler, emit_renderables, logger, render_options


def test_render_options_override_existing_options() -> None:
    options = render_options(RenderOptions(sep="|"), {"end": ""})

    assert options.sep == "|"
    assert options.end == ""


def test_emit_renderables_applies_keyword_settings_to_rendered_text() -> None:
    output = StringIO()
    console = Console(file=output, no_color=True, width=80)
    handler = RichRenderableHandler(
        console=console,
        show_time=False,
        show_level=False,
        show_path=False,
    )
    handler.set_render_callback(lambda renderable: console.print(renderable, end=""))

    previous_handlers = logger.handlers
    try:
        logger.handlers = [handler]
        emit_renderables("a", "b", sep="|", end="")
    finally:
        logger.handlers = previous_handlers
        handler.close()

    assert output.getvalue() == "a|b"
