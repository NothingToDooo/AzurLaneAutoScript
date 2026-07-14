from types import SimpleNamespace
from typing import TYPE_CHECKING

from module.adapters import campaign_runtime_war_archives as war_archives
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileManager,
    RuntimeOperation,
)
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
)
from module.content.war_archives_profile import WarArchivesDefinition, WarArchivesProfileId

if TYPE_CHECKING:
    import pytest


class _Button:
    def crop(self, area: object, *, image: object, name: str) -> _Button:
        del area, image, name
        return self


class _Template:
    def __init__(self, button: _Button) -> None:
        self.button = button

    def match_result(self, image: object) -> tuple[float, _Button]:
        del image
        return 0.9, self.button

    @staticmethod
    def match(image: object) -> bool:
        del image
        return True


class _Switch:
    def __init__(self) -> None:
        self.modes: list[str] = []

    def set(self, mode: str, *, main: object) -> None:
        del main
        self.modes.append(mode)


class _Profiles:
    def __init__(self, template: _Template) -> None:
        self._profile = SimpleNamespace(
            profile_id=WarArchivesProfileId("archive"),
            entrance=template,
        )
        self.profiles = (self._profile,)

    def resolve(self, profile_id: WarArchivesProfileId) -> object:
        assert profile_id == WarArchivesProfileId("archive")
        return self._profile


class _Runtime:
    def __init__(self) -> None:
        self.definition = SimpleNamespace(war_archives=WarArchivesDefinition(WarArchivesProfileId("archive")))
        self.device = SimpleNamespace(image=object(), click_record=[])
        self.ensure_calls = 0
        self.clicks: list[object] = []

    def appear(self, button: object, *, offset: tuple[int, int] | None = None) -> bool:
        del offset
        if button is war_archives.WAR_ARCHIVES_CHECK:
            return True
        if button is war_archives.WAR_ARCHIVES_CAMPAIGN_CHECK:
            return bool(self.clicks)
        return False

    def ui_ensure(self, *, destination: object) -> bool:
        del destination
        self.ensure_calls += 1
        return True

    def ui_click(self, button: object, **kwargs: object) -> None:
        del kwargs
        self.clicks.append(button)


def _manager() -> CampaignRuntimeProfileManager:
    implementation = RuntimeImplementationId("navigation/war_archives_catalog")
    binding = RuntimeExecutorBinding(
        RuntimeExecutorKind.WAR_ARCHIVES_NAVIGATION,
        implementation,
        {
            "operations": [
                "_advance_archives_scroll",
                "_archives_loading_complete",
                "_discard_archives_scroll_record",
                "_ensure_archives_search_page",
                "_get_archives_entrance",
                "_search_archives_entrance",
                "_wait_archives_loaded",
                "ui_goto_archives_campaign",
                "ui_goto_event",
                "ui_goto_sp",
            ],
            "state": ["first_run"],
            "max_search_attempts": 20,
            "page_fraction": 0.66,
            "match_threshold": 0.85,
            "modes": {"event": "ex", "sp": "sp"},
        },
    )
    profile = CampaignRuntimeProfile(
        CampaignRuntimeProfileId("war-archives-test"),
        (
            CampaignRuntimeExtension(
                CampaignRuntimeExtensionId("war-archives-test"),
                (binding,),
            ),
        ),
    )
    return CampaignRuntimeProfileManager(
        profile,
        CampaignRuntimeExecutorRegistry(war_archives.war_archives_runtime_executor_descriptors()),
    )


def test_war_archives_catalog_enters_once_then_reuses_active_map(monkeypatch: pytest.MonkeyPatch) -> None:
    button = _Button()
    switch = _Switch()
    monkeypatch.setattr(war_archives, "WAR_ARCHIVES_CLIENT_PROFILES", _Profiles(_Template(button)))
    monkeypatch.setattr(war_archives, "_ARCHIVES_SWITCH", switch)
    manager = _manager()
    runtime = _Runtime()

    first = manager.war_archives_navigation.invoke(
        RuntimeOperation.UI_GOTO_EVENT,
        runtime,
        lambda: False,
    )
    second = manager.war_archives_navigation.invoke(
        RuntimeOperation.UI_GOTO_EVENT,
        runtime,
        lambda: False,
    )

    assert first is True
    assert second is True
    assert runtime.ensure_calls == 1
    assert runtime.clicks == [button]
    assert switch.modes == ["ex"]
