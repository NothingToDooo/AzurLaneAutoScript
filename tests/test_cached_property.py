from module.base.decorator import cached_property, del_cached_property, has_cached_property, set_cached_property


class Example:
    def __init__(self) -> None:
        self.calls = 0

    @cached_property
    def value(self) -> int:
        self.calls += 1
        return self.calls


def test_cached_property_helpers_manage_instance_cache() -> None:
    example = Example()

    assert example.value == 1
    assert example.value == 1
    assert example.calls == 1
    assert has_cached_property(example, "value")

    del_cached_property(example, "value")

    assert not has_cached_property(example, "value")
    assert example.value == 2

    set_cached_property(example, "value", 10)

    assert example.value == 10
    assert example.calls == 2
