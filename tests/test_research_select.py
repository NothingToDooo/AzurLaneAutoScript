from types import SimpleNamespace

from module.research.research import RewardResearch
from module.research.selector import ResearchSelector


class _ResearchSelectContext(RewardResearch):
    def __init__(self) -> None:
        self.enforce = False
        self.calls = []
        self.reset_result = False
        self.start_result = None
        self.delay_result = False

    def research_enforce(self, add_queue=True):
        self.calls.append(("enforce", add_queue))
        return "enforced"

    def research_reset(self):
        self.calls.append(("reset", None))
        return self.reset_result

    def research_sort_shortest(self, enforce):
        self.calls.append(("sort_shortest", enforce))
        return []

    def research_sort_cheapest(self, enforce):
        self.calls.append(("sort_cheapest", enforce))
        return []

    def research_project_start_with_requirements(self, project, add_queue=True):
        self.calls.append(("start", project, add_queue))
        return self.start_result

    def research_delay_check(self):
        self.calls.append(("delay", None))
        return self.delay_result


class _ResearchCheckContext(ResearchSelector):
    def __init__(self) -> None:
        self.config = SimpleNamespace(
            Research_UseCube="always_use",
            Research_UseCoin="always_use",
            Research_UsePart="always_use",
        )
        self.storage_has_boxes = True

    def check_for_test(self, project, *, enforce=False):
        return self._research_check(project, enforce=enforce)


def _project(**kwargs):
    project = SimpleNamespace(
        valid=True,
        duration=1,
        need_cube=False,
        need_coin=False,
        need_part=False,
        genre="C",
        equipment_amount=0,
    )
    for key, value in kwargs.items():
        setattr(project, key, value)
    return project


def test_research_select_empty_priority_enforces_filter() -> None:
    context = _ResearchSelectContext()

    assert context.research_select([], add_queue=False) == "enforced"
    assert context.calls == [("enforce", False)]


def test_research_select_reset_returns_false_after_reset() -> None:
    context = _ResearchSelectContext()
    context.reset_result = True

    assert context.research_select(["reset"]) is False
    assert context.calls == [("reset", None)]


def test_research_select_shortest_preset_runs_nested_selection() -> None:
    context = _ResearchSelectContext()

    assert context.research_select(["shortest"]) is True
    assert context.calls == [
        ("sort_shortest", False),
        ("enforce", True),
    ]


def test_research_select_enforces_cube_and_cognition_projects() -> None:
    context = _ResearchSelectContext()
    project = SimpleNamespace(genre="C")

    assert context.research_select([project]) == "enforced"
    assert context.calls == [("enforce", True)]


def test_research_select_allows_delay_when_start_conditions_are_missing() -> None:
    context = _ResearchSelectContext()
    context.start_result = False
    context.delay_result = True
    project = SimpleNamespace(genre="B")

    assert context.research_select([project]) is True
    assert context.calls == [
        ("start", project, True),
        ("delay", None),
    ]


def test_research_check_rejects_invalid_project() -> None:
    context = _ResearchCheckContext()

    assert context.check_for_test(_project(valid=False)) is False


def test_research_check_accepts_normal_project() -> None:
    context = _ResearchCheckContext()

    assert context.check_for_test(_project()) is True


def test_research_check_rejects_disabled_resource() -> None:
    context = _ResearchCheckContext()
    context.config.Research_UseCube = "do_not_use"

    assert context.check_for_test(_project(need_cube=True)) is False


def test_research_check_rejects_resource_when_only_no_project_without_enforce() -> None:
    context = _ResearchCheckContext()
    context.config.Research_UseCoin = "only_no_project"
    project = _project(need_coin=True)

    assert context.check_for_test(project) is False
    assert context.check_for_test(project, enforce=True) is True


def test_research_check_allows_only_half_hour_resource_without_enforce() -> None:
    context = _ResearchCheckContext()
    context.config.Research_UsePart = "only_05_hour"

    assert context.check_for_test(_project(need_part=True, duration=1)) is False
    assert context.check_for_test(_project(need_part=True, duration=0.5)) is True
    assert context.check_for_test(_project(need_part=True, duration=1), enforce=True) is True


def test_research_check_rejects_blocked_genres() -> None:
    context = _ResearchCheckContext()

    assert context.check_for_test(_project(genre="B")) is False
    assert context.check_for_test(_project(genre="t")) is False


def test_research_check_rejects_equipment_research_without_boxes() -> None:
    context = _ResearchCheckContext()
    context.storage_has_boxes = False

    assert context.check_for_test(_project(genre="E", equipment_amount=1)) is False
    assert context.check_for_test(_project(genre="E", equipment_amount=0)) is True
