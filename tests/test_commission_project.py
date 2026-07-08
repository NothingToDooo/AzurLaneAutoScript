from datetime import timedelta

from module.commission.project import Commission


def _commission(**overrides):
    commission = Commission.__new__(Commission)
    attrs = {
        "valid": True,
        "genre": "major_comm",
        "status": "pending",
        "category_str": "major",
        "duration": timedelta(hours=1),
        "expire": timedelta(seconds=0),
        "repeat_count": 1,
        "name": "委托",
    }
    attrs.update(overrides)
    for key, value in attrs.items():
        setattr(commission, key, value)

    def suffix_match(_other):
        return attrs.get("suffix_matches", True)

    commission.suffix_match = suffix_match
    return commission


def test_commission_eq_accepts_matching_project_with_duration_tolerance() -> None:
    first = _commission()
    second = _commission(duration=timedelta(hours=1, seconds=119))

    assert first == second


def test_commission_eq_rejects_project_outside_duration_tolerance() -> None:
    first = _commission()
    second = _commission(duration=timedelta(hours=1, seconds=121))

    assert first != second


def test_commission_eq_requires_urgent_box_tags_to_match() -> None:
    first = _commission(genre="urgent_box", category_str="urgent", name="NYB要员护卫")
    second = _commission(genre="urgent_box", category_str="urgent", name="要员护卫")

    assert first != second


def test_commission_eq_requires_suffix_for_daily_and_extra_oil() -> None:
    daily = _commission(category_str="daily", suffix_matches=False)
    extra = _commission(genre="extra_oil", category_str="extra", suffix_matches=False)

    assert daily != _commission(category_str="daily")
    assert extra != _commission(genre="extra_oil", category_str="extra")
