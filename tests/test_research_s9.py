import runpy
from pathlib import Path
from types import SimpleNamespace
from typing import TYPE_CHECKING

import cv2
import numpy as np

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

if TYPE_CHECKING:
    from module.config.deep import MutableDeepValue


DEFAULT_S9_PRESET = "series_9_blueprint_ta152"
S9_PRESET_KEYS = {
    "series_9_ta152_only_cube",
    "series_9_ta152_only",
    "series_9_blueprint_ta152_cube",
    DEFAULT_S9_PRESET,
    "series_9_blueprint_only_cube",
    "series_9_blueprint_only",
}
S8_PRESET_KEYS = {
    "series_8_305_only_cube",
    "series_8_305_only",
    "series_8_blueprint_305_cube",
    "series_8_blueprint_305",
    "series_8_blueprint_only_cube",
    "series_8_blueprint_only",
}


def _deep_dict(value: MutableDeepValue) -> dict[str, MutableDeepValue]:
    assert isinstance(value, dict)
    return value


def _deep_string(value: MutableDeepValue) -> str:
    assert isinstance(value, str)
    return value


def _deep_string_list(value: MutableDeepValue) -> list[str]:
    assert isinstance(value, list)
    assert all(isinstance(item, str) for item in value)
    return [item for item in value if isinstance(item, str)]


def _filter_value(value: MutableDeepValue) -> str | list[str]:
    if isinstance(value, str):
        return value
    return _deep_string_list(value)


def test_series_nine_template_is_registered_first_and_matches_itself() -> None:
    template = getattr(research_assets, "TEMPLATE_S9", None)

    assert template is not None
    assert RESEARCH_SERIES_TEMPLATES[0] == (template, 9)
    assert Path(template.file).is_file()
    template_image = load_image(template.file)
    screenshot = np.asarray(cv2.cvtColor(template_image, cv2.COLOR_GRAY2RGB), dtype=np.uint8)
    assert match_series(screenshot, scaling=1.0) == 9


def test_series_nine_project_data_is_unique_and_runtime_loadable() -> None:
    project_keys = [(row["series"], row["name"]) for row in LIST_RESEARCH_PROJECT]
    series_nine = [row for row in LIST_RESEARCH_PROJECT if row["series"] == 9]

    assert len(project_keys) == len(set(project_keys))
    assert series_nine
    assert all({"name", "series", "time"} <= row.keys() for row in series_nine)
    assert all(ResearchProject(row["name"], 9).valid for row in series_nine)


def test_series_nine_project_exposes_ship_fields() -> None:
    project = ResearchProject("D-737-MI", 9)

    assert project.valid is True
    assert project.ship == "valparaiso"
    assert project.ship_rarity == "dr"


def test_series_nine_filter_tokens_and_presets_are_executable() -> None:
    ships = {str(row["ship"]) for row in LIST_RESEARCH_PROJECT if row["series"] == 9 and "ship" in row}
    assert all(FILTER_REGEX.fullmatch(f"s9-{ship}") for ship in ships)
    assert DICT_FILTER_PRESET.keys() >= S9_PRESET_KEYS

    projects = [ResearchProject(row["name"], 9) for row in LIST_RESEARCH_PROJECT if row["series"] == 9]
    research_filter = Filter(FILTER_REGEX, FILTER_ATTR, FILTER_PRESET)
    for key in S9_PRESET_KEYS:
        for selection in split_filter(DICT_FILTER_PRESET[key].lower()):
            if not selection.startswith("s9"):
                continue
            assert FILTER_REGEX.fullmatch(selection)
            research_filter.load(selection)
            assert research_filter.apply(projects), f"{key}: {selection}"


def test_research_presets_prioritize_series_eight_rainbow_gear() -> None:
    for preset_key in sorted(S9_PRESET_KEYS | S8_PRESET_KEYS):
        selections = split_filter(DICT_FILTER_PRESET[preset_key].lower())
        rainbow_start = selections.index("s8-e-880")

        assert selections[rainbow_start : rainbow_start + 2] == ["s8-e-880", "s8-e-180"]
        if preset_key in S9_PRESET_KEYS:
            assert rainbow_start < selections.index("reset")


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

    argument_research = _deep_dict(argument["Research"])
    argument_preset = _deep_dict(argument_research["PresetFilter"])
    args_research = _deep_dict(_deep_dict(args["Research"])["Research"])
    args_preset = _deep_dict(args_research["PresetFilter"])
    template_research = _deep_dict(_deep_dict(template["Research"])["Research"])
    i18n_preset = _deep_dict(_deep_dict(i18n["Research"])["PresetFilter"])

    assert _deep_string(argument_preset["value"]) == DEFAULT_S9_PRESET
    assert _deep_string_list(argument_preset["option"])[:4] == expected_options
    assert _deep_string(args_preset["value"]) == DEFAULT_S9_PRESET
    assert _deep_string_list(args_preset["option"])[:4] == expected_options
    assert GeneratedConfig.Research_PresetFilter == DEFAULT_S9_PRESET
    assert _deep_string(template_research["PresetFilter"]) == DEFAULT_S9_PRESET
    expected_filter = split_filter(DICT_FILTER_PRESET[DEFAULT_S9_PRESET])
    assert split_filter(_filter_value(argument_research["CustomFilter"])) == expected_filter
    assert split_filter(GeneratedConfig.Research_CustomFilter) == expected_filter
    assert split_filter(_filter_value(template_research["CustomFilter"])) == expected_filter
    expected_labels = {
        "series_9_blueprint_ta152": "九期 蓝图+Ta152",
        "series_9_blueprint_only": "九期 仅蓝图",
        "series_9_ta152_only": "九期 仅Ta152",
    }
    assert all(i18n_preset.get(key) == label for key, label in expected_labels.items())


def test_research_extractor_maps_a_series_nine_ship_without_import_side_effects() -> None:
    extractor_path = Path("dev_tools/research_extractor.py")
    project_data_path = Path("module/research/project_data.py")
    project_data_before = project_data_path.read_bytes()
    extractor = runpy.run_path(str(extractor_path), run_name="research_extractor_test")
    project_ship = extractor["project_ship"]
    project_type = extractor["Project"]
    item = SimpleNamespace(name="蓝图：瓦尔帕莱索")
    project = SimpleNamespace(name="D-000-MI", series=9, time=9000, input=[], output=[item], task="")

    assert project_data_path.read_bytes() == project_data_before
    assert project_ship([item]) == "valparaiso"
    encoded = project_type.encode(project)
    assert encoded["ship"] == "valparaiso"
    assert encoded["ship_rarity"] == "dr"
