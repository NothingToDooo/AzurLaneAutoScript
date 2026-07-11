import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import cast

import cv2
import pytest

from module.base.filter import Filter
from module.base.utils import load_image
from module.config.config_generated import GeneratedConfig
from module.config.utils import read_file
from module.research import assets as research_assets
from module.research.preset import DICT_FILTER_PRESET
from module.research.preset_generator import split_filter
from module.research.project import ResearchProject
from module.research.project_data import LIST_RESEARCH_PROJECT
from module.research.selector import FILTER_ATTR, FILTER_PRESET, FILTER_REGEX
from module.research.series import RESEARCH_SERIES_TEMPLATES, match_series

DEFAULT_S9_PRESET = "series_9_blueprint_ta152"
S9_PRESET_KEYS = {
    "series_9_ta152_only_cube",
    "series_9_ta152_only",
    "series_9_blueprint_ta152_cube",
    DEFAULT_S9_PRESET,
    "series_9_blueprint_only_cube",
    "series_9_blueprint_only",
}
S9_SHIPS = ("valparaiso", "maximmelmann", "duncan", "takahashi", "orage")
S9_D_PROJECT_NUMBERS = {
    "737",
    "781",
    "732",
    "740",
    "747",
    "337",
    "381",
    "332",
    "340",
    "347",
    "437",
    "481",
    "432",
    "440",
    "447",
    "037",
    "081",
    "032",
    "040",
    "047",
}
S8_E_PROJECT_NAMES = {
    "E-180-MI",
    "E-136-MI",
    "E-111-MI",
    "E-164-MI",
    "E-187-MI",
    "E-880-MI",
    "E-836-MI",
    "E-811-MI",
    "E-864-MI",
    "E-887-MI",
}
S8_E_PROJECT_TIMES = {
    "E-180-MI": 21600,
    "E-136-MI": 21600,
    "E-111-MI": 21600,
    "E-164-MI": 21600,
    "E-187-MI": 21600,
    "E-880-MI": 7200,
    "E-836-MI": 7200,
    "E-811-MI": 7200,
    "E-864-MI": 7200,
    "E-887-MI": 7200,
}
S9_SHIP_BY_NUMBER = {
    number: ship
    for ship, numbers in {
        "valparaiso": {"737", "337", "437", "037"},
        "maximmelmann": {"781", "381", "481", "081"},
        "duncan": {"732", "332", "432", "032"},
        "takahashi": {"740", "340", "440", "040"},
        "orage": {"747", "347", "447", "047"},
    }.items()
    for number in numbers
}
S9_PROJECT_NAMES = {
    "C-153-MI",
    "C-185-MI",
    "B-622-MI",
    "B-636-MI",
    "B-654-MI",
    "B-682-MI",
    "B-235-MI",
    "B-268-MI",
    "B-128-MI",
    "B-164-MI",
    "T-018-MI",
    "T-384-MI",
    "T-249-MI",
    "E-031-MI",
    "E-315-MI",
    "G-412-MI",
    "G-236-MI",
    "G-531-MI",
    "D-737-MI",
    "D-781-MI",
    "D-732-MI",
    "D-740-MI",
    "D-747-MI",
    "D-337-MI",
    "D-381-MI",
    "D-332-MI",
    "D-340-MI",
    "D-347-MI",
    "Q-302-MI",
    "Q-310-MI",
    "Q-351-MI",
    "Q-368-MI",
    "Q-389-MI",
    "Q-202-MI",
    "Q-210-MI",
    "Q-251-MI",
    "Q-268-MI",
    "Q-289-MI",
    "Q-002-MI",
    "Q-010-MI",
    "Q-051-MI",
    "Q-068-MI",
    "Q-089-MI",
    "H-387-MI",
    "H-339-MI",
    "C-038-RF",
    "B-351-RF",
    "B-397-RF",
    "D-437-RF",
    "D-481-RF",
    "D-432-RF",
    "D-440-RF",
    "D-447-RF",
    "H-207-RF",
    "D-037-UL",
    "D-081-UL",
    "D-032-UL",
    "D-040-UL",
    "D-047-UL",
    "Q-002-UL",
    "Q-010-UL",
    "Q-051-UL",
    "Q-068-UL",
    "Q-089-UL",
    "H-063-UL",
}


