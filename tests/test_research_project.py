from module.research.project import ResearchProject


def _bare_project(series: int) -> ResearchProject:
    project = object.__new__(ResearchProject)
    project.raw_series = series
    project.name = ""
    return project


def test_research_project_normalizes_known_ocr_errors() -> None:
    project = _bare_project(series=5)

    assert project.check_name("D-349-MI") == "D-319-MI"
    assert project.check_name("LC-038-RF") == "C-038-RF"
    assert project.check_name("D-057-0C") == "D-057-UL"
    assert project.check_name("H339-MI") == "H-339-MI"


def test_research_project_resolves_real_data_fallbacks() -> None:
    examples = (
        ("002-UL", 9, "Q-002-UL"),
        ("D-185-MI", 9, "C-185-MI"),
        ("D-057-U", 2, "D-057-UL"),
    )

    for recognized, series, expected in examples:
        project = _bare_project(series)
        project.name = recognized

        rows = tuple(project.get_data(recognized, series))

        assert any(row["name"] == expected for row in rows)
