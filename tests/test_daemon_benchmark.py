import pytest

from module.daemon.benchmark import Benchmark


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        ("Failed", "Failed"),
        (0.010, "Insane Fast"),
        (0.025, "Ultra Fast"),
        (0.100, "Very Fast"),
        (0.200, "Fast"),
        (0.300, "Medium"),
        (0.500, "Slow"),
        (0.750, "Very Slow"),
        (1.000, "Ultra Slow"),
    ],
)
def test_evaluate_screenshot(cost, expected: str) -> None:
    assert Benchmark.evaluate_screenshot(cost).plain == expected


@pytest.mark.parametrize(
    ("cost", "expected"),
    [
        ("Failed", "Failed"),
        (0.050, "Fast"),
        (0.100, "Medium"),
        (0.200, "Slow"),
        (0.400, "Very Slow"),
    ],
)
def test_evaluate_click(cost, expected: str) -> None:
    assert Benchmark.evaluate_click(cost).plain == expected
