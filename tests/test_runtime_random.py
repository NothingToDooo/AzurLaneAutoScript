import pytest

from module.base.runtime_random import RuntimeRandom


def test_seeded_generator_repeats_uniform_values() -> None:
    first = RuntimeRandom(seed=20260707).uniform(-2.0, 2.0, size=5)
    second = RuntimeRandom(seed=20260707).uniform(-2.0, 2.0, size=5)

    assert first.tolist() == second.tolist()
    assert (first >= -2.0).all()
    assert (first < 2.0).all()


def test_chance_has_clear_probability_boundaries() -> None:
    runtime_random = RuntimeRandom(seed=1)

    assert not runtime_random.chance(0.0)
    assert runtime_random.chance(1.0)


def test_chance_rejects_invalid_probability() -> None:
    runtime_random = RuntimeRandom(seed=1)

    with pytest.raises(ValueError, match="probability must be between 0 and 1"):
        runtime_random.chance(-0.01)

    with pytest.raises(ValueError, match="probability must be between 0 and 1"):
        runtime_random.chance(1.01)
