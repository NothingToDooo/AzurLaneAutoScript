from types import SimpleNamespace

from module.research.research import RewardResearch


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
