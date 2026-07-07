import pytest

from module.base.runtime_random import RuntimeRandom


def test_seeded_generator_repeats_uniform_values():
    first = RuntimeRandom(seed=20260707).uniform(-2.0, 2.0, size=5)
    second = RuntimeRandom(seed=20260707).uniform(-2.0, 2.0, size=5)

    assert first.tolist() == second.tolist()
    assert (first >= -2.0).all()
    assert (first < 2.0).all()


def test_chance_has_clear_probability_boundaries():
    runtime_random = RuntimeRandom(seed=1)

    assert not runtime_random.chance(0.0)
    assert runtime_random.chance(1.0)


def test_chance_rejects_invalid_probability():
    runtime_random = RuntimeRandom(seed=1)

    with pytest.raises(ValueError):
        runtime_random.chance(-0.01)

    with pytest.raises(ValueError):
        runtime_random.chance(1.01)
