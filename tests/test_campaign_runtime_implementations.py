import pytest

from module.adapters.campaign_runtime_implementations import (
    load_default_campaign_runtime_executor_registry,
)
from module.adapters.campaign_runtime_profile import (
    CampaignRuntimeProfileError,
    CampaignRuntimeProfileManager,
)
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
)
from module.content.runtime_profile_catalog import (
    load_default_campaign_runtime_profile_registry,
)


def test_every_registered_extension_constructs_from_current_content() -> None:
    content_registry = load_default_campaign_runtime_profile_registry()
    executor_registry = load_default_campaign_runtime_executor_registry()
    failures: list[str] = []

    for index, extension in enumerate(content_registry.extensions.values()):
        profile = CampaignRuntimeProfile(
            CampaignRuntimeProfileId(f"executor-contract-{index}"),
            (CampaignRuntimeExtension(extension.extension_id, extension.executors),),
        )
        try:
            CampaignRuntimeProfileManager(profile, executor_registry)
        except CampaignRuntimeProfileError as error:
            failures.append(f"{extension.extension_id.value}: {error}")

    if failures:
        pytest.fail("generated runtime executor contracts failed:\n" + "\n".join(failures))


def test_production_registry_exactly_covers_every_runtime_contract() -> None:
    content_registry = load_default_campaign_runtime_profile_registry()
    executor_registry = load_default_campaign_runtime_executor_registry()
    content_contracts = {
        (binding.implementation_id, binding.kind)
        for extension in content_registry.extensions.values()
        for binding in extension.executors
    }
    production_contracts = {
        (implementation_id, kind)
        for implementation_id, descriptor in executor_registry.descriptors.items()
        for kind in descriptor.option_schemas
    }

    assert content_contracts == production_contracts
    for extension in content_registry.extensions.values():
        for binding in extension.executors:
            assert binding.options
            descriptor = executor_registry.resolve(binding.implementation_id)
            descriptor.option_schemas[binding.kind].validate(
                binding.implementation_id,
                binding.kind,
                binding.options,
            )
