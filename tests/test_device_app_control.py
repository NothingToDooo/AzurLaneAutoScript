from typing import TYPE_CHECKING, cast, override

import pytest

from module.config.server import CN_ACTIVITY, CN_PACKAGE
from module.device.app_service import AppController
from module.exception import RequestHumanTakeover

if TYPE_CHECKING:
    from module.device.contracts import RetrySession


class _RecordingSession:
    def __init__(self, *outputs: str) -> None:
        self.package = CN_PACKAGE
        self.outputs = list(outputs)
        self.commands: list[list[str]] = []

    def adb_shell(self, command: list[str]) -> str:
        self.commands.append(command)
        return self.outputs.pop(0)


class _AppControl(AppController):
    def __init__(self, am_results: list[bool], *, monkey_result: bool) -> None:
        self.am_results = am_results
        self.monkey_result = monkey_result
        self.calls: list[tuple[str, str | None, str | None, bool]] = []

    @property
    @override
    def package(self) -> str:
        return CN_PACKAGE

    def _app_start_adb_am(
        self,
        package_name: str | None = None,
        activity_name: str | None = None,
        *,
        allow_failure: bool = False,
    ) -> bool:
        self.calls.append(("am", package_name, activity_name, allow_failure))
        return self.am_results.pop(0)

    def _app_start_adb_monkey(self, package_name: str | None = None, *, allow_failure: bool = False) -> bool:
        self.calls.append(("monkey", package_name, None, allow_failure))
        return self.monkey_result


def test_app_start_uses_cn_activity_first() -> None:
    app = _AppControl(am_results=[True], monkey_result=False)

    app.app_start()

    assert app.calls == [("am", CN_PACKAGE, CN_ACTIVITY, True)]


def test_app_start_falls_back_to_monkey_then_forced_activity() -> None:
    app = _AppControl(am_results=[False, True], monkey_result=False)

    app.app_start()

    assert app.calls == [
        ("am", CN_PACKAGE, CN_ACTIVITY, True),
        ("monkey", CN_PACKAGE, None, True),
        ("am", CN_PACKAGE, CN_ACTIVITY, False),
    ]


def test_app_start_raises_when_every_strategy_fails() -> None:
    app = _AppControl(am_results=[False, False], monkey_result=False)

    with pytest.raises(RequestHumanTakeover, match="Unable to start app after all strategies failed"):
        app.app_start()


def test_current_reads_both_adb_sources_before_finding_the_focused_package() -> None:
    session = _RecordingSession(
        "mCurrentFocus=null",
        f"topResumedActivity=ActivityRecord{{42 {CN_PACKAGE}/{CN_ACTIVITY}}}",
    )
    app = AppController(cast("RetrySession", session))

    assert app.current() == CN_PACKAGE
    assert session.commands == [
        ["dumpsys", "window"],
        ["dumpsys", "activity", "activities"],
    ]


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("Events injected: 1", True),
        ("monkey aborted because package is inaccessible", False),
        ("No activities found to run", False),
    ],
)
def test_monkey_start_interprets_the_adb_result(output: str, *, expected: bool) -> None:
    session = _RecordingSession(output)
    app = AppController(cast("RetrySession", session))

    assert app._app_start_adb_monkey(allow_failure=True) is expected  # noqa: SLF001 - 直接验证 ADB 输出协议。
    assert session.commands == [
        [
            "monkey",
            "-p",
            CN_PACKAGE,
            "-c",
            "android.intent.category.LAUNCHER",
            "--pct-syskeys",
            "0",
            "1",
        ]
    ]


@pytest.mark.parametrize(
    ("output", "expected"),
    [
        ("Starting: Intent", True),
        ("Error: Activity class does not exist", False),
        ("Permission Denial: starting Intent", False),
        ("Exception occurred while executing start", False),
    ],
)
def test_activity_start_interprets_the_adb_result(output: str, *, expected: bool) -> None:
    session = _RecordingSession(output)
    app = AppController(cast("RetrySession", session))

    assert app._app_start_adb_am(CN_PACKAGE, CN_ACTIVITY) is expected  # noqa: SLF001 - 直接验证 ADB 输出协议。
    assert session.commands == [
        [
            "am",
            "start",
            "-a",
            "android.intent.action.MAIN",
            "-c",
            "android.intent.category.LAUNCHER",
            "-n",
            f"{CN_PACKAGE}/{CN_ACTIVITY}",
        ]
    ]


def test_stop_sends_force_stop_for_the_bound_package() -> None:
    session = _RecordingSession("")
    app = AppController(cast("RetrySession", session))

    app.stop()

    assert session.commands == [["am", "force-stop", CN_PACKAGE]]
