from collections.abc import Mapping
from datetime import date

from module.config.config_updater import ConfigGenerator
from module.config.deep import DeepValue, MutableDeepData, deep_get
from module.config.utils import filepath_i18n, read_file
from module.content.manifest import load_default_event_manifests
from module.content.models import ContentId, EventPack, EventRelease


def _string_mapping(value: DeepValue | None) -> dict[str, str]:
    if not isinstance(value, Mapping):
        message = "expected string mapping"
        raise TypeError(message)
    result: dict[str, str] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not isinstance(item, str):
            message = "expected string mapping"
            raise TypeError(message)
        result[key] = item
    return result


def _pack(pack_id: str, kind: str, *releases: tuple[str, str | None, int]) -> EventPack:
    return EventPack(
        pack_id=ContentId(pack_id),
        kind=kind,
        releases=tuple(EventRelease(date.fromisoformat(opened), name, order) for opened, name, order in releases),
    )


def _generator(
    task: MutableDeepData,
    argument: MutableDeepData,
    gui: MutableDeepData | None = None,
    packs: list[EventPack] | None = None,
) -> ConfigGenerator:
    generator = object.__new__(ConfigGenerator)
    generator.task = task
    generator.argument = argument
    generator.gui = gui or {}
    generator.event_packs = tuple(packs or [])
    return generator


def test_generate_i18n_data_preserves_existing_words_and_adds_fallbacks() -> None:
    generator = _generator(
        task={"Main": {"tasks": {"General": {"groups": ["Settings"]}}}},
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
            "Task": {"General": {"help": "旧帮助"}},
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
    assert deep_get(data, keys="Task.General.name") == "Task.General.name"
    assert deep_get(data, keys="Task.General.help") == "旧帮助"
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
        packs=[
            _pack("event_same", "event", ("2026-01-01", "新、活动", 20), ("2025-01-01", "旧活动", 10)),
            _pack("event_missing", "event", ("2024-01-01", None, 30)),
            _pack("war_archives_demo", "war_archives", ("2023-01-01", "档案名", 40)),
        ],
    )

    data = generator.generate_i18n_data({})

    assert deep_get(data, keys="Campaign.Event.event_same") == "新活动"
    assert deep_get(data, keys="Campaign.Event.event_missing") == "event_missing"
    assert deep_get(data, keys="Campaign.Event.war_archives_demo") == "档案 档案名"


def test_real_manifest_i18n_matches_checked_in_chinese_names() -> None:
    generator = _generator(task={}, argument={}, packs=list(load_default_event_manifests()))

    generated = _string_mapping(deep_get(generator.generate_i18n_data({}), keys="Campaign.Event"))
    checked_in = _string_mapping(deep_get(read_file(filepath_i18n("zh-CN")), keys="Campaign.Event"))
    checked_in_packs = {pack_id: checked_in[pack_id] for pack_id in generated}

    assert generated == checked_in_packs
    assert len(generated) == 132
    assert list(generated) == sorted(generated)
