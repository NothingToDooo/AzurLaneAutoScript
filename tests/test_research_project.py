import pytest

import module.research.project as research_project
from module.research.project import ResearchProject


def _bare_project(series: int = 5) -> ResearchProject:
    project = object.__new__(ResearchProject)
    project.raw_series = series
    project.name = ""
    return project


def test_research_project_check_name_normalizes_known_ocr_errors() -> None:
    project = _bare_project(series=5)

    assert project.check_name("D-349-MI") == "D-319-MI"
    assert project.check_name("LC-038-RF") == "C-038-RF"
    assert project.check_name("D-057-0C") == "D-057-UL"
    assert project.check_name("H339-MI") == "H-339-MI"


def test_research_project_get_data_tries_digit_name_prefixes(monkeypatch: pytest.MonkeyPatch) -> None:
    data = [{"series": 4, "name": "Q-057-UL"}]
    project = _bare_project(series=4)
    project.name = "057-UL"
    monkeypatch.setattr(research_project, "LIST_RESEARCH_PROJECT", data)

    assert list(project.get_data("057-UL", 4)) == data
    assert project.name == "Q-057-UL"


def test_research_project_get_data_tries_c_when_d_is_not_found(monkeypatch: pytest.MonkeyPatch) -> None:
    data = [{"series": 3, "name": "C-185-MI"}]
    project = _bare_project(series=3)
    project.name = "D-185-MI"
    monkeypatch.setattr(research_project, "LIST_RESEARCH_PROJECT", data)

    assert list(project.get_data("D-185-MI", 3)) == data
    assert project.name == "C-185-MI"


def test_research_project_get_data_matches_trimmed_suffix(monkeypatch: pytest.MonkeyPatch) -> None:
    data = [{"series": 2, "name": "D-057-UL"}]
    project = _bare_project(series=2)
    project.name = "D-057-U"
    monkeypatch.setattr(research_project, "LIST_RESEARCH_PROJECT", data)

    assert list(project.get_data("D-057-U", 2)) == data


def test_research_project_get_data_has_no_hidden_return_value(monkeypatch: pytest.MonkeyPatch) -> None:
    project = _bare_project(series=5)
    monkeypatch.setattr(research_project, "LIST_RESEARCH_PROJECT", [])
    data = project.get_data("X-000-X", 5)

    with pytest.raises(StopIteration) as stopped:
        next(data)

    assert stopped.value.value is None
