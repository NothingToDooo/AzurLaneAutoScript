import importlib
from dataclasses import dataclass
from types import ModuleType

from module.campaign.campaign_base import CampaignBase
from module.content.errors import LegacyStageContractError, LegacyStageReferenceError
from module.content.models import StageRef
from module.map.map_base import CampaignMap


@dataclass(frozen=True, slots=True)
class LoadedCampaignModule:
    config_class: type[object]
    campaign_class: type[CampaignBase]


@dataclass(frozen=True, slots=True)
class LoadedStage(LoadedCampaignModule):
    map: CampaignMap


class LegacyStageModuleAdapter:
    @staticmethod
    def _module_name(ref: StageRef) -> str:
        if not isinstance(ref, StageRef):
            message = "legacy stage ref must be a StageRef"
            raise LegacyStageReferenceError(message)
        for field_name, value in (("pack_id", ref.pack_id), ("stage_id", ref.stage_id)):
            if not value.isidentifier():
                message = f"invalid legacy stage {field_name}: {value!r}"
                raise LegacyStageReferenceError(message)
        return f"campaign.{ref.pack_id}.{ref.stage_id}"

    @staticmethod
    def _class_export(module: ModuleType, module_name: str, export_name: str) -> type[object]:
        try:
            export = getattr(module, export_name)
        except AttributeError:
            message = f"legacy campaign module {module_name} is missing {export_name}"
            raise LegacyStageContractError(message) from None
        if not isinstance(export, type):
            message = f"legacy campaign module {module_name} export {export_name} must be a class"
            raise LegacyStageContractError(message)
        return export

    @classmethod
    def _campaign_export(cls, module: ModuleType, module_name: str) -> type[CampaignBase]:
        campaign_class = cls._class_export(module, module_name, "Campaign")
        if not issubclass(campaign_class, CampaignBase):
            message = f"legacy campaign module {module_name} export Campaign must inherit CampaignBase"
            raise LegacyStageContractError(message)
        return campaign_class

    def _load_campaign_module(self, ref: StageRef) -> tuple[ModuleType, LoadedCampaignModule]:
        module_name = self._module_name(ref)
        module = importlib.import_module(module_name)
        if not isinstance(module, ModuleType):
            message = f"legacy campaign import {module_name} must return a module object"
            raise LegacyStageContractError(message)
        loaded = LoadedCampaignModule(
            config_class=self._class_export(module, module_name, "Config"),
            campaign_class=self._campaign_export(module, module_name),
        )
        return module, loaded

    def load_campaign_helper(self, ref: StageRef) -> LoadedCampaignModule:
        return self._load_campaign_module(ref)[1]

    def load(self, ref: StageRef) -> LoadedStage:
        module_name = self._module_name(ref)
        module, loaded = self._load_campaign_module(ref)
        try:
            map_ = module.MAP
        except AttributeError:
            message = f"legacy stage module {module_name} is missing MAP"
            raise LegacyStageContractError(message) from None
        if not isinstance(map_, CampaignMap):
            message = f"legacy stage module {module_name} export MAP must be a CampaignMap"
            raise LegacyStageContractError(message)
        return LoadedStage(
            config_class=loaded.config_class,
            campaign_class=loaded.campaign_class,
            map=map_,
        )
