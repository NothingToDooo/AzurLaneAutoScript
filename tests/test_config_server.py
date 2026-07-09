import pytest

from module.config.server import CN_PACKAGE, CN_SERVER, to_package


def test_to_package_accepts_only_cn_identifier() -> None:
    assert to_package(CN_SERVER) == CN_PACKAGE
    assert to_package(CN_PACKAGE) == CN_PACKAGE

    with pytest.raises(ValueError, match="Package/server invalid"):
        to_package("com.example.other")
