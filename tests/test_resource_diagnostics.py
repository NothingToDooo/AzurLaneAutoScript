import sys
from typing import TYPE_CHECKING

import module.base.resource as resource_module
from module.base.resource import Resource, ResourceSnapshot, ResourceTypeSnapshot

if TYPE_CHECKING:
    import pytest


class _LazyResource(Resource):
    def __init__(self) -> None:
        self.image_reads = 0

    @property
    def image(self) -> object:
        self.image_reads += 1
        return object()


class _TrackedResource(Resource):
    def __init__(self, name: str, *, loaded: bool, unload_on_release: bool = True) -> None:
        self.name = name
        self.image: object | None = object() if loaded else None
        self.unload_on_release = unload_on_release
        self.release_calls = 0

    def __str__(self) -> str:
        return self.name

    def resource_release(self) -> None:
        super().resource_release()
        if self.unload_on_release:
            self.image = None
        self.release_calls += 1


def test_resource_snapshot_is_immutable_stable_and_does_not_load_lazy_properties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lazy = _LazyResource()
    loaded = _TrackedResource("loaded", loaded=True)
    unloaded = _TrackedResource("unloaded", loaded=False)
    monkeypatch.setattr(Resource, "instances", {"lazy": lazy, "loaded": loaded, "unloaded": unloaded})
    monkeypatch.setattr(Resource, "last_released", 2)

    before = vars(lazy).copy()
    snapshot = Resource.snapshot()

    assert snapshot == ResourceSnapshot(
        registered=3,
        loaded=1,
        by_type=(
            ResourceTypeSnapshot(resource_type="_LazyResource", registered=1, loaded=0),
            ResourceTypeSnapshot(resource_type="_TrackedResource", registered=2, loaded=1),
        ),
        last_released=2,
    )
    assert isinstance(snapshot.by_type, tuple)
    assert vars(lazy) == before
    assert lazy.image_reads == 0


def test_release_resources_records_only_loaded_resources_that_were_released(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    preserved = _TrackedResource("preserved", loaded=True)
    released = _TrackedResource("released", loaded=True)
    unloaded = _TrackedResource("unloaded", loaded=False)
    sticky = _TrackedResource("sticky", loaded=True, unload_on_release=False)
    monkeypatch.setattr(
        Resource,
        "instances",
        {"preserved": preserved, "released": released, "unloaded": unloaded, "sticky": sticky},
    )
    monkeypatch.setattr(Resource, "last_released", 0)
    monkeypatch.setattr(resource_module, "_preserved_ui_assets", lambda: frozenset({"preserved"}))
    monkeypatch.delitem(sys.modules, "module.map_detection.utils_assets", raising=False)

    resource_module.release_resources(next_task="Daily")

    assert preserved.release_calls == 0
    assert released.release_calls == 1
    assert unloaded.release_calls == 1
    assert sticky.release_calls == 1
    assert Resource.snapshot() == ResourceSnapshot(
        registered=4,
        loaded=2,
        by_type=(ResourceTypeSnapshot(resource_type="_TrackedResource", registered=4, loaded=2),),
        last_released=1,
    )
