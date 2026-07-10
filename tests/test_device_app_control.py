from types import SimpleNamespace

from module.config.server import CN_ACTIVITY, CN_PACKAGE
from module.device.app_service import AppController


class _AppControl(AppController):
    def __init__(self, am_results: list[bool], *, monkey_result: bool) -> None:
        super().__init__(SimpleNamespace(package=CN_PACKAGE))
        self.am_results = am_results
        self.monkey_result = monkey_result
        self.calls: list[tuple[str, str | None, str | None, bool]] = []

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