def _expected_s9_time(name: str) -> int:
    prefix, number, suffix = name.split("-")
    if suffix == "UL":
        time = 1800
    elif suffix == "RF":
        time = {"C": 43200, "B": 14400, "D": 28800, "H": 14400}[prefix]
    elif prefix == "C":
        time = {"153": 21600, "185": 28800}[number]
    elif prefix == "B":
        time = 14400
    elif prefix == "T":
        time = {"018": 10800, "384": 14400, "249": 21600}[number]
    elif prefix == "E":
        time = 7200
    elif prefix == "G":
        time = {"412": 5400, "236": 9000, "531": 14400}[number]
    elif prefix == "D":
        time = 9000 if number.startswith("7") else 18000
    elif prefix == "Q":
        time = {"3": 3600, "2": 7200, "0": 14400}[number[0]]
    else:
        time = {"387": 3600, "339": 7200}[number]
    return time


def _expected_resource_flags(name: str) -> set[str]:
    prefix, _, suffix = name.split("-")
    flags: set[str] = set()
    if prefix in {"D", "G"} or (prefix in {"Q", "H"} and suffix == "UL"):
        flags.add("need_coin")
    if prefix == "H" or (prefix == "D" and suffix == "UL"):
        flags.add("need_cube")
    if prefix == "Q":
        flags.add("need_part")
    return flags


def test_series_nine_template_is_registered_first_and_matches_itself() -> None:
    template = getattr(research_assets, "TEMPLATE_S9", None)

    assert template is not None
    assert RESEARCH_SERIES_TEMPLATES[0] == (template, 9)
    assert Path(template.file).is_file()
    template_image = load_image(template.file)
    screenshot = cv2.cvtColor(template_image, cv2.COLOR_GRAY2RGB)
    assert match_series(screenshot, scaling=1.0) == 9


def test_series_nine_project_data_is_complete_and_unique() -> None:
    project_keys = [(row["series"], row["name"]) for row in LIST_RESEARCH_PROJECT]
    series_nine = [row for row in LIST_RESEARCH_PROJECT if row["series"] == 9]
    series_eight_e = {
        row["name"] for row in LIST_RESEARCH_PROJECT if row["series"] == 8 and row["name"] in S8_E_PROJECT_NAMES
    }

    assert len(project_keys) == len(set(project_keys))
    assert {row["name"] for row in series_nine} == S9_PROJECT_NAMES
    assert series_eight_e == S8_E_PROJECT_NAMES
    assert set(ResearchProject.D_PROJECT_NUMBERS) >= S9_D_PROJECT_NUMBERS
    assert all(ResearchProject(row["name"], 9).valid for row in series_nine)


def test_series_nine_compact_fields_follow_runtime_contract() -> None:
    series_nine = [row for row in LIST_RESEARCH_PROJECT if row["series"] == 9]
    series_eight_e_times = {
        row["name"]: row["time"]
        for row in LIST_RESEARCH_PROJECT
        if row["series"] == 8 and row["name"] in S8_E_PROJECT_NAMES
    }

    assert series_eight_e_times == S8_E_PROJECT_TIMES
    for row in series_nine:
        name = cast("str", row["name"])
        prefix, number, _ = name.split("-")
        actual_flags = {flag for flag in ("need_coin", "need_cube", "need_part") if row.get(flag, False)}
        expected_equipment_amount = {"E-031-MI": 8, "E-315-MI": 15}.get(name, 0)

        assert row["time"] == _expected_s9_time(name)
        assert actual_flags == _expected_resource_flags(name)
        assert row.get("equipment_amount", 0) == expected_equipment_amount
        if prefix == "D":
            expected_ship = S9_SHIP_BY_NUMBER[number]
            expected_rarity = "dr" if expected_ship in {"valparaiso", "maximmelmann"} else "pry"
            assert row.get("ship") == expected_ship
            assert row.get("ship_rarity") == expected_rarity
        else:
            assert "ship" not in row
            assert "ship_rarity" not in row


