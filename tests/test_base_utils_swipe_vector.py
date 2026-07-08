from module.base.utils import random_rectangle_vector_opted


def _fixed_points(points):
    point_iter = iter(points)

    def random_point(_area, _n=3):
        return next(point_iter)

    return random_point


def test_random_rectangle_vector_uses_random_end_point(monkeypatch) -> None:
    monkeypatch.setattr("module.base.utils.random_rectangle_point", _fixed_points([(0, 0), (80, 50)]))

    assert random_rectangle_vector_opted((10, 0), box=(0, 0, 100, 100), padding=0) == ((70, 50), (80, 50))


def test_random_rectangle_vector_prefers_whitelist_end_point(monkeypatch) -> None:
    monkeypatch.setattr("module.base.utils.random_rectangle_point", _fixed_points([(0, 0), (20, 30)]))

    assert random_rectangle_vector_opted(
        (10, 0),
        box=(0, 0, 100, 100),
        padding=0,
        whitelist_area=[(10, 10, 30, 40)],
    ) == ((10, 30), (20, 30))


def test_random_rectangle_vector_retries_blacklisted_path(monkeypatch) -> None:
    monkeypatch.setattr(
        "module.base.utils.random_rectangle_point",
        _fixed_points([(0, 0), (20, 20), (50, 50)]),
    )

    assert random_rectangle_vector_opted(
        (10, 0),
        box=(0, 0, 100, 100),
        padding=0,
        blacklist_area=[(19, 19, 21, 21)],
    ) == ((40, 50), (50, 50))
