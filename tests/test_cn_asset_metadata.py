from module.equipment.assets import FLEET_ENTER, FLEET_ENTER_FLAGSHIP
from module.freebies.assets import OCR_DATA_KEY


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
