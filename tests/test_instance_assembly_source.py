import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, cast

import pytest

from module.bootstrap import (
    CompiledConfiguration,
    ConfigurationDocument,
    ConfigurationLoadError,
    FilesystemInstanceAssemblySource,
    GameRuntimeBundle,
    GameTaskDependencies,
    InstanceAssemblyLayout,
    JsonConfigurationDocumentSource,
    validate_instance_name,
)
from module.notify import DisabledNotificationConfig
from module.supervisor import DeviceLeaseRegistry

if TYPE_CHECKING:
    from collections.abc import Mapping

    from module.bootstrap import ConfigurationDocumentSource, GameRuntimeBundleSource


def _template() -> dict[str, object]:
    return cast(
        "dict[str, object]",
        json.loads(Path("config/template.json").read_text(encoding="utf-8")),
    )


@pytest.mark.parametrize("name", ["alas", "港区一号", "instance-2", "user.profile"])
def test_instance_name_accepts_safe_file_names(name: str) -> None:
    assert validate_instance_name(name) == name


@pytest.mark.parametrize("name", ["", " alas", "a b", ".", "..", "../alas", "a\\b", "C:alas"])
def test_instance_name_rejects_empty_whitespace_or_path_semantics(name: str) -> None:
    with pytest.raises(ValueError, match="instance_name"):
        validate_instance_name(name)


def test_json_source_uses_template_only_for_the_explicit_default_instance(tmp_path: Path) -> None:
    template_path = tmp_path / "template.json"
    template_path.write_text('{"source": "template"}', encoding="utf-8")
    source = JsonConfigurationDocumentSource(tmp_path / "instances", template_path)

    assert source.load("alas") == {"source": "template"}
    with pytest.raises(FileNotFoundError, match=r"other\.json"):
        source.load("other")


def test_json_source_prefers_instance_document_and_rejects_duplicate_fields(tmp_path: Path) -> None:
    config_root = tmp_path / "instances"
    config_root.mkdir()
    template_path = tmp_path / "template.json"
    template_path.write_text('{"source": "template"}', encoding="utf-8")
    (config_root / "alas.json").write_text('{"source": "instance"}', encoding="utf-8")
    source = JsonConfigurationDocumentSource(config_root, template_path)

    assert source.load("alas") == {"source": "instance"}

    (config_root / "alas.json").write_text('{"task": {"enabled": true, "enabled": false}}', encoding="utf-8")
    with pytest.raises(ConfigurationLoadError, match="duplicate configuration field: enabled"):
        source.load("alas")


@dataclass(slots=True)
class _DocumentSource:
    document: ConfigurationDocument
    names: list[str] = field(default_factory=list)

    def load(self, instance_name: str) -> ConfigurationDocument:
        self.names.append(instance_name)
        return self.document

    @staticmethod
    def watch_paths(instance_name: str) -> tuple[Path, ...]:
        return (Path(f"{instance_name}.json"),)


def test_filesystem_assembly_requires_configuration_watch_contract(tmp_path: Path) -> None:
    class _LoadOnlySource:
        @staticmethod
        def load(instance_name: str) -> ConfigurationDocument:
            del instance_name
            return _template()

    with pytest.raises(TypeError, match="watch_paths"):
        FilesystemInstanceAssemblySource(
            cast("ConfigurationDocumentSource", _LoadOnlySource()),
            cast("GameRuntimeBundleSource", object()),
            InstanceAssemblyLayout(state_root=tmp_path / "state", lease_lock_root=tmp_path / "leases"),
        )


@dataclass(slots=True)
class _BundleSource:
    bundle: GameRuntimeBundle
    calls: list[tuple[str, Mapping[str, object], CompiledConfiguration]] = field(default_factory=list)

    def build(
        self,
        instance_name: str,
        document: ConfigurationDocument,
        configuration: CompiledConfiguration,
    ) -> GameRuntimeBundle:
        self.calls.append((instance_name, document, configuration))
        return self.bundle


@dataclass(slots=True)
class _LeaseObservingBundleSource(_BundleSource):
    lease_root: Path = Path()
    observed_owner: str | None = None

    def build(
        self,
        instance_name: str,
        document: ConfigurationDocument,
        configuration: CompiledConfiguration,
    ) -> GameRuntimeBundle:
        self.observed_owner = DeviceLeaseRegistry(self.lease_root).holder(configuration.device_serial)
        return super().build(instance_name, document, configuration)


def test_filesystem_assembly_compiles_once_and_owns_instance_state_paths(tmp_path: Path) -> None:
    document = _template()
    dependencies = object.__new__(GameTaskDependencies)
    bundle = GameRuntimeBundle(
        tasks=dependencies,
        content_revision="content:2026-07-13",
        client_ui_revision="ui:cn-current",
    )
    documents = _DocumentSource(document)
    bundles = _BundleSource(bundle)
    state_root = tmp_path / "state"
    lease_root = tmp_path / "leases"
    source = FilesystemInstanceAssemblySource(
        documents,
        bundles,
        InstanceAssemblyLayout(state_root=state_root, lease_lock_root=lease_root),
        process_id=lambda: 1234,
    )

    assembly = source.load("港区一号")

    assert documents.names == ["港区一号"]
    assert len(bundles.calls) == 1
    assert bundles.calls[0][0:2] == ("港区一号", document)
    assert bundles.calls[0][2] is assembly.configuration
    assert assembly.tasks is dependencies
    assert assembly.runtime.state_path == state_root / "港区一号.sqlite3"
    assert assembly.runtime.lease_lock_root == lease_root
    assert assembly.runtime.lease_owner == "港区一号:pid-1234"
    assert assembly.runtime.device_serial == assembly.configuration.device_serial
    assert assembly.configuration.notification == DisabledNotificationConfig()
    assert state_root.is_dir()
    assert lease_root.is_dir()


def test_filesystem_assembly_holds_device_lease_while_building_runtime_bundle(tmp_path: Path) -> None:
    dependencies = object.__new__(GameTaskDependencies)
    bundle = GameRuntimeBundle(
        tasks=dependencies,
        content_revision="content:current",
        client_ui_revision="ui:current",
    )
    lease_root = tmp_path / "leases"
    bundles = _LeaseObservingBundleSource(bundle=bundle, lease_root=lease_root)
    source = FilesystemInstanceAssemblySource(
        _DocumentSource(_template()),
        bundles,
        InstanceAssemblyLayout(state_root=tmp_path / "state", lease_lock_root=lease_root),
        process_id=lambda: 4321,
    )

    source.load("alas")

    assert bundles.observed_owner == "alas:pid-4321"
    assert DeviceLeaseRegistry(lease_root).holder("127.0.0.1:16384") is None
