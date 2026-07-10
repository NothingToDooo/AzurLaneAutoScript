import copy
import importlib
from contextlib import suppress
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, cast

from module.campaign.campaign_base import CampaignBase
from module.campaign.campaign_event import CampaignEvent
from module.campaign.campaign_ui import MODE_SWITCH_1
from module.content.campaign_policy import (
    CampaignPolicy,
    StageLoopConfig,
    StagePolicyConfig,
    apply_pack_policy,
    apply_stage_policy,
    resolve_stage_loop,
)
from module.content.catalog import ContentCatalog
from module.content.errors import UnknownPackError, UnknownStageError
from module.content.legacy_stage import LegacyStageModuleAdapter, LoadedCampaignModule, LoadedStage
from module.content.manifest import load_default_event_manifests
from module.content.models import StageRef, StageSpec
from module.content.stage_loader import StageLoader, StageSpecLoader
from module.exception import CampaignEnd, RequestHumanTakeover, ScriptEnd
from module.handler.fast_forward import map_files, to_map_file_name
from module.logger import logger
from module.ui.page import page_campaign

if TYPE_CHECKING:
    from module.config.config import AzurLaneConfig


@dataclass(frozen=True, slots=True)
class _CampaignLoadState:
    name: str
    folder: str
    stage: str
    loaded: LoadedCampaignModule
    loaded_stage: LoadedStage | None
    campaign: CampaignBase

    def __post_init__(self) -> None:
        if not isinstance(self.campaign, CampaignBase):
            message = "campaign load state requires a CampaignBase instance"
            raise TypeError(message)


MAIN_CAMPAIGN_STAGE_ALIASES = {
    "t1": "a1",
    "t2": "a2",
    "t3": "a3",
    "t4": "b1",
    "t5": "b2",
    "t6": "b3",
    "ht1": "c1",
    "ht2": "c2",
    "ht3": "c3",
    "ht4": "d1",
    "ht5": "d2",
    "ht6": "d3",
}


@lru_cache(maxsize=1)
def _content_catalog() -> ContentCatalog:
    return ContentCatalog(load_default_event_manifests())


def _campaign_policy(folder: str, catalog: ContentCatalog | None = None) -> CampaignPolicy:
    effective_catalog = catalog if catalog is not None else _content_catalog()
    try:
        return effective_catalog.get_pack(folder).policy
    except UnknownPackError:
        return CampaignPolicy()


def _normalize_stage_alias(name: str, folder: str, catalog: ContentCatalog | None = None) -> str:
    """归一化地图文件名里的活动别名。"""
    if folder == "campaign_main":
        return MAIN_CAMPAIGN_STAGE_ALIASES.get(name, name)
    return _campaign_policy(folder, catalog).resolve_alias(name)


def _resolve_stage_loop_alias(
    name: str,
    folder: str,
    config: StageLoopConfig,
    catalog: ContentCatalog | None = None,
) -> tuple[str, bool]:
    """处理循环关卡别名，返回实际关卡名和是否命中循环。"""
    return resolve_stage_loop(name, folder, _campaign_policy(folder, catalog), config)


def _apply_stage_alias_policies(
    name: str,
    folder: str,
    config: StagePolicyConfig,
    catalog: ContentCatalog | None = None,
) -> None:
    """应用依赖归一化关卡名的运行策略。"""
    apply_stage_policy(name, folder, _campaign_policy(folder, catalog), config)


def _apply_campaign_folder_policies(
    folder: str,
    config: StagePolicyConfig,
    catalog: ContentCatalog | None = None,
) -> None:
    """应用只依赖活动目录的运行策略。"""
    apply_pack_policy(folder, _campaign_policy(folder, catalog), config)


