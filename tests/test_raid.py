import pytest

from module.exception import ScriptError
from module.ocr.ocr import Digit, DigitCounter
from module.raid.raid import HuanChangPtOcr, RaidCounter, pt_ocr, raid_name_shorten, raid_ocr


def test_raid_name_shorten_returns_asset_prefix() -> None:
    assert raid_name_shorten("raid_20200624") == "ESSEX"
    assert raid_name_shorten("raid_20260212") == "CHANGWU"


def test_raid_name_shorten_rejects_unknown_raid() -> None:
    with pytest.raises(ScriptError):
        raid_name_shorten("raid_unknown")


def test_raid_ocr_uses_configured_counter_class() -> None:
    assert isinstance(raid_ocr("raid_20200624", "easy"), RaidCounter)
    assert isinstance(raid_ocr("raid_20230118", "normal"), DigitCounter)
    assert isinstance(raid_ocr("raid_20230118", "ex"), Digit)


def test_pt_ocr_uses_configured_counter_class() -> None:
    assert isinstance(pt_ocr("raid_20220630"), Digit)
    assert isinstance(pt_ocr("raid_20240130"), HuanChangPtOcr)
