import copy
from dataclasses import FrozenInstanceError
from typing import TYPE_CHECKING

import pytest

from module.config.resolved import resolve_task_config

if TYPE_CHECKING:
    from module.config.deep import DeepValue, MutableDeepData, MutableDeepValue


def _nested_items(value: MutableDeepValue) -> list[MutableDeepValue]:
    assert isinstance(value, dict)
    items = value["items"]
    assert isinstance(items, list)
    return items


def test_resolver_keeps_first_value_and_full_source_path() -> None:
    snapshot = resolve_task_config(
        task_name="Event",
        bind_chain=("General", "Alas", "Event"),
        data={
            "General": {"Shared": {"Value": "general"}},
            "Alas": {"Shared": {"Value": "alas"}},
            "Event": {"Campaign": {"Name": "D3"}},
        },
        overrides={},
    )

    assert snapshot.task_name == "Event"
    assert snapshot.bind_chain == ("General", "Alas", "Event")
    assert snapshot.Shared_Value == "general"
    assert snapshot.Campaign_Name == "D3"
    assert snapshot.source_path("Shared_Value") == "General.Shared.Value"
    assert snapshot.bound_paths == {
        "Shared_Value": "General.Shared.Value",
        "Campaign_Name": "Event.Campaign.Name",
    }


def test_resolver_marks_overrides_without_inventing_persistent_paths() -> None:
    snapshot = resolve_task_config(
        task_name="Alas",
        bind_chain=("General", "Alas"),
        data={"General": {"Shared": {"Value": "stored"}}},
        overrides={"Shared_Value": "override", "Runtime_Only": [1, 2]},
    )

    fields = snapshot.fields
    assert snapshot.Shared_Value == "override"
    assert fields["Shared_Value"].is_override is True
    assert snapshot.source_path("Shared_Value") == "General.Shared.Value"
    assert snapshot.Runtime_Only == [1, 2]
    assert fields["Runtime_Only"].is_override is True
    assert snapshot.source_path("Runtime_Only") is None
    assert "Runtime_Only" not in snapshot.bound_paths


def test_resolver_deep_copies_input_and_every_output_container() -> None:
    nested: MutableDeepData = {"items": [1, {"name": "original"}]}
    data: MutableDeepData = {"General": {"Nested": {"Value": nested}}}
    overrides: MutableDeepData = {"Runtime_List": ["original"]}
    snapshot = resolve_task_config(
        task_name="Alas",
        bind_chain=("General", "Alas"),
        data=data,
        overrides=overrides,
    )

    input_record = _nested_items(nested)[1]
    assert isinstance(input_record, dict)
    input_record["name"] = "input-mutated"
    runtime_list = overrides["Runtime_List"]
    assert isinstance(runtime_list, list)
    runtime_list.append("input-mutated")
    first = snapshot.Nested_Value
    _nested_items(first).append("output-mutated")
    second = snapshot.Nested_Value
    fields = snapshot.fields
    _nested_items(fields["Nested_Value"].value).append("field-mutated")
    paths = snapshot.bound_paths
    paths["Nested_Value"] = "changed"

    assert second == {"items": [1, {"name": "original"}]}
    assert snapshot.Nested_Value == {"items": [1, {"name": "original"}]}
    assert snapshot.Runtime_List == ["original"]
    assert snapshot.source_path("Nested_Value") == "General.Nested.Value"


def test_resolved_snapshot_is_frozen_and_deepcopy_safe() -> None:
    snapshot = resolve_task_config(
        task_name="Alas",
        bind_chain=("General", "Alas"),
        data={"General": {"Nested": {"Value": [1, 2]}}},
        overrides={},
    )

    frozen_attribute = "task_name"
    with pytest.raises(FrozenInstanceError):
        setattr(snapshot, frozen_attribute, "Other")

    cloned = copy.deepcopy(snapshot)
    assert cloned is not snapshot
    assert cloned.Nested_Value == [1, 2]


@pytest.mark.parametrize(
    "data",
    [
        {"General": []},
        {"General": {"Shared": []}},
    ],
)
def test_resolver_rejects_malformed_scope_data(data: dict[str, DeepValue]) -> None:
    with pytest.raises(TypeError, match="mapping"):
        resolve_task_config(
            task_name="Alas",
            bind_chain=("General", "Alas"),
            data=data,
            overrides={},
        )
