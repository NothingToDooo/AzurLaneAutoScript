from types import SimpleNamespace
from typing import TypedDict, Unpack

import pytest

from module.research.project import ResearchProject
from module.research.selector import ResearchSelector


class _ResearchCheckContext(ResearchSelector):
    config: SimpleNamespace

    def __init__(self) -> None:
        self.config = SimpleNamespace(
            Research_UseCube="always_use",
            Research_UseCoin="always_use",
            Research_UsePart="always_use",
        )
        self.storage_has_boxes = True

    def check_for_test(self, project: ResearchProject, *, enforce: bool = False) -> bool:
        return self._research_check(project, enforce=enforce)


class _ProjectOverrides(TypedDict, total=False):
    valid: bool
    duration: float
    need_cube: bool
    need_coin: bool
    need_part: bool
    genre: str
    equipment_amount: int


def _project(**kwargs: Unpack[_ProjectOverrides]) -> ResearchProject:
    project = object.__new__(ResearchProject)
    project.valid = True
    project.duration = 1
    project.need_cube = False
    project.need_coin = False
    project.need_part = False
    project.genre = "C"
    project.equipment_amount = 0
    for key, value in kwargs.items():
        setattr(project, key, value)
    return project


@pytest.mark.parametrize(
    ("project_overrides", "config_overrides", "has_boxes", "enforce", "expected"),
    [
        ({}, {}, True, False, True),
        ({"valid": False}, {}, True, False, False),
        ({"need_cube": True}, {"Research_UseCube": "do_not_use"}, True, False, False),
        ({"need_coin": True}, {"Research_UseCoin": "only_no_project"}, True, False, False),
        ({"need_coin": True}, {"Research_UseCoin": "only_no_project"}, True, True, True),
        ({"need_part": True, "duration": 0.5}, {"Research_UsePart": "only_05_hour"}, True, False, True),
        ({"genre": "B"}, {}, True, False, False),
        ({"genre": "E", "equipment_amount": 1}, {}, False, False, False),
    ],
)
def test_research_project_selection_rules(
    project_overrides: _ProjectOverrides,
    config_overrides: dict[str, str],
    *,
    has_boxes: bool,
    enforce: bool,
    expected: bool,
) -> None:
    context = _ResearchCheckContext()
    context.storage_has_boxes = has_boxes
    for name, value in config_overrides.items():
        setattr(context.config, name, value)

    assert context.check_for_test(_project(**project_overrides), enforce=enforce) is expected
