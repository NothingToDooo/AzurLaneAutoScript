from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

    import pytest

import module.webui.utils as webui_utils
from module.webui.utils import Switch, Task, _read, get_generator


def test_add_css_reads_utf8_text(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    css_file = tmp_path / "theme.css"
    css_file.write_text("/* 中文主题 */\nbody { color: red; }", encoding="utf-8")
    scripts: list[str] = []
    monkeypatch.setattr(webui_utils, "run_js", scripts.append)

    webui_utils.add_css(css_file)

    assert scripts == ["$('head').append('<style>/* 中文主题 */body { color: red; }</style>')"]


def test_read_reads_utf8_text(tmp_path: Path) -> None:
    text_file = tmp_path / "icon.svg"
    text_file.write_text("<svg><text>舰队</text></svg>", encoding="utf-8")

    assert _read(text_file) == "<svg><text>舰队</text></svg>"


def test_task_generator_runs_callback_after_priming() -> None:
    calls: list[str] = []
    task = Task(get_generator(lambda: calls.append("tick")), delay=1)

    task.send(None)

    assert calls == ["tick"]


def test_switch_runs_mapped_actions_only_for_known_states() -> None:
    states = iter([0, 0, 1])
    calls: list[str] = []
    switch = Switch(
        status={
            0: lambda: calls.append("off"),
            1: [lambda: calls.append("on"), lambda: calls.append("refreshed")],
        },
        get_state=lambda: next(states),
    )

    switch.switch()
    switch.switch()
    switch.switch()

    assert calls == ["off", "on", "refreshed"]
