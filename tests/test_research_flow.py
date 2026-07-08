from types import SimpleNamespace

from module.research.research import RewardResearch


class _Receive6thContext(RewardResearch):
    def __init__(self, *, status, finished=False, receive_result=True, queue_slot=1) -> None:
        self.device = SimpleNamespace(image="screen", screenshots=0)
        self.status = status
        self.finished = finished
        self.receive_result = receive_result
        self.queue_slot = queue_slot
        self.calls = []
        self._research_finished_index = 2

        def screenshot():
            self.device.screenshots += 1

        self.device.screenshot = screenshot

    def get_research_status(self, image):
        assert image == "screen"
        self.calls.append(("status", None))
        return self.status

    def research_has_finished(self):
        self.calls.append(("finished", None))
        return self.finished

    def research_receive(self):
        self.calls.append(("receive", None))
        return self.receive_result

    def get_queue_slot(self):
        self.calls.append(("queue_slot", None))
        return self.queue_slot

    def research_project_start(self, project, add_queue=True, skip_first_screenshot=True):
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
        status=["detail", "running", "detail", "detail", "detail"],
        queue_slot=0,
    )

    assert context.receive_6th_research() is True
    assert ("queue_slot", None) in context.calls
    assert not any(call[0] == "start" for call in context.calls)
