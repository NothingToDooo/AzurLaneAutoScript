from datetime import datetime

from module.config.resolved import ResolvedField
from module.webui.setting_form_utils import (
    GroupOutputContext,
    SettingOutputContext,
    build_setting_output_kwargs,
    iter_group_output_kwargs,
)


def _translate(key: str, *args: str) -> str:
    if key.endswith(".help"):
        return ""
    if args:
        return f"{key}:{args[0]}"
    return key


def test_build_setting_output_kwargs_normalizes_visible_input() -> None:
    output = build_setting_output_kwargs(
        SettingOutputContext(
            task="Demo",
            group_name="Scheduler",
            arg_name="NextRun",
            arg_config={"type": "input", "value": "default", "option": ["a", "b"]},
            config={"Demo": {"Scheduler": {"NextRun": datetime(2026, 1, 2, 3, 4, 5)}}},
            translate=_translate,
            resolved_field=None,
        )
    )

    assert output == {
        "widget_type": "input",
        "name": "Demo_Scheduler_NextRun",
        "title": "Scheduler.NextRun.name",
        "value": "2026-01-02 03:04:05",
        "options": ["a", "b"],
        "options_label": ["Scheduler.NextRun.a", "Scheduler.NextRun.b"],
        "help": None,
        "invalid_feedback": "Gui.Text.InvalidFeedBack:2026-01-02 03:04:05",
    }


def test_build_setting_output_kwargs_skips_hidden_and_gems_single_event() -> None:
    hidden = build_setting_output_kwargs(
        SettingOutputContext(
            task="Demo",
            group_name="Group",
            arg_name="Hidden",
            arg_config={"type": "input", "value": "", "display": "hide"},
            config={},
            translate=_translate,
            resolved_field=None,
        )
    )
    gems_event = build_setting_output_kwargs(
        SettingOutputContext(
            task="GemsFarming",
            group_name="Campaign",
            arg_name="Event",
            arg_config={"type": "select", "value": "event", "option": ["event"]},
            config={},
            translate=_translate,
            resolved_field=None,
        )
    )

    assert hidden is None
    assert gems_event is None


def test_build_setting_output_kwargs_marks_disabled_and_single_bold_select_as_state() -> None:
    output = build_setting_output_kwargs(
        SettingOutputContext(
            task="Demo",
            group_name="Campaign",
            arg_name="Event",
            arg_config={
                "type": "select",
                "value": "event",
                "display": "disabled",
                "option": ["event"],
                "option_bold": ["event"],
            },
            config={},
            translate=_translate,
            resolved_field=None,
        )
    )

    assert output is not None
    assert output["disabled"] is True
    assert output["widget_type"] == "state"


def test_build_setting_output_kwargs_appends_source_and_runtime_override() -> None:
    output = build_setting_output_kwargs(
        SettingOutputContext(
            task="Demo",
            group_name="Group",
            arg_name="Value",
            arg_config={"type": "input", "value": "default"},
            config={"Demo": {"Group": {"Value": "configured"}}},
            translate=_translate,
            resolved_field=ResolvedField(
                value="runtime",
                source_path="General.Group.Value",
                is_override=True,
            ),
        )
    )

    assert output is not None
    assert output["help"] == "Gui.Text.ConfigSource:General.Group.Value · Gui.Text.ConfigOverride"


def test_iter_group_output_kwargs_yields_only_visible_settings() -> None:
    outputs = list(
        iter_group_output_kwargs(
            GroupOutputContext(
                task="Demo",
                group_name="Group",
                arg_dict={
                    "Visible": {"type": "input", "value": "ok"},
                    "Hidden": {"type": "input", "value": "skip", "display": "hide"},
                },
                config={},
                translate=_translate,
                resolved_fields={
                    "Group_Visible": ResolvedField(
                        value="ok",
                        source_path=None,
                        is_override=True,
                    )
                },
            )
        )
    )

    assert [output["name"] for output in outputs] == ["Demo_Group_Visible"]
    assert outputs[0]["help"] == "Gui.Text.ConfigSource:Gui.Text.ConfigRuntime · Gui.Text.ConfigOverride"
