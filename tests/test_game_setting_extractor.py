import pytest

from module.game_setting.setting_extractor import LuaSetting


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
def test_lua_setting_default(typ: str, code: str, expected) -> None:
    setting = LuaSetting(raw="", typ=typ, code=code)

    assert setting.default == expected
