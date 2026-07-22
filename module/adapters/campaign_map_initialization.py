from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .campaign_runtime_profile import CampaignRuntimeProfileError

if TYPE_CHECKING:
    from collections.abc import Callable, Iterable

    from module.config.config import AzurLaneConfig


class CampaignMapInitializationRuntime(Protocol):
    config: AzurLaneConfig
    map_is_clear_mode: bool


type CampaignMapInitializationHook = Callable[[CampaignMapInitializationRuntime], None]


@dataclass(frozen=True, slots=True)
class CampaignMapInitializationContributor:
    pre_control: CampaignMapInitializationHook | None = None
    post_control: CampaignMapInitializationHook | None = None

    def __post_init__(self) -> None:
        hooks = (self.pre_control, self.post_control)
        if all(hook is None for hook in hooks):
            message = "campaign map initialization contributor requires a phase hook"
            raise ValueError(message)
        if any(hook is not None and not callable(hook) for hook in hooks):
            message = "campaign map initialization phase hook must be callable"
            raise TypeError(message)


@runtime_checkable
class CampaignMapInitializationContributorSource(Protocol):
    @property
    def map_initialization_contributor(self) -> CampaignMapInitializationContributor: ...


@dataclass(frozen=True, slots=True)
class CampaignMapInitializationService:
    pre_control_hooks: tuple[CampaignMapInitializationHook, ...] = ()
    post_control_hooks: tuple[CampaignMapInitializationHook, ...] = ()

    def __post_init__(self) -> None:
        pre_control_hooks = tuple(self.pre_control_hooks)
        post_control_hooks = tuple(self.post_control_hooks)
        if any(not callable(hook) for hook in (*pre_control_hooks, *post_control_hooks)):
            message = "campaign map initialization service requires callable hooks"
            raise TypeError(message)
        object.__setattr__(self, "pre_control_hooks", pre_control_hooks)
        object.__setattr__(self, "post_control_hooks", post_control_hooks)

    def pre_control(self, runtime: CampaignMapInitializationRuntime) -> None:
        self._run(self.pre_control_hooks, runtime, phase="pre-control")

    def post_control(self, runtime: CampaignMapInitializationRuntime) -> None:
        self._run(self.post_control_hooks, runtime, phase="post-control")

    @staticmethod
    def _run(
        hooks: tuple[CampaignMapInitializationHook, ...],
        runtime: CampaignMapInitializationRuntime,
        *,
        phase: str,
    ) -> None:
        for hook in hooks:
            if hook(runtime) is not None:
                message = f"campaign map initialization {phase} hook must return None"
                raise CampaignRuntimeProfileError(message)


def build_campaign_map_initialization_service(
    instances: Iterable[object],
) -> CampaignMapInitializationService:
    """按 profile 声明顺序编译数据初始化与地图控制之间的固定阶段。"""

    pre_control_hooks: list[CampaignMapInitializationHook] = []
    post_control_hooks: list[CampaignMapInitializationHook] = []
    for instance in instances:
        if not isinstance(instance, CampaignMapInitializationContributorSource):
            continue
        contributor = instance.map_initialization_contributor
        if not isinstance(contributor, CampaignMapInitializationContributor):
            message = "campaign map initialization source must provide a typed contributor"
            raise CampaignRuntimeProfileError(message)
        if contributor.pre_control is not None:
            pre_control_hooks.append(contributor.pre_control)
        if contributor.post_control is not None:
            post_control_hooks.append(contributor.post_control)
    return CampaignMapInitializationService(tuple(pre_control_hooks), tuple(post_control_hooks))
