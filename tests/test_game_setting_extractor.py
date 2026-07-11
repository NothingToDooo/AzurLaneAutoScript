import pytest

from module.game_setting import setting_extractor
from module.game_setting.setting_extractor import LuaSetting, SettingExtractor


@pytest.mark.parametrize(
    ("typ", "code", "expected"),
    [
        ("Int", '"key", 3', 3),
        ("Int", '"key", bad', 0),
        ("String", '"key", "value"', "'value'"),
        ("Float", '"key", 1.5', 1.5),
        ("Float", '"key", bad', 0.0),
        ("Int", '"key"', 0),
        ("String", '"key"', "''"),
        ("Float", '"key"', 0.0),
        ("Bool", '"key"', None),
        ("Bool", '"key", true', None),
    ],
)
def test_lua_setting_default(typ: str, code: str, expected: float | str | None) -> None:
    setting = LuaSetting(raw="", typ=typ, code=code)

    assert setting.default == expected


def test_lua_setting_duplicate_is_explicit_instance_state() -> None:
    regular = LuaSetting(raw='PlayerPrefs.GetInt("key", 0)', typ="Int", code='"key", 0')
    duplicate = LuaSetting(raw='PlayerPrefs.GetInt("key", 0)', typ="Int", code='"key", 0', duplicate=True)

    assert regular.duplicate is False
    assert duplicate.duplicate is True
    assert regular.generated[-1].startswith("key = Field(")
    assert duplicate.generated[-1] == "# 重复项"


def test_iter_file_from_folder_preserves_walk_order_and_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    walked = [
        ("root", ["nested"], ["second.lua", "first.lua"]),
        ("root/nested", [], ["third.lua"]),
    ]
    monkeypatch.setattr(setting_extractor.os, "walk", lambda _folder: iter(walked))

    assert list(SettingExtractor.iter_file_from_folder("root")) == [
        "root/second.lua",
        "root/first.lua",
        "root/nested/third.lua",
    ]
