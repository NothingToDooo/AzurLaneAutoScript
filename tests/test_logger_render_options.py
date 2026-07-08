from rich.console import Console

from module.logger import RenderOptions, _get_renderables, render_options


def test_render_options_override_existing_options() -> None:
    options = render_options(RenderOptions(sep="|"), {"end": ""})

    assert options.sep == "|"
    assert options.end == ""


def test_get_renderables_accepts_print_keyword_settings() -> None:
    console = Console(no_color=True, width=80)

    renderables = _get_renderables(console, "a", "b", sep="|", end="")

    assert renderables