@pytest.mark.parametrize(
    ("name", "ship", "rarity"),
    [
        ("D-737-MI", "valparaiso", "dr"),
        ("D-781-MI", "maximmelmann", "dr"),
        ("D-732-MI", "duncan", "pry"),
        ("D-740-MI", "takahashi", "pry"),
        ("D-747-MI", "orage", "pry"),
    ],
)
def test_series_nine_ship_projects(name: str, ship: str, rarity: str) -> None:
    project = ResearchProject(name, 9)

    assert project.valid is True
    assert project.ship == ship
    assert project.ship_rarity == rarity


def test_series_nine_filter_tokens_and_presets_are_valid() -> None:
    assert all(FILTER_REGEX.fullmatch(f"s9-{ship}") for ship in S9_SHIPS)
    assert DICT_FILTER_PRESET.keys() >= S9_PRESET_KEYS

    projects = [ResearchProject(row["name"], 9) for row in LIST_RESEARCH_PROJECT if row["series"] == 9]
    research_filter = Filter(FILTER_REGEX, FILTER_ATTR, FILTER_PRESET)
    for key in S9_PRESET_KEYS:
        selections = split_filter(DICT_FILTER_PRESET[key].lower())
        for selection in selections:
            if not selection.startswith("s9"):
                continue
            assert FILTER_REGEX.fullmatch(selection)
            research_filter.load(selection)
            assert research_filter.apply(projects), f"{key}: {selection}"


def test_series_nine_config_defaults_and_chinese_labels_are_generated() -> None:
    argument = read_file("./module/config/argument/argument.yaml")
    args = read_file("./module/config/argument/args.json")
    template = read_file("./config/template.json")
    i18n = read_file("./module/config/i18n/zh-CN.json")
    expected_options = [
        "custom",
        DEFAULT_S9_PRESET,
        "series_9_blueprint_only",
        "series_9_ta152_only",
    ]

    assert argument["Research"]["PresetFilter"]["value"] == DEFAULT_S9_PRESET
    assert argument["Research"]["PresetFilter"]["option"][:4] == expected_options
    assert args["Research"]["Research"]["PresetFilter"]["value"] == DEFAULT_S9_PRESET
    assert args["Research"]["Research"]["PresetFilter"]["option"][:4] == expected_options
    assert GeneratedConfig.Research_PresetFilter == DEFAULT_S9_PRESET
    assert template["Research"]["Research"]["PresetFilter"] == DEFAULT_S9_PRESET
    assert split_filter(argument["Research"]["CustomFilter"]) == split_filter(DICT_FILTER_PRESET[DEFAULT_S9_PRESET])
    assert split_filter(GeneratedConfig.Research_CustomFilter) == split_filter(DICT_FILTER_PRESET[DEFAULT_S9_PRESET])
    assert split_filter(template["Research"]["Research"]["CustomFilter"]) == split_filter(
        DICT_FILTER_PRESET[DEFAULT_S9_PRESET]
    )
    assert (
        i18n["Research"]["PresetFilter"]
        | {
            "series_9_blueprint_ta152": "九期 蓝图+Ta152",
            "series_9_blueprint_only": "九期 仅蓝图",
            "series_9_ta152_only": "九期 仅Ta152",
        }
        == i18n["Research"]["PresetFilter"]
    )


def test_research_extractor_maps_series_nine_without_import_side_effects() -> None:
    extractor_path = Path("dev_tools/research_extractor.py")
    project_data_path = Path("module/research/project_data.py")
    project_data_before = project_data_path.read_bytes()
    extractor = runpy.run_path(str(extractor_path), run_name="research_extractor_test")
    project_ship = extractor["project_ship"]
    project_type = extractor["Project"]
    expected_ships = {
        "蓝图：瓦尔帕莱索": ("valparaiso", "dr"),
        "蓝图：{namecode:565}": ("maximmelmann", "dr"),
        "蓝图：邓肯": ("duncan", "pry"),
        "蓝图：{namecode:313}": ("takahashi", "pry"),
        "蓝图：暴风雨": ("orage", "pry"),
    }

    assert project_data_path.read_bytes() == project_data_before
    for raw_name, (ship, rarity) in expected_ships.items():
        item = SimpleNamespace(name=raw_name)
        project = SimpleNamespace(name="D-000-MI", series=9, time=9000, input=[], output=[item], task="")

        assert project_ship([item]) == ship
        encoded = project_type.encode(project)
        assert encoded["ship"] == ship
        assert encoded["ship_rarity"] == rarity
