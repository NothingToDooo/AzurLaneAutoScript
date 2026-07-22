from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .campaign_runtime_profile import CampaignRuntimeProfileError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.config.config import AzurLaneConfig


class CampaignClearModeConfigRuntime(Protocol):
    @property
    def config(self) -> AzurLaneConfig: ...


class CampaignClearModeConfigHook(Protocol):
    def __call__(
        self,
        runtime: CampaignClearModeConfigRuntime,
        *,
        handled: bool,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class CampaignClearModeConfigContributor:
    apply: CampaignClearModeConfigHook

    def __post_init__(self) -> None:
        if not callable(self.apply):
            message = "campaign clear-mode config contributor requires an apply hook"
            raise TypeError(message)


@runtime_checkable
class CampaignClearModeConfigContributorSource(Protocol):
    @property
    def clear_mode_config_contributor(self) -> CampaignClearModeConfigContributor: ...


@dataclass(frozen=True, slots=True)
class CampaignClearModeConfigService:
    contributors: tuple[CampaignClearModeConfigContributor, ...] = ()

    def __post_init__(self) -> None:
        contributors = tuple(self.contributors)
        if any(not isinstance(contributor, CampaignClearModeConfigContributor) for contributor in contributors):
            message = "campaign clear-mode config service requires typed contributors"
            raise TypeError(message)
        object.__setattr__(self, "contributors", contributors)

    def apply(self, runtime: CampaignClearModeConfigRuntime, *, handled: bool) -> None:
        if type(handled) is not bool:
            message = "clear-mode config base result must be a boolean"
            raise CampaignRuntimeProfileError(message)
        for contributor in self.contributors:
            if contributor.apply(runtime, handled=handled) is not None:
                message = "campaign clear-mode config contributor must return None"
                raise CampaignRuntimeProfileError(message)


def build_campaign_clear_mode_config_service(
    instances_in_profile_order: Iterable[object],
) -> CampaignClearModeConfigService:
    """按 profile 全局声明顺序编译 clear-mode 配置贡献者。"""

    contributors: list[CampaignClearModeConfigContributor] = []
    for instance in instances_in_profile_order:
        if not isinstance(instance, CampaignClearModeConfigContributorSource):
            continue
        contributor = instance.clear_mode_config_contributor
        if not isinstance(contributor, CampaignClearModeConfigContributor):
            message = "campaign clear-mode config source must provide a typed contributor"
            raise CampaignRuntimeProfileError(message)
        contributors.append(contributor)
    return CampaignClearModeConfigService(tuple(contributors))
