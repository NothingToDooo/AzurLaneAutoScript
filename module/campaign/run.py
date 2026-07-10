import copy
import importlib
import random
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Protocol, cast

from module.campaign.campaign_event import CampaignEvent
from module.campaign.campaign_ui import MODE_SWITCH_1
from module.content.legacy_stage import LegacyStageModuleAdapter, LoadedCampaignModule, LoadedStage
from module.content.models import StageRef
from module.exception import CampaignEnd, RequestHumanTakeover, ScriptEnd
from module.handler.fast_forward import map_files, to_map_file_name
from module.logger import logger
from module.ui.page import page_campaign

if TYPE_CHECKING:
    from module.campaign.campaign_base import CampaignBase
    from module.config.config import AzurLaneConfig


class StageLoopConfig(Protocol):
    STAGE_LOOP_ALIAS: dict[tuple[str, str], str]
    StopCondition_RunCount: int

    def override(self, **kwargs: object) -> None: ...


class StagePolicyConfig(Protocol):
    StopCondition_MapAchievement: str

    def override(self, **kwargs: object) -> None: ...


@dataclass(frozen=True, slots=True)
class _CampaignLoadState:
    name: str
    folder: str
    stage: str
    loaded: LoadedCampaignModule
    loaded_stage: LoadedStage | None
    campaign: CampaignBase


SP_STAGE_ALIASES = {
    "event_20201126_cn": {"vsp": "sp"},
    "event_20210723_cn": {"vsp": "sp"},
    "event_20220324_cn": {"esp": "sp"},
    "event_20220818_cn": {"esp": "sp"},
    "event_20221124_cn": {"asp": "sp", "a.sp": "sp"},
    "event_20240724_cn": {"ysp": "sp", "y.sp": "sp"},
}

CHAPTER_T_EVENTS = {
    "event_20211125_cn",
    "event_20231026_cn",
    "event_20241024_cn",
    "event_20250424_cn",
    "event_20250724_cn",
    "event_20250814_cn",
    "event_20251023_cn",
    "event_20260326_cn",
    "event_20260625_cn",
    "war_archives_20230525_cn",
    "war_archives_20231026_cn",
    "war_archives_20240725_cn",
}

CHAPTER_T_STAGE_ALIASES = {
    "a1": "t1",
    "a2": "t2",
    "a3": "t3",
    "a4": "t4",
    "a5": "t5",
    "a6": "t6",
    "sp1": "t1",
    "sp2": "t2",
    "sp3": "t3",
    "sp4": "t4",
    "sp5": "t5",
    "sp6": "t6",
}

CHAPTER_ABCD_EVENTS = {
    "event_20200917_cn",
    "event_20221124_cn",
    "event_20230525_cn",
    "war_archives_20200917_cn",
    "event_20211125_cn",
    "event_20231026_cn",
    "event_20231123_cn",
    "event_20240725_cn",
    "event_20240829_cn",
    "event_20241024_cn",
    "event_20241121_cn",
    "event_20250424_cn",
    "event_20250724_cn",
    "event_20250814_cn",
    "event_20251023_cn",
    "event_20260326_cn",
    "event_20260625_cn",
    "war_archives_20230525_cn",
    "war_archives_20231026_cn",
    "war_archives_20240725_cn",
}

CHAPTER_ABCD_STAGE_ALIASES = {
    "a1": "t1",
    "a2": "t2",
    "a3": "t3",
    "b1": "t4",
    "b2": "t5",
    "b3": "t6",
    "c1": "ht1",
    "c2": "ht2",
    "c3": "ht3",
    "d1": "ht4",
    "d2": "ht5",
    "d3": "ht6",
}

CHAPTER_ABCD_STAGE_REVERSED_ALIASES = {value: key for key, value in CHAPTER_ABCD_STAGE_ALIASES.items()}


def _normalize_stage_alias(name: str, folder: str) -> str:
    """归一化地图文件名里的活动别名。"""
    name = SP_STAGE_ALIASES.get(folder, {}).get(name, name)

    if folder == "event_20240425_cn":
        if name in ["μsp", "usp", "iisp"]:
            name = "sp"
        name = name.replace("lsp", "isp").replace("1sp", "isp")
        if name == "isp":
            name = "isp1"

    if folder in CHAPTER_T_EVENTS:
        name = CHAPTER_T_STAGE_ALIASES.get(name, name)

    if folder in CHAPTER_ABCD_EVENTS:
        name = CHAPTER_ABCD_STAGE_ALIASES.get(name, name)
    else:
        name = CHAPTER_ABCD_STAGE_REVERSED_ALIASES.get(name, name)

    # event_20221124_cn 的地图文件使用 th 前缀。
    if folder == "event_20221124_cn":
        name = name.replace("ht", "th")

    if folder == "event_20230817_cn" and name.startswith("e0"):
        name = "a1"

    if folder == "event_20240829_cn" and name == "tp":
        name = "sp"

    return name


