import sys
from typing import TYPE_CHECKING

import module.base.resource as resource_module
from module.base.resource import Resource

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


def test_release_resources_skips_preserved_resources_without_loading_lazy_properties(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    lazy = _LazyResource()
    preserved = _TrackedResource("preserved", loaded=True)
    released = _TrackedResource("released", loaded=True)
    unloaded = _TrackedResource("unloaded", loaded=False)
    sticky = _TrackedResource("sticky", loaded=True, unload_on_release=False)
    monkeypatch.setattr(
        Resource,
        "instances",
        {"lazy": lazy, "preserved": preserved, "released": released, "unloaded": unloaded, "sticky": sticky},
    )
    monkeypatch.setattr(resource_module, "_preserved_ui_assets", lambda: frozenset({"preserved"}))
    monkeypatch.delitem(sys.modules, "module.map_detection.utils_assets", raising=False)

    resource_module.release_resources(next_task="Daily")

    assert preserved.release_calls == 0
    assert released.release_calls == 1
    assert unloaded.release_calls == 1
    assert sticky.release_calls == 1
    assert lazy.image_reads == 0
