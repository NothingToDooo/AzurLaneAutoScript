from module.webui.overview_utils import split_overview_tasks


def test_split_overview_tasks_marks_first_pending_as_running_when_alive() -> None:
    running, pending, waiting = split_overview_tasks(["TaskA", "TaskB"], ["TaskC"], is_alive=True)

    assert running == ["TaskA"]
    assert pending == ["TaskB"]
    assert waiting == ["TaskC"]


def test_split_overview_tasks_keeps_all_pending_when_not_alive() -> None:
    running, pending, waiting = split_overview_tasks(["TaskA", "TaskB"], ["TaskC"], is_alive=False)

    assert running == []
    assert pending == ["TaskA", "TaskB"]
    assert waiting == ["TaskC"]


def test_split_overview_tasks_handles_empty_pending_queue() -> None:
    running, pending, waiting = split_overview_tasks([], ["TaskC"], is_alive=True)

    assert running == []
    assert pending == []
    assert waiting == ["TaskC"]
