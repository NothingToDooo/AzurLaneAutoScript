from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, TypedDict, override

from module.commission.project import Commission

if TYPE_CHECKING:
    from typing import Unpack

    from module.commission.project import CommissionStatus


class _Commission(Commission):
    suffix_matches: bool

    @override
    def suffix_match(self, other: Commission, similarity: float = 0.75) -> bool:
        del other, similarity
        return self.suffix_matches


@dataclass(frozen=True)
class _CommissionSpec:
    valid: bool = True
    genre: str = "major_comm"
    status: CommissionStatus = "pending"
    category_str: str = "major"
    duration: timedelta = timedelta(hours=1)
    expire: timedelta = timedelta()
    repeat_count: int = 1
    name: str = "委托"
    suffix_matches: bool = True


class _CommissionOverrides(TypedDict, total=False):
    valid: bool
    genre: str
    status: CommissionStatus
    category_str: str
    duration: timedelta
    expire: timedelta
    repeat_count: int
    name: str
    suffix_matches: bool


def _commission(**overrides: Unpack[_CommissionOverrides]) -> _Commission:
    spec = _CommissionSpec(**overrides)
    commission = _Commission.__new__(_Commission)
    commission.valid = spec.valid
    commission.genre = spec.genre
    commission.status = spec.status
    commission.category_str = spec.category_str
    commission.duration = spec.duration
    commission.expire = spec.expire
    commission.repeat_count = spec.repeat_count
    commission.name = spec.name
    commission.suffix_matches = spec.suffix_matches
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