class CampaignRun(CampaignEvent):
    folder: str
    name: str
    stage: str
    stage_adapter = LegacyStageModuleAdapter()
    stage_loader: StageLoader = StageSpecLoader()
    content_catalog: ContentCatalog | None = None
    loaded_campaign: LoadedCampaignModule
    loaded_stage: LoadedStage | None = None
    config: AzurLaneConfig
    campaign: CampaignBase
    run_count: int
    run_limit: int
    is_stage_loop = False

    def _effective_content_catalog(self) -> ContentCatalog:
        return self.content_catalog if self.content_catalog is not None else _content_catalog()

    def _campaign_identity_matches(self, name: str, folder: str, *, is_stage: bool) -> bool:
        return (
            getattr(self, "name", None) == name
            and getattr(self, "folder", None) == folder
            and (self.loaded_stage is not None) == is_stage
        )

    def _stage_for_reference(self, name: str, folder: str) -> str:
        if folder.startswith("campaign_"):
            return "-".join(name.split("_")[1:3])
        if folder.startswith(("event", "war_archives")):
            return name
        return name

    def _native_stage_spec(self, ref: StageRef) -> StageSpec | None:
        catalog = self._effective_content_catalog()
        try:
            return catalog.resolve_stage(ref)
        except UnknownPackError, UnknownStageError:
            return None

    @staticmethod
    def _raise_campaign_not_found(ref: StageRef, error: ModuleNotFoundError) -> None:
        folder = ref.pack_id
        name = ref.stage_id
        logger.warning(f"Map file not found: campaign.{folder}.{name}")
        if not Path(f"./campaign/{folder}").exists():
            logger.warning(f"Folder not exists: ./campaign/{folder}")
        else:
            files = map_files(folder)
            logger.warning(f"Existing files: {files}")

        logger.critical(f"Possible reason #1: This event ({folder}) does not have {name}")
        logger.critical(
            "Possible reason #2: You are using an old Alas, "
            "please check for update, or make map files yourself using dev_tools/map_extractor.py"
        )
        raise RequestHumanTakeover from error

    def _build_campaign_load(
        self,
        name: str,
        folder: str,
        loaded: LoadedCampaignModule,
        loaded_stage: LoadedStage | None,
    ) -> _CampaignLoadState:
        config = copy.deepcopy(self.config).merge(loaded.config_class())
        campaign = loaded.campaign_class(config=config, device=self.device)
        return _CampaignLoadState(
            name=name,
            folder=folder,
            stage=self._stage_for_reference(name, folder),
            loaded=loaded,
            loaded_stage=loaded_stage,
            campaign=campaign,
        )

    def _commit_campaign_load(self, state: _CampaignLoadState) -> None:
        self.name = state.name
        self.folder = state.folder
        self.stage = state.stage
        self.loaded_campaign = state.loaded
        self.loaded_stage = state.loaded_stage
        self.campaign = state.campaign

    def load_campaign(self, name: str, folder: str = "campaign_main") -> bool:
        if self._campaign_identity_matches(name, folder, is_stage=True):
            return False

        ref = StageRef(pack_id=folder, stage_id=name)
        spec = self._native_stage_spec(ref)
        if spec is not None:
            loaded = self.stage_loader.load(spec)
        else:
            try:
                loaded = self.stage_adapter.load(ref)
            except ModuleNotFoundError as error:
                self._raise_campaign_not_found(ref, error)

        state = self._build_campaign_load(name, folder, loaded, loaded)
        self._commit_campaign_load(state)
        return True

    def load_campaign_helper(self, name: str, folder: str) -> bool:
        """装载不带地图的历史战役辅助模块。"""
        if self._campaign_identity_matches(name, folder, is_stage=False):
            return False

        ref = StageRef(pack_id=folder, stage_id=name)
        try:
            loaded = self.stage_adapter.load_campaign_helper(ref)
        except ModuleNotFoundError as error:
            self._raise_campaign_not_found(ref, error)

        state = self._build_campaign_load(name, folder, loaded, None)
        self._commit_campaign_load(state)
        return True

    def _triggered_run_count_limit(self) -> bool:
        if not (self.run_limit and self.config.StopCondition_RunCount <= 0):
            return False

        logger.hr("Triggered stop condition: Run count")
        self.config.StopCondition_RunCount = 0
        self.config.Scheduler_Enable = False
        return True

    def _triggered_reach_level_limit(self) -> bool:
        if not (self.config.StopCondition_ReachLevel and self.campaign.config.LV_TRIGGERED):
            return False

        logger.hr(f"Triggered stop condition: Reach level {self.config.StopCondition_ReachLevel}")
        self.config.Scheduler_Enable = False
        return True

    def _triggered_oil_limit(self, oil_check=True) -> bool:
        if not oil_check or self.get_oil() >= max(500, self.config.StopCondition_OilLimit):
            return False

        logger.hr("Triggered stop condition: Oil limit")
        self.config.task_delay(minute=(120, 240))
        return True

    def _triggered_auto_search_oil_limit(self) -> bool:
        if not self.campaign.auto_search_oil_limit_triggered:
            return False

        logger.hr("Triggered stop condition: Auto search oil limit")
        self.config.task_delay(minute=(120, 240))
        return True

    def _triggered_get_new_ship_limit(self) -> bool:
        if not (self.config.StopCondition_GetNewShip and self.campaign.config.GET_SHIP_TRIGGERED):
            return False

        logger.hr("Triggered stop condition: Get new ship")
        self.config.Scheduler_Enable = False
        return True

    def _triggered_event_pt_limit(self, oil_check=True) -> bool:
        if not (oil_check and self.campaign.event_pt_limit_triggered()):
            return False

        logger.hr("Triggered stop condition: Event PT limit")
        return True

    def _triggered_auto_search_coin_limit(self) -> bool:
        if not (self.config.TaskBalancer_Enable and self.campaign.auto_search_coin_limit_triggered):
            return False

        logger.hr("Triggered stop condition: Auto search coin limit")
        self.handle_task_balancer()
        return True

    def _triggered_task_balancer_limit(self, oil_check=True) -> bool:
        if not (
            oil_check and self.run_count >= 1 and self.config.TaskBalancer_Enable and self.triggered_task_balancer()
        ):
            return False

        logger.hr("Triggered stop condition: Coin limit")
        self.handle_task_balancer()
        return True

    def triggered_stop_condition(self, oil_check=True):
        """
        Returns:
            bool: If triggered a stop condition.
        """
        return (
            self._triggered_run_count_limit()
            or self._triggered_reach_level_limit()
            or self._triggered_oil_limit(oil_check)
            or self._triggered_auto_search_oil_limit()
            or self._triggered_get_new_ship_limit()
            or self._triggered_event_pt_limit(oil_check)
            or self._triggered_auto_search_coin_limit()
            or self._triggered_task_balancer_limit(oil_check)
        )

    def _triggered_app_restart(self):
        """
        Returns:
            bool: If triggered a restart condition.
        """
        if not self.campaign.emotion.is_ignore and self.campaign.emotion.triggered_bug():
            logger.info("Triggered restart avoid emotion bug")
            return True

        return False

    def handle_app_restart(self):
        if self._triggered_app_restart():
            self.config.task_call("Restart")
            return True

        return False

    def handle_stage_name(self, name, folder, mode="normal"):
        """
        Handle wrong stage names.
        In some events, the name of SP may be different, such as 'vsp', muse sp.
        To call them easier, their map files should named 'sp.py'.

        Args:
            name (str): Name of .py file.
            folder (str): Name of the file folder under campaign.

        Returns:
            str, str: name, folder
        """
        name = to_map_file_name(name)
        # For GemsFarming, auto choose events or main chapters
        if self.config.task.command == "GemsFarming":
            if self.stage_is_main(name):
                logger.info(f"Stage name {name} is from campaign_main")
                folder = "campaign_main"
            else:
                folder = self.config.cross_get("GemsFarming.Campaign.Event")
                if folder is not None:
                    logger.info(f"Stage name {name} is from event {folder}")
                else:
                    logger.warning("Cannot get the latest event, fallback to campaign_main")
                    folder = "campaign_main"
        catalog = self._effective_content_catalog()
        name = _normalize_stage_alias(name, folder, catalog)
        policy_config = cast("StagePolicyConfig", self.config)
        _apply_stage_alias_policies(name, folder, policy_config, catalog)
        name, is_stage_loop = _resolve_stage_loop_alias(
            name,
            folder,
            cast("StageLoopConfig", self.config),
            catalog,
        )
        self.is_stage_loop = self.is_stage_loop or is_stage_loop
        # Convert campaign_main to campaign hard if mode is hard and file exists
        if mode == "hard" and folder == "campaign_main" and name in map_files("campaign_hard"):
            folder = "campaign_hard"
        _apply_campaign_folder_policies(folder, policy_config, catalog)
        return name, folder

    def can_use_auto_search_continue(self):
        # Cannot update map info in auto search menu
        # Close it if map achievement is set
        if self.config.StopCondition_MapAchievement != "non_stop":
            return False

        return self.run_count > 0 and self.campaign.map_is_auto_search

    def handle_commission_notice(self):
        """
        Check commission notice.
        If found, stop current task and call commission.

        Raises:
            TaskEnd: If found commission notice.

        Pages:
            in: page_campaign
        """
        if self.campaign.commission_notice_show_at_campaign():
            logger.info("Commission notice found")
            self.config.task_call("Commission", force_call=True)
            self.config.task_stop("Commission notice found")

    def _ensure_campaign_run_ui(self, mode) -> None:
        self.device.stuck_record_clear()
        self.device.click_record_clear()
        if not self.device.has_cached_image:
            self.device.screenshot()
        self.campaign.device.image = self.device.image
        if self.campaign.is_in_map():
            logger.info("Already in map, retreating.")
            with suppress(CampaignEnd):
                self.campaign.withdraw()
            self.campaign.ensure_campaign_ui(name=self.stage, mode=mode)
        elif self.campaign.is_in_auto_search_menu():
            if self.can_use_auto_search_continue():
                logger.info("In auto search menu, skip ensure_campaign_ui.")
            else:
                logger.info("In auto search menu, closing.")
                # 某些活动的任务平衡器会移除当前 campaign，只重新进入活动 UI。
                self.campaign.ensure_campaign_ui(name=self.stage, mode=mode)
        else:
            self.campaign.ensure_campaign_ui(name=self.stage, mode=mode)
        self.disable_raid_on_event()
        self.handle_commission_notice()

    def _handle_campaign_after_run(self) -> bool:
        self.run_count += 1
        if self.config.StopCondition_RunCount:
            self.config.StopCondition_RunCount -= 1
        if self.triggered_stop_condition(oil_check=False):
            return True
        if self.campaign.config.MAP_IS_ONE_TIME_STAGE and self.run_count >= 1:
            logger.hr("Triggered one-time stage limit")
            self.campaign.handle_map_stop()
            return True
        if self.is_stage_loop and self.run_count >= 1:
            logger.hr("Triggered loop stage switch")
            return True
        if self.config.task_switched():
            self.campaign.ensure_auto_search_exit()
            self.config.task_stop()

        return False

    def run(self, name, folder="campaign_main", mode="normal", total=0):
        """
        Args:
            name (str): Name of .py file.
            folder (str): Name of the file folder under campaign.
            mode (str): `normal` or `hard`
            total (int):
        """
        name, folder = self.handle_stage_name(name, folder, mode=mode)
        self.config.override(Campaign_Name=name, Campaign_Event=folder)
        self.load_campaign(name, folder=folder)
        self.run_count = 0
        self.run_limit = self.config.StopCondition_RunCount
        while 1:
            # End
            if total and self.run_count >= total:
                break
            if self.campaign.event_time_limit_triggered():
                self.config.task_stop()

            # Log
            logger.hr(name, level=1)
            if self.config.StopCondition_RunCount > 0:
                logger.info(f"Count remain: {self.config.StopCondition_RunCount}")
            else:
                logger.info(f"Count: {self.run_count}")

            self._ensure_campaign_run_ui(mode)

            # if in hard mode, check remain times
            if self.ui_page_appear(page_campaign) and MODE_SWITCH_1.get(main=self) == "normal":
                ocr_hard_remain = importlib.import_module("module.hard.hard").OCR_HARD_REMAIN
                remain = ocr_hard_remain.ocr(self.device.image)
                if not remain:
                    logger.info("Remaining number of times of hard mode campaign_main is 0, delay task to next day")
                    self.config.task_delay(server_update=True)
                    break

            # End
            if self.triggered_stop_condition(oil_check=not self.campaign.is_in_auto_search_menu()):
                break

            # Run
            self.device.stuck_record_clear()
            self.device.click_record_clear()
            try:
                self.campaign.run()
            except ScriptEnd as e:
                logger.hr("Script end")
                logger.info(str(e))
                break

            if self._handle_campaign_after_run():
                break

        self.campaign.ensure_auto_search_exit()
