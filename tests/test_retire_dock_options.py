from module.retire.dock import DockFilterOptions, dock_filter_options


def test_dock_filter_options_override_existing_options() -> None:
    options = dock_filter_options(
        DockFilterOptions(index="cv", wait_loading=False),
        {"rarity": "common", "extra": "enhanceable"},
    )

    assert options.index == "cv"
    assert options.rarity == "common"
    assert options.extra == "enhanceable"
    assert options.wait_loading is False
