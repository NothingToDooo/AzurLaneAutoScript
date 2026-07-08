import pytest

from module.exception import ScriptError
from module.os.globe_zone import ZoneManager


def test_name_to_zone_accepts_zone_instance() -> None:
    manager = ZoneManager()
    zone = manager.name_to_zone(154)

    assert manager.name_to_zone(zone) is zone


def test_name_to_zone_accepts_numeric_id_and_digit_string() -> None:
    manager = ZoneManager()

    assert manager.name_to_zone(154).zone_id == 154
    assert manager.name_to_zone("154").zone_id == 154


def test_name_to_zone_accepts_cn_name_without_spaces() -> None:
    manager = ZoneManager()
    zone = manager.name_to_zone(154)

    assert manager.name_to_zone(f" {zone.cn} ").zone_id == 154


def test_name_to_zone_maps_arbiter_keywords_to_center_zone() -> None:
    manager = ZoneManager()

    assert manager.name_to_zone("困难 仲裁者").zone_id == 154


def test_name_to_zone_rejects_unknown_name() -> None:
    manager = ZoneManager()

    with pytest.raises(ScriptError):
        manager.name_to_zone("不存在的海域")
