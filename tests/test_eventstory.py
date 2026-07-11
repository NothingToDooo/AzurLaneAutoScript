from typing import TYPE_CHECKING, Literal, override

from module.eventstory import assets as eventstory_assets
from module.eventstory.eventstory import EventStory

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.base.button import Button


class _FakeDevice:
    def __init__(self) -> None:
        self.clicks = []
        self.screenshots = 0
        self.click_record_clears = 0

    def click(self, button: Button) -> None:
        self.clicks.append(button)

    def screenshot(self) -> None:
        self.screenshots += 1

    def click_record_clear(self) -> None:
        self.click_record_clears += 1


class _EventStoryStateContext(EventStory):
    def __init__(
        self,
        *,
        matching: Iterable[Button] = (),
        appearing: Iterable[Button] = (),
        clicking: Iterable[Button] = (),
        alchemist: bool = False,
    ) -> None:
        self.matching = set(matching)
        self.appearing = set(appearing)
        self.clicking = set(clicking)
        self.alchemist = alchemist

    def match_template_color(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return button in self.matching

    def appear(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return button in self.appearing

    def appear_then_click(self, button: Button, *_args: object, **_kwargs: object) -> bool:
        return button in self.clicking

    def get_event_20250724_button(self) -> Button | None:
        return eventstory_assets.STORY_FIRST if self.alchemist else None


class _EventStoryLoopContext(_EventStoryStateContext):
    device: _FakeDevice

    def __init__(self) -> None:
        super().__init__(clicking=(eventstory_assets.STORY_FIRST,))
        self.device = _FakeDevice()
        self.combat_executing_results: list[Button | Literal[False]] = [False, eventstory_assets.STORY_FIRST]
        self.story_skip_clears = 0
        self.popup_clears = 0

    def is_combat_executing(self) -> Button | Literal[False]:
        return self.combat_executing_results.pop(0)

    @override
    def is_combat_loading(self) -> bool:
        return False

    @override
    def handle_story_skip(self) -> bool:
        return False

    @override
    def handle_get_items(self) -> bool:
        return False

    @override
    def handle_event_20250724(self, *_args: object, **_kwargs: object) -> bool:
        return False

    @override
    def interval_clear(
        self,
        button: Button | list[Button] | tuple[Button, ...] | None,
        interval: float = 3,
    ) -> None:
        del button, interval

    def story_skip_interval_clear(self) -> None:
        self.story_skip_clears += 1

    def popup_interval_clear(self) -> None:
        self.popup_clears += 1


def test_get_event_story_state_prefers_finished_state() -> None:
    context = _EventStoryStateContext(
        matching=(eventstory_assets.STORY_FINISHED,),
        clicking=(eventstory_assets.STORY_FIRST,),
    )

    assert context.get_event_story_state() == "finish"


def test_get_event_story_state_detects_regular_story_entry() -> None:
    context = _EventStoryStateContext(clicking=(eventstory_assets.STORY_MIDDLE,))

    assert context.get_event_story_state() == "story"


def test_get_event_story_state_detects_alchemist_story_entry() -> None:
    context = _EventStoryStateContext(alchemist=True)

    assert context.get_event_story_state() == "story_alchemist"


def test_event_story_clears_intervals_after_clicking_story_entry() -> None:
    context = _EventStoryLoopContext()

    assert context.event_story() == "battle"
    assert context.story_skip_clears == 1
    assert context.popup_clears == 1
    assert context.device.click_record_clears == 1
    assert context.device.screenshots == 1
