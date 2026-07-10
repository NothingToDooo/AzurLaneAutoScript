from module.content.models import StageRef
from module.content.stage_loader import load_default_stage

_LOADED_STAGE = load_default_stage(StageRef("event_20260625_cn", "ht2"))
MAP = _LOADED_STAGE.map
Config = _LOADED_STAGE.config_class
Campaign = _LOADED_STAGE.campaign_class
