from typing import TYPE_CHECKING

import numpy as np

from module.research.research import ResearchProjectInput, RewardResearch

if TYPE_CHECKING:
    from module.base.type_alias import ImageArray
    from module.research.ui import ResearchStatus


class _Device:
    image: ImageArray = np.empty((1, 1, 3), dtype=np.uint8)

    def __init__(self) -> None:
        self.screenshots = 0

    def screenshot(self) -> None:
        self.screenshots += 1


class _Receive6thContext(RewardResearch):
    device: _Device

    def __init__(
        self,
        *,
        status: list[ResearchStatus],
        status_after_wait: list[ResearchStatus] | None = None,
        finished: bool = False,
        receive_result: bool = True,
        queue_slot: int = 1,
    ) -> None:
        self.device = _Device()
        self.statuses = [status] if status_after_wait is None else [status, status_after_wait]
        self.finished = finished
        self.receive_result = receive_result
        self.queue_slot = queue_slot
        self.calls = []
        self._research_finished_index = 2

    def get_research_status(self, image: ImageArray) -> list[ResearchStatus]:
        assert image is self.device.image
        self.calls.append(("status", None))
        return self.statuses.pop(0) if len(self.statuses) > 1 else self.statuses[0]

    def research_has_finished(self) -> bool:
        self.calls.append(("finished", None))
        return self.finished

    def research_receive(self, *, skip_first_screenshot: bool = True) -> bool:
        del skip_first_screenshot
        self.calls.append(("receive", None))
        return self.receive_result

    def get_queue_slot(self) -> int:
        self.calls.append(("queue_slot", None))
        return self.queue_slot

    def research_project_start(
        self,
        project: ResearchProjectInput,
        *,
        add_queue: bool = True,
        skip_first_screenshot: bool = True,
    ) -> bool:
        self.calls.append(("start", project, add_queue, skip_first_screenshot))
        return True


def test_receive_6th_research_starts_waiting_project_when_queue_has_slot() -> None:
    context = _Receive6thContext(status=["detail", "detail", "waiting", "detail", "detail"])

    assert context.receive_6th_research() is True
    assert ("start", 2, True, True) in context.calls


def test_receive_6th_research_returns_false_when_finished_reward_cannot_be_received() -> None:
    context = _Receive6thContext(
        status=["detail", "detail", "waiting", "detail", "detail"],
        finished=True,
        receive_result=False,
    )

    assert context.receive_6th_research() is False
    assert ("receive", None) in context.calls
    assert not any(call[0] == "start" for call in context.calls)


def test_receive_6th_research_does_not_start_running_project_when_queue_is_full() -> None:
    context = _Receive6thContext(
        status=["detail", "detail", "detail", "detail", "detail"],
        status_after_wait=["detail", "running", "detail", "detail", "detail"],
        queue_slot=0,
    )

    assert context.receive_6th_research() is True
    assert ("queue_slot", None) in context.calls
    assert not any(call[0] == "start" for call in context.calls)
