from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING

from module.config.deep import DeepValue, deep_get, deep_iter
from module.config.utils import path_to_arg

if TYPE_CHECKING:
    from collections.abc import Callable, Iterator, Mapping

    from module.config.resolved import ResolvedField


@dataclass(slots=True)
class SettingOutputContext:
    task: str
    group_name: str
    arg_name: str
    arg_config: dict
    config: DeepValue
    translate: Callable[..., str]
    resolved_field: ResolvedField | None


@dataclass(slots=True)
class GroupOutputContext:
    task: str
    group_name: str
    arg_dict: DeepValue
    config: DeepValue
    translate: Callable[..., str]
    resolved_fields: Mapping[str, ResolvedField]


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


def _setting_help(context: SettingOutputContext, arg_help: str) -> str | None:
    field = context.resolved_field
    if field is None:
        return arg_help or None

    source_path = field.source_path or context.translate("Gui.Text.ConfigRuntime")
    source_help = context.translate("Gui.Text.ConfigSource", source_path)
    if field.is_override:
        source_help = f"{source_help} · {context.translate('Gui.Text.ConfigOverride')}"
    return "\n".join(part for part in (arg_help, source_help) if part)


def build_setting_output_kwargs(context: SettingOutputContext) -> dict | None:
    output_kwargs = context.arg_config.copy()

    display: str | None = output_kwargs.pop("display", None)
    if display == "hide":
        return None
    if display == "disabled":
        output_kwargs["disabled"] = True

    output_kwargs["widget_type"] = output_kwargs.pop("type")
    output_kwargs["name"] = f"{context.task}_{context.group_name}_{context.arg_name}"
    output_kwargs["title"] = context.translate(f"{context.group_name}.{context.arg_name}.name")

    value = deep_get(context.config, [context.task, context.group_name, context.arg_name], output_kwargs["value"])
    value = str(value) if isinstance(value, datetime) else value
    output_kwargs["value"] = value

    options = output_kwargs.pop("option", [])
    output_kwargs["options"] = options
    if _should_skip_setting(context.task, context.group_name, context.arg_name, output_kwargs["widget_type"], options):
        return None
    _normalize_select_with_single_bold_option(output_kwargs, options)

    output_kwargs["options_label"] = [
        context.translate(f"{context.group_name}.{context.arg_name}.{option}") for option in options
    ]

    arg_help = context.translate(f"{context.group_name}.{context.arg_name}.help")
    output_kwargs["help"] = _setting_help(context, arg_help)
    output_kwargs["invalid_feedback"] = context.translate("Gui.Text.InvalidFeedBack", value)
    return output_kwargs


def iter_group_output_kwargs(context: GroupOutputContext) -> Iterator[dict]:
    for arg, arg_config in deep_iter(context.arg_dict, depth=1):
        if not isinstance(arg_config, dict):
            message = f"Setting {'.'.join(arg)} must be a mapping"
            raise TypeError(message)
        output_kwargs = build_setting_output_kwargs(
            SettingOutputContext(
                task=context.task,
                group_name=context.group_name,
                arg_name=arg[0],
                arg_config=arg_config,
                config=context.config,
                translate=context.translate,
                resolved_field=context.resolved_fields.get(path_to_arg(f"{context.group_name}.{arg[0]}")),
            )
        )
        if output_kwargs is not None:
            yield output_kwargs
