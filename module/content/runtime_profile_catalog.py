from collections.abc import Mapping, Sequence
from functools import lru_cache
from pathlib import Path
from typing import cast

from module.config.json_codec import (
    DuplicateJsonFieldError,
    NonFiniteJsonNumberError,
    StrictJsonDecodeError,
    decode_json,
)
from module.content.errors import ContentValidationError
from module.content.runtime_profile import (
    CampaignRuntimeExtension,
    CampaignRuntimeExtensionId,
    CampaignRuntimeProfile,
    CampaignRuntimeProfileId,
    CampaignRuntimeProfileRegistry,
    RuntimeExecutorBinding,
    RuntimeExecutorKind,
    RuntimeImplementationId,
    RuntimeTuning,
    RuntimeTuningKey,
)

RUNTIME_PROFILE_SCHEMA_VERSION = 1
DEFAULT_RUNTIME_PROFILE_PATH = Path(__file__).resolve().parents[2] / "content" / "campaign-runtime-profiles.json"
_ROOT_FIELDS = {"schema_version", "extensions", "profiles"}
_EXTENSION_FIELDS = {"id", "executors"}
_EXECUTOR_FIELDS = {"kind", "implementation", "options"}
_PROFILE_FIELDS = {"id", "extensions", "tunings"}
_TUNING_FIELDS = {"key", "value"}


def _mapping(value: object, location: str, fields: set[str]) -> Mapping[str, object]:
    if not isinstance(value, Mapping) or any(not isinstance(key, str) for key in value):
        message = f"{location} must be an object with string fields"
        raise ContentValidationError(message)
    result = cast("Mapping[str, object]", value)
    if set(result) != fields:
        message = f"{location} fields must be exactly {sorted(fields)}"
        raise ContentValidationError(message)
    return result


def _sequence(value: object, location: str) -> Sequence[object]:
    if not isinstance(value, Sequence) or isinstance(value, str | bytes):
        message = f"{location} must be a list"
        raise ContentValidationError(message)
    return value


def _string(value: object, location: str) -> str:
    if not isinstance(value, str) or not value:
        message = f"{location} must be a non-empty string"
        raise ContentValidationError(message)
    return value


def _executor(value: object, location: str) -> RuntimeExecutorBinding:
    item = _mapping(value, location, _EXECUTOR_FIELDS)
    raw_kind = _string(item["kind"], f"{location}.kind")
    try:
        kind = RuntimeExecutorKind(raw_kind)
    except ValueError as error:
        message = f"{location}.kind contains an unknown RuntimeExecutorKind: {raw_kind!r}"
        raise ContentValidationError(message) from error
    options = item["options"]
    if not isinstance(options, Mapping) or any(not isinstance(key, str) for key in options):
        message = f"{location}.options must be an object with string fields"
        raise ContentValidationError(message)
    return RuntimeExecutorBinding(
        kind,
        RuntimeImplementationId(_string(item["implementation"], f"{location}.implementation")),
        cast("Mapping[str, object]", options),
    )


def _tuning(value: object, location: str) -> RuntimeTuning:
    item = _mapping(value, location, _TUNING_FIELDS)
    raw_key = _string(item["key"], f"{location}.key")
    try:
        key = RuntimeTuningKey(raw_key)
    except ValueError as error:
        message = f"{location}.key contains an unknown RuntimeTuningKey: {raw_key!r}"
        raise ContentValidationError(message) from error
    return RuntimeTuning(key, item["value"])


def compile_campaign_runtime_profile_registry(
    path: Path = DEFAULT_RUNTIME_PROFILE_PATH,
) -> CampaignRuntimeProfileRegistry:
    if not isinstance(path, Path):
        message = "runtime profile registry path must be a Path"
        raise TypeError(message)
    try:
        raw = decode_json(path.read_text(encoding="utf-8"))
    except DuplicateJsonFieldError as error:
        message = f"duplicate JSON key: {error.field}"
        raise ContentValidationError(message) from error
    except NonFiniteJsonNumberError as error:
        message = f"runtime profile registry contains a non-finite JSON number: {error.constant}"
        raise ContentValidationError(message) from error
    except (OSError, UnicodeError, StrictJsonDecodeError) as error:
        message = f"failed to load runtime profile registry {path}: {error}"
        raise ContentValidationError(message) from error
    root = _mapping(raw, "$", _ROOT_FIELDS)
    if type(root["schema_version"]) is not int or root["schema_version"] != RUNTIME_PROFILE_SCHEMA_VERSION:
        message = f"$.schema_version must be {RUNTIME_PROFILE_SCHEMA_VERSION}"
        raise ContentValidationError(message)

    extensions: list[CampaignRuntimeExtension] = []
    extensions_by_id: dict[CampaignRuntimeExtensionId, CampaignRuntimeExtension] = {}
    for index, raw_extension in enumerate(_sequence(root["extensions"], "$.extensions")):
        location = f"$.extensions[{index}]"
        item = _mapping(raw_extension, location, _EXTENSION_FIELDS)
        extension = CampaignRuntimeExtension(
            CampaignRuntimeExtensionId(_string(item["id"], f"{location}.id")),
            tuple(
                _executor(raw_executor, f"{location}.executors[{executor_index}]")
                for executor_index, raw_executor in enumerate(_sequence(item["executors"], f"{location}.executors"))
            ),
        )
        if extension.extension_id in extensions_by_id:
            message = f"duplicate runtime extension: {extension.extension_id.value}"
            raise ContentValidationError(message)
        extensions.append(extension)
        extensions_by_id[extension.extension_id] = extension

    profiles: list[CampaignRuntimeProfile] = []
    for index, raw_profile in enumerate(_sequence(root["profiles"], "$.profiles")):
        location = f"$.profiles[{index}]"
        item = _mapping(raw_profile, location, _PROFILE_FIELDS)
        extension_ids = tuple(
            CampaignRuntimeExtensionId(_string(raw_id, f"{location}.extensions[{extension_index}]"))
            for extension_index, raw_id in enumerate(_sequence(item["extensions"], f"{location}.extensions"))
        )
        try:
            resolved_extensions = tuple(extensions_by_id[extension_id] for extension_id in extension_ids)
        except KeyError as error:
            missing = cast("CampaignRuntimeExtensionId", error.args[0])
            message = f"{location} references unknown extension: {missing.value}"
            raise ContentValidationError(message) from None
        profiles.append(
            CampaignRuntimeProfile(
                CampaignRuntimeProfileId(_string(item["id"], f"{location}.id")),
                resolved_extensions,
                tuple(
                    _tuning(raw_tuning, f"{location}.tunings[{tuning_index}]")
                    for tuning_index, raw_tuning in enumerate(_sequence(item["tunings"], f"{location}.tunings"))
                ),
            )
        )
    return CampaignRuntimeProfileRegistry(extensions, profiles)


@lru_cache(maxsize=1)
def load_default_campaign_runtime_profile_registry() -> CampaignRuntimeProfileRegistry:
    return compile_campaign_runtime_profile_registry()