def _resolve_stage_loop_alias(name: str, folder: str, config: StageLoopConfig) -> tuple[str, bool]:
    """处理循环关卡别名，返回实际关卡名和是否命中循环。"""
    for alias_key, stages_value in config.STAGE_LOOP_ALIAS.items():
        alias_folder, alias = alias_key
        if folder != alias_folder or name != alias.lower():
            continue

        stages = [i.strip(" \t\r\n") for i in stages_value.split(">")]
        cycle = len(stages)
        count = int(config.StopCondition_RunCount)
        if count == 0:
            stage = random.choice(stages)
            logger.info(f"Loop stages in {name.upper()}, run random stage: {stage}")
        else:
            index = count % cycle
            index = 0 if index == 0 else cycle - index
            stage = stages[index]
            logger.info(f"Loop stages in {name.upper()} with remain run_count={count}, run ordered stage: {stage}")

        logger.info("disable continuous clear")
        config.override(StopCondition_MapAchievement="non_stop")
        config.override(StopCondition_StageIncrease=False)
        return stage.lower(), True

    return name, False


def _apply_stage_alias_policies(name: str, folder: str, config: StagePolicyConfig) -> None:
    """应用依赖归一化关卡名的运行策略。"""
    if folder == "event_20221124_cn" and name.startswith("th") and config.StopCondition_MapAchievement != "non_stop":
        logger.info(
            "When running chapter TH of event_20221124_cn, StopCondition.MapAchievement is forced set to threat_safe"
        )
        config.override(StopCondition_MapAchievement="threat_safe")

    if folder == "event_20250724_cn" and name.startswith("ts") and config.StopCondition_MapAchievement != "non_stop":
        logger.info(
            "When running chapter TS of event_20250724_cn, StopCondition.MapAchievement is forced set to threat_safe"
        )
        config.override(StopCondition_MapAchievement="threat_safe")

    if folder == "event_20211125_cn" and "tss" in name:
        config.override(
            StopCondition_OilLimit=0,  # 无油耗。
            StopCondition_MapAchievement="100_percent_clear",
            StopCondition_StageIncrease=True,
            Emotion_Mode="ignore",  # 无心情消耗。
            Fleet_Fleet2=0,  # 只有一队。
            Submarine_Fleet=0,  # 无潜艇。
        )


def _apply_campaign_folder_policies(folder: str, config: StagePolicyConfig) -> None:
    """应用只依赖活动目录的运行策略。"""
    if folder != "event_20240912_cn":
        return

    if config.StopCondition_MapAchievement == "threat_safe":
        logger.info("In event_20240912_cn, MapAchievement=threat_safe fallback to map_3_stars")
        config.override(StopCondition_MapAchievement="map_3_stars")
    if config.StopCondition_MapAchievement == "threat_safe_without_3_stars":
        logger.info("In event_20240912_cn, MapAchievement=threat_safe_without_3_stars fallback to 100_percent_clear")
        config.override(StopCondition_MapAchievement="100_percent_clear")


class CampaignRun(CampaignEvent):
    folder: str
    name: str
    stage: str
    stage_adapter = LegacyStageModuleAdapter()
    loaded_campaign: LoadedCampaignModule
    loaded_stage: LoadedStage | None = None
    config: AzurLaneConfig
    campaign: CampaignBase
    run_count: int
    run_limit: int
    is_stage_loop = False

    def _campaign_identity_matches(self, name: str, folder: str) -> bool:
        return getattr(self, "name", None) == name and getattr(self, "folder", None) == folder

    def _stage_for_reference(self, name: str, folder: str) -> str:
        if folder.startswith("campaign_"):
            return "-".join(name.split("_")[1:3])
        if folder.startswith(("event", "war_archives")):
            return name
        return name

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
        if self._campaign_identity_matches(name, folder):
            return False

        ref = StageRef(pack_id=folder, stage_id=name)
        try:
            loaded = self.stage_adapter.load(ref)
        except ModuleNotFoundError as error:
            self._raise_campaign_not_found(ref, error)

        state = self._build_campaign_load(name, folder, loaded, loaded)
        self._commit_campaign_load(state)
        return True

    def load_campaign_helper(self, name: str, folder: str) -> bool:
        """装载不带地图的历史战役辅助模块。"""
        if self._campaign_identity_matches(name, folder):
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
        name = _normalize_stage_alias(name, folder)
        policy_config = cast("StagePolicyConfig", self.config)
        _apply_stage_alias_policies(name, folder, policy_config)
        name, is_stage_loop = _resolve_stage_loop_alias(name, folder, cast("StageLoopConfig", self.config))
        self.is_stage_loop = self.is_stage_loop or is_stage_loop
        # Convert campaign_main to campaign hard if mode is hard and file exists
        if mode == "hard" and folder == "campaign_main" and name in map_files("campaign_hard"):
            folder = "campaign_hard"
        _apply_campaign_folder_policies(folder, policy_config)
        if folder == "event_20260417_cn" and name == "vsp":
            name = "sp"
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
                # event_20240725 的任务平衡器会移除当前 campaign，只重新进入活动 UI。
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
