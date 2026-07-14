from __future__ import annotations

from typing import TYPE_CHECKING

from module.adapters.campaign_runtime_implementations import (
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeExecutorRegistry,
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
)
from module.content.errors import ContentValidationError
from module.content.models import StageSpec
from module.content.runtime_profile import CampaignRuntimeProfileRegistry

if TYPE_CHECKING:
    from collections.abc import Iterable


def _validate_content_ownership(
    stages: tuple[StageSpec, ...],
    profiles: CampaignRuntimeProfileRegistry,
) -> None:
    referenced_profiles = {stage.runtime_profile_id for stage in stages}
    declared_profiles = set(profiles.profiles)
    unknown_profiles = sorted(profile_id.value for profile_id in referenced_profiles - declared_profiles)
    unused_profiles = sorted(profile_id.value for profile_id in declared_profiles - referenced_profiles)
    if unknown_profiles or unused_profiles:
        message = (
            f"runtime profile stage binding mismatch: unknown={unknown_profiles[:3]}, unused={unused_profiles[:3]}"
        )
        raise ContentValidationError(message)

    referenced_extensions = {
        extension.extension_id for profile in profiles.profiles.values() for extension in profile.extensions
    }
    declared_extensions = set(profiles.extensions)
    if referenced_extensions != declared_extensions:
        unknown = sorted(extension_id.value for extension_id in referenced_extensions - declared_extensions)
        unused = sorted(extension_id.value for extension_id in declared_extensions - referenced_extensions)
        message = f"runtime profile extension binding mismatch: unknown={unknown[:3]}, unused={unused[:3]}"
        raise ContentValidationError(message)


def _validate_executor_contracts(
    profiles: CampaignRuntimeProfileRegistry,
    executors: CampaignRuntimeExecutorRegistry,
) -> None:
    bound_contracts = set()
    for profile in profiles.profiles.values():
        try:
            CampaignRuntimeProfileManager(profile, executors)
        except CampaignRuntimeProfileError as error:
            message = f"runtime profile {profile.profile_id.value} is not executable: {error}"
            raise ContentValidationError(message) from error
        for extension in profile.extensions:
            for binding in extension.executors:
                if not binding.options:
                    message = (
                        "runtime executor binding has no explicit options contract: "
                        f"{binding.implementation_id.value}/{binding.kind.value}"
                    )
                    raise ContentValidationError(message)
                bound_contracts.add((binding.implementation_id, binding.kind))

    declared_contracts = {
        (implementation_id, kind)
        for implementation_id, descriptor in executors.descriptors.items()
        for kind in descriptor.option_schemas
    }
    if bound_contracts != declared_contracts:
        unbound = sorted(
            f"{implementation_id.value}/{kind.value}"
            for implementation_id, kind in declared_contracts - bound_contracts
        )
        unknown = sorted(
            f"{implementation_id.value}/{kind.value}"
            for implementation_id, kind in bound_contracts - declared_contracts
        )
        message = f"runtime executor contract mismatch: unbound={unbound[:3]}, unknown={unknown[:3]}"
        raise ContentValidationError(message)


def validate_mumu12_campaign_runtime_profiles(
    stages: Iterable[StageSpec],
    profiles: CampaignRuntimeProfileRegistry,
    executors: CampaignRuntimeExecutorRegistry | None = None,
) -> None:
    """在设备激活前闭合验证全部关卡、profile 与生产 executor。"""

    if not isinstance(profiles, CampaignRuntimeProfileRegistry):
        message = "profiles must be a CampaignRuntimeProfileRegistry"
        raise TypeError(message)
    stage_snapshot = tuple(stages)
    if any(not isinstance(stage, StageSpec) for stage in stage_snapshot):
        message = "stages must contain StageSpec instances"
        raise TypeError(message)
    executor_registry = load_default_campaign_runtime_executor_registry() if executors is None else executors
    if not isinstance(executor_registry, CampaignRuntimeExecutorRegistry):
        message = "executors must be a CampaignRuntimeExecutorRegistry"
        raise TypeError(message)
    _validate_content_ownership(stage_snapshot, profiles)
    _validate_executor_contracts(profiles, executor_registry)
