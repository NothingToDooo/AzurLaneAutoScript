from datetime import datetime
from typing import TYPE_CHECKING

from module.config.deep import deep_get, deep_iter

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator


def _should_skip_setting(task: str, group_name: str, arg_name: str, widget_type: str, options: list) -> bool:
    return (
        task == "GemsFarming"
        and group_name == "Campaign"
        and arg_name == "Event"
        and widget_type == "select"
        and len(options) == 1
    )


def _normalize_select_with_single_bold_option(output_kwargs: dict, options: list) -> None:
    if output_kwargs["widget_type"] != "select" or len(options) != 1:
        return
    if options[0] in output_kwargs.get("option_bold", []):
        output_kwargs["widget_type"] = "state"


def build_setting_output_kwargs(
    *,
    task: str,
    group_name: str,
    arg_name: str,
    arg_config: dict,
    config: dict,
    translate: Callable[..., str],
) -> dict | None:
    output_kwargs = arg_config.copy()

    display: str | None = output_kwargs.pop("display", None)
    if display == "hide":
        return None
    if display == "disabled":
        output_kwargs["disabled"] = True

    output_kwargs["widget_type"] = output_kwargs.pop("type")
    output_kwargs["name"] = f"{task}_{group_name}_{arg_name}"
    output_kwargs["title"] = translate(f"{group_name}.{arg_name}.name")

    value = deep_get(config, [task, group_name, arg_name], output_kwargs["value"])
    value = str(value) if isinstance(value, datetime) else value
    output_kwargs["value"] = value

    options = output_kwargs.pop("option", [])
    output_kwargs["options"] = options
    if _should_skip_setting(task, group_name, arg_name, output_kwargs["widget_type"], options):
        return None
    _normalize_select_with_single_bold_option(output_kwargs, options)

    output_kwargs["options_label"] = [translate(f"{group_name}.{arg_name}.{option}") for option in options]

    arg_help = translate(f"{group_name}.{arg_name}.help")
    output_kwargs["help"] = arg_help or None
    output_kwargs["invalid_feedback"] = translate("Gui.Text.InvalidFeedBack", value)
    return output_kwargs


def iter_group_output_kwargs(
    *,
    task: str,
    group_name: str,
    arg_dict: dict,
    config: dict,
    translate: Callable[..., str],
) -> Iterator[dict]:
    for arg, arg_config in deep_iter(arg_dict, depth=1):
        output_kwargs = build_setting_output_kwargs(
            task=task,
            group_name=group_name,
            arg_name=arg[0],
            arg_config=arg_config,
            config=config,
            translate=translate,
        )
        if output_kwargs is not None:
            yield output_kwargs
