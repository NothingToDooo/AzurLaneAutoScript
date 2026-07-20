from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from .campaign_runtime_profile import CampaignRuntimeProfileError

if TYPE_CHECKING:
    from collections.abc import Iterable

    from module.application import CancellationSource


@dataclass(frozen=True, slots=True)
class CampaignProgramCapabilities:
    map_has_mob_move: bool = False

    def __post_init__(self) -> None:
        if type(self.map_has_mob_move) is not bool:
            message = "campaign program capability map_has_mob_move must be a boolean"
            raise TypeError(message)


@dataclass(frozen=True, slots=True)
class CampaignProgramCapabilityContribution:
    map_has_mob_move: bool | None = None

    def __post_init__(self) -> None:
        if self.map_has_mob_move is not None and type(self.map_has_mob_move) is not bool:
            message = "campaign program capability contribution must be a boolean or None"
            raise TypeError(message)


@runtime_checkable
class CampaignProgramCapabilityContributionSource(Protocol):
    @property
    def program_capability_contribution(self) -> CampaignProgramCapabilityContribution: ...


@runtime_checkable
class CampaignProgramCapabilityOverrideSource(Protocol):
    def map_has_mob_move_override(
        self,
        cancellation: CancellationSource,
    ) -> bool | None: ...


@dataclass(frozen=True, slots=True)
class CampaignProgramCapabilityReader:
    static_capabilities: CampaignProgramCapabilities = CampaignProgramCapabilities()
    override_source: CampaignProgramCapabilityOverrideSource | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.static_capabilities, CampaignProgramCapabilities):
            message = "campaign program capability reader requires typed static capabilities"
            raise TypeError(message)
        if self.override_source is not None and not isinstance(
            self.override_source,
            CampaignProgramCapabilityOverrideSource,
        ):
            message = "campaign program capability reader requires a typed override source"
            raise TypeError(message)

    def map_has_mob_move(self, cancellation: CancellationSource) -> bool:
        cancellation.raise_if_requested()
        source = self.override_source
        if source is None:
            return self.static_capabilities.map_has_mob_move
        override = source.map_has_mob_move_override(cancellation)
        if override is not None and type(override) is not bool:
            message = "campaign program map_has_mob_move override must return bool or None"
            raise CampaignRuntimeProfileError(message)
        return self.static_capabilities.map_has_mob_move if override is None else override


def build_campaign_program_capability_reader(
    instances: Iterable[object],
) -> CampaignProgramCapabilityReader:
    capabilities = CampaignProgramCapabilities()
    override_sources: list[CampaignProgramCapabilityOverrideSource] = []
    for instance in instances:
        if isinstance(instance, CampaignProgramCapabilityContributionSource):
            contribution = instance.program_capability_contribution
            if not isinstance(contribution, CampaignProgramCapabilityContribution):
                message = "campaign program capability source must provide a typed contribution"
                raise CampaignRuntimeProfileError(message)
            if contribution.map_has_mob_move is not None:
                capabilities = CampaignProgramCapabilities(
                    map_has_mob_move=contribution.map_has_mob_move,
                )
        if isinstance(instance, CampaignProgramCapabilityOverrideSource):
            override_sources.append(instance)

    if len(override_sources) > 1:
        message = "campaign program capabilities accept at most one live override source"
        raise CampaignRuntimeProfileError(message)
    return CampaignProgramCapabilityReader(
        static_capabilities=capabilities,
        override_source=None if not override_sources else override_sources[0],
    )
