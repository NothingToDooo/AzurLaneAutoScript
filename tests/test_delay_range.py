from datetime import timedelta
from typing import cast

import pytest

from module.application import DelayRange, DelaySampler


def test_delay_range_requires_positive_ordered_integer_bounds() -> None:
    with pytest.raises(ValueError, match="lower_seconds must not exceed upper_seconds"):
        DelayRange(lower_seconds=120, upper_seconds=60)
    with pytest.raises(ValueError, match="lower_seconds must be positive"):
        DelayRange(lower_seconds=0, upper_seconds=60)
    with pytest.raises(TypeError, match="upper_seconds must be an integer"):
        DelayRange(lower_seconds=60, upper_seconds=cast("int", 120.0))


def test_delay_sampler_averages_three_inclusive_integer_draws() -> None:
    draws = iter((60, 90, 120, 120, 120, 120))
    bounds: list[tuple[int, int]] = []

    def randint(lower: int, upper: int) -> int:
        bounds.append((lower, upper))
        return next(draws)

    sampler = DelaySampler(randint=randint)
    delay = DelayRange(lower_seconds=60, upper_seconds=120)

    assert sampler.sample(delay) == timedelta(seconds=90)
    assert sampler.sample(delay) == timedelta(seconds=120)
    assert bounds == [(60, 120)] * 6


def test_delay_sampler_does_not_draw_for_a_fixed_delay() -> None:
    sampler = DelaySampler(randint=lambda _lower, _upper: pytest.fail("fixed delay must not draw"))

    assert sampler.sample(DelayRange(lower_seconds=90, upper_seconds=90)) == timedelta(seconds=90)
