from module.config.server import CN_ACTIVITY, CN_PACKAGE, CN_SERVER


def test_personal_server_constants_are_fixed_cn() -> None:
    assert CN_SERVER == "cn"
    assert CN_PACKAGE == "com.bilibili.azurlane"
    assert CN_ACTIVITY == "com.manjuu.azurlane.MainActivity"
