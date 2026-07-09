from module.config.config_updater import ConfigGenerator, Event
from module.config.deep import deep_get


def _event(date: str, directory: str, name: str) -> Event:
    return Event(f"| {date} | {directory} | {name} |")


def _generator(task: dict, argument: dict, gui: dict | None = None, events: list[Event] | None = None):
    generator = object.__new__(ConfigGenerator)
    generator.task = task
    generator.argument = argument
    generator.gui = gui or {}
    generator.event = events or []
    return generator


def test_generate_i18n_data_preserves_existing_words_and_adds_fallbacks() -> None:
    generator = _generator(
        task={"Main": {"tasks": {"Demo": ["Settings"]}}},
        argument={
            "Settings": {
                "Mode": {"value": "a", "option": ["a", "b"]},
            },
        },
        gui={"Dashboard": {"Start": None}},
    )

    data = generator.generate_i18n_data(
        {
            "Menu": {"Main": {"name": "主菜单"}},
            "Task": {"Demo": {"help": "旧帮助"}},
            "Settings": {
                "_info": {"name": "设置组"},
                "Mode": {
                    "name": "模式",
                    "a": "甲",
                },
            },
            "Gui": {"Dashboard": {"Start": "启动"}},
        }
    )

    assert deep_get(data, keys="Menu.Main.name") == "主菜单"
    assert deep_get(data, keys="Menu.Main.help") == "Menu.Main.help"
    assert deep_get(data, keys="Task.Demo.name") == "Task.Demo.name"
    assert deep_get(data, keys="Task.Demo.help") == "旧帮助"
    assert deep_get(data, keys="Settings._info.name") == "设置组"
    assert deep_get(data, keys="Settings.Mode.name") == "模式"
    assert deep_get(data, keys="Settings.Mode.help") == "Settings.Mode.help"
    assert deep_get(data, keys="Settings.Mode.a") == "甲"
    assert deep_get(data, keys="Settings.Mode.b") == "b"
    assert deep_get(data, keys="Gui.Dashboard.Start") == "启动"


def test_generate_i18n_data_uses_cn_event_name_and_directory_fallback() -> None:
    generator = _generator(
        task={},
        argument={},
        events=[
            _event("20260101", "event_same", "新活动"),
            _event("20250101", "event_same", "旧活动"),
            _event("20240101", "event_missing", "-"),
        ],
    )

    data = generator.generate_i18n_data({})

    assert deep_get(data, keys="Campaign.Event.event_same") == "新活动"
    assert deep_get(data, keys="Campaign.Event.event_missing") == "event_missing"
