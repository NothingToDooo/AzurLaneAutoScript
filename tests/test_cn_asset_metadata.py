from module.equipment.assets import FLEET_ENTER, FLEET_ENTER_FLAGSHIP
from module.freebies.assets import OCR_DATA_KEY
from module.private_quarters.assets import PRIVATE_QUARTERS_PAGE_LOCALE_VILLA, PRIVATE_QUARTERS_SHIP_NAKHIMOV
from module.private_quarters.private_quarters import PrivateQuarters


def test_ocr_data_key_cn_metadata_matches_updated_asset() -> None:
    assert (
        OCR_DATA_KEY.area,
        OCR_DATA_KEY.color,
        OCR_DATA_KEY.button,
        OCR_DATA_KEY.file,
    ) == (
        (133, 39, 250, 72),
        (82, 80, 91),
        (133, 39, 250, 72),
        "./assets/cn/freebies/OCR_DATA_KEY.png",
    )


def test_fleet_enter_cn_metadata_matches_updated_assets() -> None:
    assert (
        FLEET_ENTER.area,
        FLEET_ENTER.color,
        FLEET_ENTER.button,
        FLEET_ENTER.file,
    ) == (
        (502, 474, 517, 489),
        (165, 193, 232),
        (502, 474, 517, 489),
        "./assets/cn/equipment/FLEET_ENTER.png",
    )
    assert (
        FLEET_ENTER_FLAGSHIP.area,
        FLEET_ENTER_FLAGSHIP.color,
        FLEET_ENTER_FLAGSHIP.button,
        FLEET_ENTER_FLAGSHIP.file,
    ) == (
        (577, 277, 605, 291),
        (219, 196, 174),
        (577, 277, 605, 291),
        "./assets/cn/equipment/FLEET_ENTER_FLAGSHIP.png",
    )


def test_nakhimov_cn_private_quarters_support_matches_updated_assets() -> None:
    assert "nakhimov" not in PrivateQuarters.not_supported_ships
    assert (
        PRIVATE_QUARTERS_PAGE_LOCALE_VILLA.area,
        PRIVATE_QUARTERS_PAGE_LOCALE_VILLA.color,
        PRIVATE_QUARTERS_PAGE_LOCALE_VILLA.button,
        PRIVATE_QUARTERS_PAGE_LOCALE_VILLA.file,
    ) == (
        (23, 502, 99, 528),
        (202, 203, 203),
        (23, 502, 99, 528),
        "./assets/cn/private_quarters/PRIVATE_QUARTERS_PAGE_LOCALE_VILLA.png",
    )
    assert (
        PRIVATE_QUARTERS_SHIP_NAKHIMOV.area,
        PRIVATE_QUARTERS_SHIP_NAKHIMOV.color,
        PRIVATE_QUARTERS_SHIP_NAKHIMOV.button,
        PRIVATE_QUARTERS_SHIP_NAKHIMOV.file,
    ) == (
        (944, 386, 976, 431),
        (202, 197, 182),
        (944, 386, 976, 431),
        "./assets/cn/private_quarters/PRIVATE_QUARTERS_SHIP_NAKHIMOV.png",
    )
