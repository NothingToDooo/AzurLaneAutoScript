from module.base.utils import area_pad, crop, rgb2gray
from module.research import assets as research_assets

RESEARCH_SERIES = (
    research_assets.SERIES_1,
    research_assets.SERIES_2,
    research_assets.SERIES_3,
    research_assets.SERIES_4,
    research_assets.SERIES_5,
)
RESEARCH_SCALING = [
    424 / 558,
    491 / 558,
    1.0,
    491 / 558,
    424 / 558,
]


def match_series(image, scaling):
    image = rgb2gray(image)

    if research_assets.TEMPLATE_S8.match(image, scaling=scaling):
        return 8
    if research_assets.TEMPLATE_S7.match(image, scaling=scaling):
        return 7
    if research_assets.TEMPLATE_S6.match(image, scaling=scaling):
        return 6
    if research_assets.TEMPLATE_S4_2.match(image, scaling=scaling):
        return 4
    if research_assets.TEMPLATE_S4.match(image, scaling=scaling):
        return 4
    if research_assets.TEMPLATE_S5.match(image, scaling=scaling):
        return 5
    if research_assets.TEMPLATE_S3.match(image, scaling=scaling):
        return 3
    if research_assets.TEMPLATE_S2.match(image, scaling=scaling):
        return 2
    if research_assets.TEMPLATE_S1.match(image, scaling=scaling):
        return 1
    return 0


def get_research_series_3(image, series_button=RESEARCH_SERIES):
    """
    Args:
        image:
        series_button (list[Button]):

    Returns:
        list[int]:
    """
    return [
        match_series(crop(image, area_pad(button.area, pad=-10), copy=False), scaling)
        for scaling, button in zip(RESEARCH_SCALING, series_button, strict=True)
    ]


def get_detail_series(image):
    """
    Args:
        image:

    Returns:
        int:
    """
    return match_series(crop(image, area_pad(research_assets.SERIES_DETAIL.area, pad=-30), copy=False), scaling=1.0)
