from typing import TYPE_CHECKING, cast, override

import numpy as np
import pytest

from module.base.button import Button
from module.campaign.campaign_ocr import CampaignOcr
from module.exception import CampaignNameError

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray
    from module.device.device import Device


_IMAGE = np.zeros((720, 1280, 3), dtype=np.uint8)
_STAGE_BUTTON = Button(
    area=(100, 200, 140, 240),
    color=(255, 255, 255),
    button=(100, 200, 140, 240),
    name="1-1",
)


class _Device:
    def __init__(self) -> None:
        self.image = _IMAGE
        self.screenshots = 0

    def screenshot(self) -> ImageArray:
        self.screenshots += 1
        return self.image


class _CampaignOcrHarness(CampaignOcr):
    def __init__(self, outcomes: list[BaseException | None]) -> None:
        self.outcomes = outcomes
        self.images: list[ImageArray] = []
        self.test_device = _Device()
        self.device = cast("Device", self.test_device)
        self.stage_entrance = {}

    @override
    def _get_stage_name(self, image: ImageArray) -> None:
        self.images.append(image)
        outcome = self.outcomes.pop(0)
        if outcome is not None:
            raise outcome
        self.campaign_chapter = "1"
        self.stage_entrance = {"1-1": _STAGE_BUTTON}

    @override
    def handle_get_chapter_additional(self) -> bool:
        return False


def test_try_update_stage_entrances_publishes_successful_ocr_state() -> None:
    campaign = _CampaignOcrHarness([None])

    assert campaign.try_update_stage_entrances(_IMAGE) is True
    assert campaign.campaign_chapter == "1"
    assert campaign.stage_entrance == {"1-1": _STAGE_BUTTON}
    assert campaign.images == [_IMAGE]


@pytest.mark.parametrize("error", [IndexError(), CampaignNameError()], ids=["index", "campaign-name"])
def test_try_update_stage_entrances_normalizes_expected_ocr_failures(error: BaseException) -> None:
    campaign = _CampaignOcrHarness([error])

    assert campaign.try_update_stage_entrances(_IMAGE) is False
    assert campaign.images == [_IMAGE]


def test_get_chapter_index_retries_through_public_stage_ocr_boundary() -> None:
    campaign = _CampaignOcrHarness([IndexError(), None])

    assert campaign.get_chapter_index() == 1
    assert campaign.images == [_IMAGE, _IMAGE]
    assert campaign.test_device.screenshots == 1
