import pytest

from module.config.server import CN_PACKAGE, CN_SERVER, VALID_PACKAGE, to_package


def test_to_package_accepts_only_cn_identifier() -> None:
    assert to_package(CN_SERVER) == CN_PACKAGE
    assert to_package(CN_PACKAGE) == CN_PACKAGE

    with pytest.raises(ValueError, match="Package/server invalid"):
        to_package("com.example.other")


def test_valid_package_exposes_single_cn_package() -> None:
    assert VALID_PACKAGE == {CN_PACKAGE: CN_SERVER}
