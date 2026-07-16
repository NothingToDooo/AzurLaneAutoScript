import re
from pathlib import Path

_ALAS_CSS = Path(__file__).resolve().parents[1] / "assets" / "gui" / "css" / "alas.css"


def _declarations(css: str, selector: str) -> str:
    bodies = [
        match.group("body")
        for match in re.finditer(r"(?P<selectors>[^{}]+)\{(?P<body>[^{}]*)\}", css)
        if selector in {item.strip() for item in match.group("selectors").split(",")}
    ]
    assert bodies
    return "\n".join(bodies)


def test_header_status_spinner_stays_in_its_cell_and_stops_when_inactive() -> None:
    css = _ALAS_CSS.read_text(encoding="utf-8")
    running = _declarations(css, '*[style*="--loading-border--"] > .spinner-border')
    inactive = _declarations(css, '*[style*="--loading-border-fill--"] > .spinner-border')

    for declarations in (running, inactive):
        assert "width: 100%" in declarations
        assert "height: 100%" in declarations
    assert "animation: none" not in running
    assert "animation: none" in inactive
