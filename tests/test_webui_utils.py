import module.webui.utils as webui_utils
from module.webui.utils import _read


def test_add_css_reads_utf8_text(tmp_path, monkeypatch) -> None:
    css_file = tmp_path / "theme.css"
    css_file.write_text("/* 中文主题 */\nbody { color: red; }", encoding="utf-8")
    scripts = []
    monkeypatch.setattr(webui_utils, "run_js", scripts.append)

    webui_utils.add_css(css_file)

    assert scripts == ["$('head').append('<style>/* 中文主题 */body { color: red; }</style>')"]


def test_read_reads_utf8_text(tmp_path) -> None:
    text_file = tmp_path / "icon.svg"
    text_file.write_text("<svg><text>舰队</text></svg>", encoding="utf-8")

    assert _read(text_file) == "<svg><text>舰队</text></svg>"
