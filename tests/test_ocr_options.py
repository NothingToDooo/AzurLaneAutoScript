from module.ocr.ocr import Digit, Ocr, OcrOptions


def test_ocr_options_accepts_existing_keyword_settings() -> None:
    ocr = Ocr([], lang="cnocr", threshold=256, name="commission")

    assert ocr.lang == "cnocr"
    assert ocr.threshold == 256
    assert ocr.name == "commission"


def test_digit_options_keep_default_alphabet() -> None:
    digit = Digit([], options=OcrOptions(letter=(1, 2, 3), threshold=64, name="digit"))

    assert digit.letter == (1, 2, 3)
    assert digit.threshold == 64
    assert digit.name == "digit"
    assert digit.alphabet == "0123456789IDSB"


def test_digit_keyword_settings_override_default_alphabet() -> None:
    digit = Digit([], alphabet="0123")

    assert digit.alphabet == "0123"
