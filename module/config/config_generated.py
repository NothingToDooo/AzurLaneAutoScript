import datetime
from typing import ClassVar, TypedDict

from module.config.deep import MutableDeepValue

# 本文件由 module/config/config_updater.py 自动生成。
# 不要手动修改。

type ConfigValue = MutableDeepValue


class ConfigOverrides(TypedDict, total=False):
    SERVER: str
    SCHEDULER_PRIORITY: str
    ASSETS_FOLDER: str
    ASSETS_MODULE: str
    ASSETS_RESOLUTION: tuple[int, ...]
    BUTTON_OFFSET: int
    MAP_CLEAR_ALL_THIS_TIME: bool
    STAR_REQUIRE_1: int
    STAR_REQUIRE_2: int
    STAR_REQUIRE_3: int
    STAGE_ENTRANCE: tuple[str, ...]
    LV_TRIGGERED: bool
    LV32_TRIGGERED: bool
    STOP_IF_REACH_LV32: bool
    FORWARD_PORT_RANGE: tuple[int, ...]
    REVERSE_SERVER_PORT: int
    MINITOUCH_FILEPATH_REMOTE: str
    GEMS_EMOTION_TRIGGERED: bool
    STORY_OPTION: int
    STORY_ALLOW_SKIP: bool
    MAP_HAS_MODE_SWITCH: bool
    MAP_CHAPTER_SWITCH_20241219: bool
    MAP_CHAPTER_SWITCH_20241219_SP: bool
    MAP_CHAPTER_SWITCH_20241219_SPEX: bool
    STAGE_INCREASE_AB: bool
    STAGE_INCREASE_CUSTOM: str
    MAP_HAS_CLEAR_PERCENTAGE: bool
    MAP_CLEAR_PERCENTAGE_SHORT: bool
    MAP_HAS_WALK_SPEEDUP: bool
    MAP_HAS_AMBUSH: bool
    MAP_HAS_FLEET_STEP: bool
    MAP_HAS_MOVABLE_ENEMY: bool
    MAP_HAS_MOVABLE_NORMAL_ENEMY: bool
    MAP_HAS_SIREN: bool
    MAP_HAS_DYNAMIC_RED_BORDER: bool
    MAP_HAS_MAP_STORY: bool
    MAP_HAS_WALL: bool
    MAP_HAS_PT_BONUS: bool
    MAP_IS_ONE_TIME_STAGE: bool
    MAP_HAS_PORTAL: bool
    MAP_HAS_LAND_BASED: bool
    MAP_HAS_MAZE: bool
    MAP_HAS_FORTRESS: bool
    MAP_HAS_MISSILE_ATTACK: bool
    MAP_HAS_BOUNCING_ENEMY: bool
    MAP_HAS_DECOY_ENEMY: bool
    MAP_FOCUS_ENEMY_AFTER_BATTLE: bool
    MAP_ENEMY_TEMPLATE: tuple[str, ...]
    MAP_SIREN_TEMPLATE: tuple[str, ...]
    MAP_ENEMY_GENRE_DETECTION_SCALING: dict[str, MutableDeepValue]
    MAP_ENEMY_GENRE_SIMILARITY: float
    MAP_SIREN_MOVE_WAIT: float
    MAP_SIREN_COUNT: int
    MAP_SIREN_HAS_BOSS_ICON: bool
    MAP_SIREN_HAS_BOSS_ICON_SMALL: bool
    MAP_HAS_MYSTERY: bool
    MAP_MYSTERY_MAP_CLICK: bool
    MAP_MYSTERY_HAS_CARRIER: bool
    MAP_GRID_CENTER_TOLERANCE: float
    MOVABLE_ENEMY_FLEET_STEP: int
    MOVABLE_ENEMY_TURN: tuple[int, ...]
    MOVABLE_NORMAL_ENEMY_TURN: tuple[int, ...]
    POOR_MAP_DATA: bool
    MAP_SWIPE_MULTIPLY: tuple[float, ...]
    MAP_SWIPE_MULTIPLY_MINITOUCH: tuple[float, ...]
    MAP_SWIPE_DROP: float
    MAP_SWIPE_PREDICT: bool
    MAP_SWIPE_PREDICT_WITH_CURRENT_FLEET: bool
    MAP_SWIPE_PREDICT_WITH_SEA_GRIDS: bool
    MAP_ENSURE_EDGE_INSIGHT_CORNER: str
    MAP_WALK_USE_CURRENT_FLEET: bool
    MAP_WALK_TURNING_OPTIMIZE: bool
    MAP_SWIPE_OPTIMIZE: bool
    MAP_BOSS_APPEAR_REFOCUS_SWIPE: tuple[int, ...]
    SCREEN_SIZE: tuple[int, ...]
    DETECTING_AREA: tuple[int, ...]
    SCREEN_CENTER: tuple[float, ...]
    DETECTION_BACKEND: str
    GRID_IMAGE_A_MULTIPLY: float
    HOMO_TILE: tuple[int, ...]
    HOMO_CENTER_OFFSET: tuple[int, ...]
    HOMO_CORNER_OFFSET_LIST: tuple[tuple[int, ...], ...]
    HOMO_CANNY_THRESHOLD: tuple[int, ...]
    HOMO_CENTER_GOOD_THRESHOLD: float
    HOMO_CENTER_THRESHOLD: float
    HOMO_CORNER_THRESHOLD: float
    HOMO_RECTANGLE_THRESHOLD: int
    HOMO_EDGE_DETECT: bool
    HOMO_EDGE_HOUGHLINES_THRESHOLD: int
    HOMO_EDGE_COLOR_RANGE: tuple[int, ...]
    HOMO_STORAGE: MutableDeepValue
    INTERNAL_LINES_FIND_PEAKS_PARAMETERS: dict[str, tuple[int, ...] | tuple[float | int, ...] | int]
    EDGE_LINES_FIND_PEAKS_PARAMETERS: dict[str, tuple[int, ...] | int]
    INTERNAL_LINES_HOUGHLINES_THRESHOLD: int
    EDGE_LINES_HOUGHLINES_THRESHOLD: int
    HORIZONTAL_LINES_THETA_THRESHOLD: float
    VERTICAL_LINES_THETA_THRESHOLD: int
    TRUST_EDGE_LINES: bool
    TRUST_EDGE_LINES_THRESHOLD: int
    VANISH_POINT_RANGE: tuple[tuple[int, ...], ...]
    DISTANCE_POINT_X_RANGE: tuple[tuple[int, ...], ...]
    COINCIDENT_POINT_ENCOURAGE_DISTANCE: int
    ERROR_LINES_TOLERANCE: tuple[int, ...]
    MID_DIFF_RANGE_H: tuple[int, ...]
    MID_DIFF_RANGE_V: tuple[int, ...]
    OS_EXPLORE_FILTER: str
    OS_ACTION_POINT_BOX_USE: bool
    OS_ACTION_POINT_PRESERVE: int
    OS_CL1_YELLOW_COINS_PRESERVE: int
    OS_NORMAL_YELLOW_COINS_PRESERVE: int
    OS_NORMAL_PURPLE_COINS_PRESERVE: int
    OS_GLOBE_HOMO_STORAGE: tuple[tuple[int, ...] | tuple[tuple[int, ...], ...], ...]
    OS_GLOBE_DETECTING_AREA: tuple[int, ...]
    OS_GLOBE_IMAGE_PAD: int
    OS_GLOBE_IMAGE_RESIZE: float
    OS_GLOBE_FIND_PEAKS_PARAMETERS: dict[str, int]
    OS_LOCAL_FIND_PEAKS_PARAMETERS: dict[str, int]
    OS_GLOBE_SWIPE_MULTIPLY: tuple[float, ...]
    DOCK_FULL_TRIGGERED: bool
    GET_SHIP_TRIGGERED: bool
    COMMON_CV_THRESHOLD: float
    SHOP_EXTRACT_TEMPLATE: bool
    USE_DATA_KEY: bool
    Scheduler_Enable: bool
    Scheduler_NextRun: datetime.datetime
    Scheduler_Command: str
    Scheduler_SuccessInterval: int
    Scheduler_FailureInterval: int
    Scheduler_ServerUpdate: str
    Emulator_Serial: str
    Emulator_MuMuPath: str
    Error_HandleError: bool
    Error_SaveError: bool
    Error_OnePushConfig: str
    Error_ScreenshotLength: int
    Optimization_ScreenshotInterval: float
    Optimization_CombatScreenshotInterval: float
    Optimization_TaskHoardingDuration: int
    Optimization_WhenTaskQueueEmpty: str
    Retirement_RetireMode: str
    OneClickRetire_KeepLimitBreak: str
    Enhance_ShipToEnhance: str
    Enhance_Filter: str | None
    Enhance_CheckPerCategory: int
    OldRetire_N: bool
    OldRetire_R: bool
    OldRetire_SR: bool
    OldRetire_SSR: bool
    OldRetire_RetireAmount: str
    Campaign_Name: str
    Campaign_Event: str
    Campaign_Mode: str
    Campaign_UseClearMode: bool
    Campaign_UseFleetLock: bool
    Campaign_UseAutoSearch: bool
    Campaign_Use2xBook: bool
    Campaign_AmbushEvade: bool
    StopCondition_OilLimit: int
    StopCondition_RunCount: int
    StopCondition_MapAchievement: str
    StopCondition_StageIncrease: bool
    StopCondition_GetNewShip: bool
    StopCondition_ReachLevel: int
    Fleet_Fleet1: int
    Fleet_Fleet1Formation: str
    Fleet_Fleet1Mode: str
    Fleet_Fleet1Step: int
    Fleet_Fleet2: int
    Fleet_Fleet2Formation: str
    Fleet_Fleet2Mode: str
    Fleet_Fleet2Step: int
    Fleet_FleetOrder: str
    Submarine_Fleet: int
    Submarine_Mode: str
    Submarine_AutoSearchMode: str
    Submarine_DistanceToBoss: str
    Emotion_Mode: str
    Emotion_Fleet1Value: int
    Emotion_Fleet1Record: datetime.datetime
    Emotion_Fleet1Control: str
    Emotion_Fleet1Recover: str
    Emotion_Fleet1Oath: bool
    Emotion_Fleet2Value: int
    Emotion_Fleet2Record: datetime.datetime
    Emotion_Fleet2Control: str
    Emotion_Fleet2Recover: str
    Emotion_Fleet2Oath: bool
    HpControl_UseHpBalance: bool
    HpControl_UseEmergencyRepair: bool
    HpControl_UseLowHpRetreat: bool
    HpControl_HpBalanceThreshold: float
    HpControl_HpBalanceWeight: str
    HpControl_RepairUseSingleThreshold: float
    HpControl_RepairUseMultiThreshold: float
    HpControl_LowHpRetreatThreshold: float
    EnemyPriority_EnemyScaleBalanceWeight: str
    C11AffinityFarming_RunCount: int
    GemsFarming_ChangeFlagship: str
    GemsFarming_CommonCV: str
    GemsFarming_ChangeVanguard: str
    GemsFarming_CommonDD: str
    GemsFarming_CommissionLimit: bool
    EquipmentCode_ExportToConfig: bool
    EquipmentCode_Config: str | None
    EventGeneral_PtLimit: int
    EventGeneral_TimeLimit: datetime.datetime
    TaskBalancer_Enable: bool
    TaskBalancer_CoinLimit: int
    TaskBalancer_TaskCall: str
    EventDaily_StageFilter: str
    EventDaily_LastStage: int
    Raid_Mode: str
    Raid_UseTicket: bool
    RaidDaily_StageFilter: str
    Hospital_UseRecommendFleet: bool
    MaritimeEscort_Enable: bool
    Coalition_Mode: str
    Coalition_Fleet: str
    Commission_PresetFilter: str
    Commission_CustomFilter: str
    Commission_DoMajorCommission: bool
    Tactical_TacticalFilter: str
    Tactical_RapidTrainingSlot: str
    ControlExpOverflow_Enable: bool
    ControlExpOverflow_T4Allow: int
    ControlExpOverflow_T3Allow: int
    ControlExpOverflow_T2Allow: int
    ControlExpOverflow_T1Allow: int
    AddNewStudent_Enable: bool
    AddNewStudent_Favorite: bool
    AddNewStudent_MinLevel: int
    Research_UseCube: str
    Research_UseCoin: str
    Research_UsePart: str
    Research_AllowDelay: bool
    Research_PresetFilter: str
    Research_CustomFilter: str
    Dorm_Collect: bool
    Dorm_Feed: bool
    Dorm_FeedFilter: str
    BuyFurniture_Enable: bool
    BuyFurniture_BuyOption: str
    BuyFurniture_LastRun: datetime.datetime
    Meowfficer_BuyAmount: int
    Meowfficer_FortChoreMeowfficer: bool
    Meowfficer_OverflowCoins: int
    MeowfficerTrain_Enable: bool
    MeowfficerTrain_Mode: str
    MeowfficerTrain_RetainTalentedGold: bool
    MeowfficerTrain_RetainTalentedPurple: bool
    MeowfficerTrain_EnhanceIndex: int
    MeowfficerTrain_MaxFeedLevel: int
    GuildLogistics_Enable: bool
    GuildLogistics_SelectNewMission: bool
    GuildLogistics_ExchangeFilter: str
    GuildOperation_Enable: bool
    GuildOperation_SelectNewOperation: bool
    GuildOperation_NewOperationMaxDate: int
    GuildOperation_JoinThreshold: int
    GuildOperation_AttackBoss: bool
    GuildOperation_BossFleetRecommend: bool
    Reward_CollectOil: bool
    Reward_CollectCoin: bool
    Reward_CollectExp: bool
    Reward_CollectMission: bool
    Reward_CollectWeeklyMission: bool
    Awaken_LevelCap: str
    Awaken_Favourite: bool
    GeneralShop_UseGems: bool
    GeneralShop_Refresh: bool
    GeneralShop_BuySkinBox: bool
    GeneralShop_ConsumeCoins: bool
    GeneralShop_Filter: str
    GuildShop_Refresh: bool
    GuildShop_Filter: str
    GuildShop_BOX_T3: str
    GuildShop_BOX_T4: str
    GuildShop_BOOK_T2: str
    GuildShop_BOOK_T3: str
    GuildShop_RETROFIT_T2: str
    GuildShop_RETROFIT_T3: str
    GuildShop_PLATE_T2: str
    GuildShop_PLATE_T3: str
    GuildShop_PLATE_T4: str
    GuildShop_PR1: str
    GuildShop_PR2: str
    GuildShop_PR3: str
    MedalShop2_Filter: str
    MedalShop2_RETROFIT_T1: str
    MedalShop2_RETROFIT_T2: str
    MedalShop2_RETROFIT_T3: str
    MedalShop2_PLATE_T1: str
    MedalShop2_PLATE_T2: str
    MedalShop2_PLATE_T3: str
    MeritShop_Refresh: bool
    MeritShop_Filter: str
    CoreShop_Filter: str
    ShipyardDr_ResearchSeries: int
    ShipyardDr_ShipIndex: int
    ShipyardDr_BuyAmount: int
    ShipyardDr_LastRun: datetime.datetime
    Shipyard_ResearchSeries: int
    Shipyard_ShipIndex: int
    Shipyard_BuyAmount: int
    Shipyard_LastRun: datetime.datetime
    Gacha_Pool: str
    Gacha_Amount: int
    Gacha_UseTicket: bool
    Gacha_UseDrill: bool
    BattlePass_Collect: bool
    DataKey_Collect: bool
    DataKey_ForceCollect: bool
    Mail_ClaimMerit: bool
    Mail_ClaimMaintenance: bool
    Mail_ClaimTradeLicense: bool
    Mail_DeleteCollected: bool
    SupplyPack_Collect: bool
    SupplyPack_DayOfWeek: int
    Minigame_Collect: bool
    PrivateQuarters_BuyRoses: bool
    PrivateQuarters_BuyCake: bool
    PrivateQuarters_TargetInteract: bool
    PrivateQuarters_TargetShip: str
    Daily_UseDailySkip: bool
    Daily_EscortMission: str
    Daily_EscortMissionFleet: int
    Daily_AdvanceMission: str
    Daily_AdvanceMissionFleet: int
    Daily_FierceAssault: str
    Daily_FierceAssaultFleet: int
    Daily_TacticalTraining: str
    Daily_TacticalTrainingFleet: int
    Daily_SupplyLineDisruption: str
    Daily_ModuleDevelopment: str
    Daily_ModuleDevelopmentFleet: int
    Daily_EmergencyModuleDevelopment: str
    Daily_EmergencyModuleDevelopmentFleet: int
    Hard_HardStage: str
    Hard_HardFleet: int
    Exercise_OpponentChooseMode: str
    Exercise_OpponentTrial: int
    Exercise_ExerciseStrategy: str
    Exercise_LowHpThreshold: float
    Exercise_LowHpConfirmWait: float
    Exercise_OpponentRefreshValue: int
    Exercise_OpponentRefreshRecord: datetime.datetime
    OpsiAshAssist_Tier: int
    OpsiGeneral_UseLogger: bool
    OpsiGeneral_BuyActionPointLimit: int
    OpsiGeneral_OilLimit: int
    OpsiGeneral_RepairThreshold: float
    OpsiGeneral_DoRandomMapEvent: bool
    OpsiGeneral_AkashiShopFilter: str
    OpsiAshBeacon_AttackMode: str
    OpsiAshBeacon_OneHitMode: bool
    OpsiAshBeacon_DossierAutoAttackMode: bool
    OpsiAshBeacon_RequestAssist: bool
    OpsiAshBeacon_EnsureFullyCollected: bool
    OpsiFleetFilter_Filter: str
    OpsiFleet_Fleet: int
    OpsiFleet_Submarine: bool
    OpsiExplore_SpecialRadar: bool
    OpsiExplore_ForceRun: bool
    OpsiExplore_LastZone: int
    OpsiShop_PresetFilter: str
    OpsiShop_CustomFilter: str
    OpsiVoucher_Filter: str
    OpsiDaily_DoMission: bool
    OpsiDaily_UseTuningSample: bool
    OpsiObscure_ForceRun: bool
    OpsiAbyssal_ForceRun: bool
    OpsiStronghold_ForceRun: bool
    OpsiMonthBoss_Mode: str
    OpsiMonthBoss_CheckAdaptability: bool
    OpsiMonthBoss_ForceRun: bool
    OpsiMeowfficerFarming_ActionPointPreserve: int
    OpsiMeowfficerFarming_HazardLevel: int
    OpsiMeowfficerFarming_TargetZone: int
    OpsiHazard1Leveling_TargetZone: int
    Daemon_EnterMap: bool
    OpsiDaemon_RepairShip: bool
    OpsiDaemon_SelectEnemy: bool
    EventStory_SkipBattle: bool
    Benchmark_TestScene: str
    GameManager_AutoRestart: bool
    Storage_Storage: dict[str, MutableDeepValue]


class RecordUpdates(TypedDict, total=False):
    Emotion_Fleet1Value: int
    Emotion_Fleet2Value: int
    Exercise_OpponentRefreshValue: int


class GeneratedConfig:
    """
    Auto generated configuration
    """

    # 配置组 `Scheduler`
    # 可选项：True, False
    Scheduler_Enable = False
    Scheduler_NextRun = datetime.datetime(2020, 1, 1, 0, 0)
    Scheduler_Command = "Alas"
    Scheduler_SuccessInterval = 0
    Scheduler_FailureInterval = 120
    Scheduler_ServerUpdate = "00:00"

    # 配置组 `Emulator`
    Emulator_Serial = "127.0.0.1:16384"
    Emulator_MuMuPath = "C:/Program Files/Netease/MuMu Player 12/nx_main/MuMuNxMain.exe"

    # 配置组 `Error`
    Error_HandleError = True
    Error_SaveError = True
    Error_OnePushConfig = "provider: null"
    Error_ScreenshotLength = 12

    # 配置组 `Optimization`
    Optimization_ScreenshotInterval = 0.3
    Optimization_CombatScreenshotInterval = 1.0
    Optimization_TaskHoardingDuration = 0
    # 可选项：stay_there, goto_main, close_game
    Optimization_WhenTaskQueueEmpty = "goto_main"

    # 配置组 `Retirement`
    # 可选项：one_click_retire, enhance, old_retire
    Retirement_RetireMode = "one_click_retire"

    # 配置组 `OneClickRetire`
    # 可选项：keep_limit_break, do_not_keep
    OneClickRetire_KeepLimitBreak = "keep_limit_break"

    # 配置组 `Enhance`
    # 可选项：all, favourite
    Enhance_ShipToEnhance = "all"
    Enhance_Filter = None
    Enhance_CheckPerCategory = 5

    # 配置组 `OldRetire`
    OldRetire_N = True
    OldRetire_R = True
    OldRetire_SR = False
    OldRetire_SSR = False
    # 可选项：retire_all, retire_10
    OldRetire_RetireAmount = "retire_all"

    # 配置组 `Campaign`
    Campaign_Name = "12-4"
    # 可选项：campaign_main
    Campaign_Event = "campaign_main"
    # 可选项：normal, hard
    Campaign_Mode = "normal"
    Campaign_UseClearMode = True
    Campaign_UseFleetLock = True
    Campaign_UseAutoSearch = True
    Campaign_Use2xBook = False
    Campaign_AmbushEvade = True

    # 配置组 `StopCondition`
    StopCondition_OilLimit = 1000
    StopCondition_RunCount = 0
    # 可选项：non_stop, 100_percent_clear, map_3_stars, threat_safe, threat_safe_without_3_stars
    StopCondition_MapAchievement = "non_stop"
    StopCondition_StageIncrease = False
    StopCondition_GetNewShip = False
    StopCondition_ReachLevel = 0

    # 配置组 `Fleet`
    # 可选项：1, 2, 3, 4, 5, 6
    Fleet_Fleet1 = 1
    # 可选项：line_ahead, double_line, diamond
    Fleet_Fleet1Formation = "double_line"
    # 可选项：combat_auto, combat_manual, stand_still_in_the_middle, hide_in_bottom_left, hide_in_upper_left
    Fleet_Fleet1Mode = "combat_auto"
    # 可选项：2, 3, 4, 5
    Fleet_Fleet1Step = 3
    # 可选项：0, 1, 2, 3, 4, 5, 6
    Fleet_Fleet2 = 2
    # 可选项：line_ahead, double_line, diamond
    Fleet_Fleet2Formation = "double_line"
    # 可选项：combat_auto, combat_manual, stand_still_in_the_middle, hide_in_bottom_left, hide_in_upper_left
    Fleet_Fleet2Mode = "combat_auto"
    # 可选项：2, 3, 4, 5
    Fleet_Fleet2Step = 2
    # 可选项：fleet1_mob_fleet2_boss, fleet1_boss_fleet2_mob, fleet1_all_fleet2_standby, fleet1_standby_fleet2_all
    Fleet_FleetOrder = "fleet1_mob_fleet2_boss"

    # 配置组 `Submarine`
    # 可选项：0, 1, 2
    Submarine_Fleet = 0
    # 可选项：do_not_use, hunt_only, boss_only, hunt_and_boss, every_combat
    Submarine_Mode = "do_not_use"
    # 可选项：sub_standby, sub_auto_call
    Submarine_AutoSearchMode = "sub_standby"
    # 可选项：to_boss_position, 1_grid_to_boss, 2_grid_to_boss, use_open_ocean_support
    Submarine_DistanceToBoss = "2_grid_to_boss"

    # 配置组 `Emotion`
    # 可选项：calculate, ignore, calculate_ignore
    Emotion_Mode = "calculate"
    Emotion_Fleet1Value = 119
    Emotion_Fleet1Record = datetime.datetime(2020, 1, 1, 0, 0)
    # 可选项：keep_exp_bonus, prevent_green_face, prevent_yellow_face, prevent_red_face
    Emotion_Fleet1Control = "prevent_green_face"
    # 可选项：not_in_dormitory, dormitory_floor_1, dormitory_floor_2
    Emotion_Fleet1Recover = "not_in_dormitory"
    Emotion_Fleet1Oath = False
    Emotion_Fleet2Value = 119
    Emotion_Fleet2Record = datetime.datetime(2020, 1, 1, 0, 0)
    # 可选项：keep_exp_bonus, prevent_green_face, prevent_yellow_face, prevent_red_face
    Emotion_Fleet2Control = "prevent_green_face"
    # 可选项：not_in_dormitory, dormitory_floor_1, dormitory_floor_2
    Emotion_Fleet2Recover = "not_in_dormitory"
    Emotion_Fleet2Oath = False

    # 配置组 `HpControl`
    HpControl_UseHpBalance = False
    HpControl_UseEmergencyRepair = False
    HpControl_UseLowHpRetreat = False
    HpControl_HpBalanceThreshold = 0.2
    HpControl_HpBalanceWeight = "1000, 1000, 1000"
    HpControl_RepairUseSingleThreshold = 0.3
    HpControl_RepairUseMultiThreshold = 0.6
    HpControl_LowHpRetreatThreshold = 0.3

    # 配置组 `EnemyPriority`
    # 可选项：default_mode, S3_enemy_first, S1_enemy_first
    EnemyPriority_EnemyScaleBalanceWeight = "default_mode"

    # 配置组 `C11AffinityFarming`
    C11AffinityFarming_RunCount = 32

    # 配置组 `GemsFarming`
    # 可选项：ship, ship_equip
    GemsFarming_ChangeFlagship = "ship"
    # 可选项：any, langley, bogue, ranger, hermes
    GemsFarming_CommonCV = "any"
    # 可选项：disabled, ship, ship_equip
    GemsFarming_ChangeVanguard = "ship"
    # 可选项：any, favourite, aulick_or_foote, cassin_or_downes, z20_or_z21
    GemsFarming_CommonDD = "any"
    GemsFarming_CommissionLimit = True

    # 配置组 `EquipmentCode`
    EquipmentCode_ExportToConfig = True
    EquipmentCode_Config = None

    # 配置组 `EventGeneral`
    EventGeneral_PtLimit = 0
    EventGeneral_TimeLimit = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `TaskBalancer`
    TaskBalancer_Enable = False
    TaskBalancer_CoinLimit = 10000
    # 可选项：Main, Main2, Main3
    TaskBalancer_TaskCall = "Main"

    # 配置组 `EventDaily`
    EventDaily_StageFilter = "A1 > A2 > A3"
    EventDaily_LastStage = 0

    # 配置组 `Raid`
    # 可选项：easy, normal, hard, ex
    Raid_Mode = "hard"
    Raid_UseTicket = False

    # 配置组 `RaidDaily`
    RaidDaily_StageFilter = "hard > normal > easy"

    # 配置组 `Hospital`
    Hospital_UseRecommendFleet = True

    # 配置组 `MaritimeEscort`
    MaritimeEscort_Enable = True

    # 配置组 `Coalition`
    # 可选项：tc1, tc2, tc3, sp, ex
    Coalition_Mode = "tc3"
    # 可选项：single, multi
    Coalition_Fleet = "single"

    # 配置组 `Commission`
    # 可选项：cube, cube_24h, chip, chip_24h, oil, custom
    Commission_PresetFilter = "cube"
    Commission_CustomFilter = (
        "DailyEvent > Gem-4 > Gem-2 > Gem-8 > ExtraCube-0:30\n"
        "> UrgentCube-1:30 > UrgentCube-1:45 > UrgentCube-3\n"
        "> ExtraDrill-5:20 > ExtraDrill-2 > ExtraDrill-3:20\n"
        "> UrgentCube-2:15 > UrgentCube-4\n"
        "> ExtraDrill-1 > UrgentCube-6 > ExtraCube-1:30\n"
        "> ExtraDrill-2:40 > ExtraDrill-0:20\n"
        "> Major > DailyChip > DailyResource\n"
        "> ExtraPart-0:30 > ExtraOil-1 > UrgentBox-6\n"
        "> ExtraCube-3 > ExtraPart-1 > UrgentBox-3\n"
        "> ExtraCube-4 > ExtraPart-1:30 > ExtraOil-4\n"
        "> UrgentBox-1 > ExtraCube-5 > UrgentBox-1\n"
        "> ExtraCube-8 > ExtraOil-8\n"
        "> UrgentDrill-4 > UrgentDrill-2:40 > UrgentDrill-2\n"
        "> UrgentDrill-1 > UrgentDrill-1:30 > UrgentDrill-1:10\n"
        "> Extra-0:20 > Extra-0:30 > Extra-1:00 > Extra-1:30 > Extra-2:00\n"
        "> shortest"
    )
    Commission_DoMajorCommission = False

    # 配置组 `Tactical`
    Tactical_TacticalFilter = (
        "SameT4 > SameT3 > SameT2 > SameT1\n"
        "> BlueT2 > YellowT2 > RedT2\n"
        "> BlueT3 > YellowT3 > RedT3\n"
        "> BlueT4 > YellowT4 > RedT4\n"
        "> BlueT1 > YellowT1 > RedT1\n"
        "> first"
    )
    # 可选项：do_not_use, slot_1, slot_2, slot_3, slot_4
    Tactical_RapidTrainingSlot = "do_not_use"

    # 配置组 `ControlExpOverflow`
    ControlExpOverflow_Enable = True
    ControlExpOverflow_T4Allow = 100
    ControlExpOverflow_T3Allow = 100
    ControlExpOverflow_T2Allow = 200
    ControlExpOverflow_T1Allow = 200

    # 配置组 `AddNewStudent`
    AddNewStudent_Enable = False
    AddNewStudent_Favorite = False
    AddNewStudent_MinLevel = 50

    # 配置组 `Research`
    # 可选项：always_use, only_05_hour, only_no_project, do_not_use
    Research_UseCube = "only_05_hour"
    # 可选项：always_use, only_05_hour, only_no_project, do_not_use
    Research_UseCoin = "always_use"
    # 可选项：always_use, only_05_hour, only_no_project, do_not_use
    Research_UsePart = "always_use"
    Research_AllowDelay = True
    # 可选项：custom, series_9_blueprint_ta152, series_9_blueprint_only, series_9_ta152_only, series_8_blueprint_305,
    # series_8_blueprint_only, series_8_305_only, series_7_blueprint_la9, series_7_blueprint_only,
    # series_7_la9_only, series_6_blueprint_203, series_6_blueprint_only, series_6_203_only, series_5_blueprint_152,
    # series_5_blueprint_only, series_5_152_only, series_4_blueprint_tenrai, series_4_blueprint_only,
    # series_4_tenrai_only, series_3_blueprint_234, series_3_blueprint_only, series_3_234_only,
    # series_2_than_3_457_234, series_2_blueprint_457, series_2_blueprint_only, series_2_457_only
    Research_PresetFilter = "series_9_blueprint_ta152"
    Research_CustomFilter = (
        "S9-DR0.5 > S9-PRY0.5 > S9-Q0.5 > S9-H0.5 > Q0.5 > S9-DR2.5\n"
        "> S9-G1.5 > S9-Q1 > S9-DR5 > 0.5 > S9-G4 > S9-Q2 > S9-PRY2.5 > S8-E-880 > S8-E-180 > reset\n"
        "> S9-DR8 > Q1 > 1 > S9-E-315 > S9-G2.5 > G1.5 > 1.5 > S9-E-031\n"
        "> S9-Q4 > Q2 > E2 > 2 > DR2.5 > PRY2.5 > G2.5 > 2.5 > S9-PRY5\n"
        "> S9-PRY8 > Q4 > G4 > 4 > S9-C6 > DR5 > PRY5 > 5 > C6 > 6 > S9-C8\n"
        "> S9-C12 > DR8 > PRY8 > C8 > 8 > C12 > 12"
    )

    # 配置组 `Dorm`
    Dorm_Collect = True
    Dorm_Feed = True
    Dorm_FeedFilter = "20000 > 10000 > 5000 > 3000 > 2000 > 1000"

    # 配置组 `BuyFurniture`
    BuyFurniture_Enable = False
    # 可选项：set, all
    BuyFurniture_BuyOption = "all"
    BuyFurniture_LastRun = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Meowfficer`
    Meowfficer_BuyAmount = 1
    Meowfficer_FortChoreMeowfficer = True
    Meowfficer_OverflowCoins = -1

    # 配置组 `MeowfficerTrain`
    MeowfficerTrain_Enable = False
    # 可选项：seamlessly, once_a_day
    MeowfficerTrain_Mode = "seamlessly"
    MeowfficerTrain_RetainTalentedGold = True
    MeowfficerTrain_RetainTalentedPurple = True
    MeowfficerTrain_EnhanceIndex = 1
    MeowfficerTrain_MaxFeedLevel = 5

    # 配置组 `GuildLogistics`
    GuildLogistics_Enable = True
    GuildLogistics_SelectNewMission = False
    GuildLogistics_ExchangeFilter = (
        "PlateTorpedoT1 > PlateAntiAirT1 > PlatePlaneT1 > PlateGunT1 > PlateGeneralT1\n"
        "> PlateTorpedoT2 > PlateAntiAirT2 > PlatePlaneT2 > PlateGunT2 > PlateGeneralT2\n"
        "> PlateTorpedoT3 > PlateAntiAirT3 > PlatePlaneT3 > PlateGunT3 > PlateGeneralT3\n"
        "> OxyCola > Coolant > Merit > Coin > Oil"
    )

    # 配置组 `GuildOperation`
    GuildOperation_Enable = True
    GuildOperation_SelectNewOperation = False
    GuildOperation_NewOperationMaxDate = 15
    GuildOperation_JoinThreshold = 1
    GuildOperation_AttackBoss = True
    GuildOperation_BossFleetRecommend = False

    # 配置组 `Reward`
    Reward_CollectOil = True
    Reward_CollectCoin = True
    Reward_CollectExp = True
    Reward_CollectMission = True
    Reward_CollectWeeklyMission = True

    # 配置组 `Awaken`
    # 可选项：level120, level125
    Awaken_LevelCap = "level120"
    Awaken_Favourite = False

    # 配置组 `GeneralShop`
    GeneralShop_UseGems = False
    GeneralShop_Refresh = False
    GeneralShop_BuySkinBox = False
    GeneralShop_ConsumeCoins = False
    GeneralShop_Filter = "BookRedT3 > BookYellowT3 > BookBlueT3 > BookRedT2\n> Cube\n> FoodT6 > FoodT5"

    # 配置组 `GuildShop`
    GuildShop_Refresh = True
    GuildShop_Filter = "PlateT4 > BookT3 > PR > CatT3 > Chip > BookT2 > Retrofit > FoodT6 > FoodT5 > CatT2 > BoxT4"
    # 可选项：eagle, royal, sakura, ironblood
    GuildShop_BOX_T3 = "ironblood"
    # 可选项：eagle, royal, sakura, ironblood
    GuildShop_BOX_T4 = "ironblood"
    # 可选项：red, blue, yellow
    GuildShop_BOOK_T2 = "red"
    # 可选项：red, blue, yellow
    GuildShop_BOOK_T3 = "red"
    # 可选项：dd, cl, bb, cv
    GuildShop_RETROFIT_T2 = "cl"
    # 可选项：dd, cl, bb, cv
    GuildShop_RETROFIT_T3 = "cl"
    # 可选项：general, gun, torpedo, antiair, plane
    GuildShop_PLATE_T2 = "general"
    # 可选项：general, gun, torpedo, antiair, plane
    GuildShop_PLATE_T3 = "general"
    # 可选项：general, gun, torpedo, antiair, plane
    GuildShop_PLATE_T4 = "gun"
    # 可选项：neptune, monarch, ibuki, izumo, roon, saintlouis
    GuildShop_PR1 = "neptune"
    # 可选项：seattle, georgia, kitakaze, gascogne
    GuildShop_PR2 = "seattle"
    # 可选项：cheshire, mainz, odin, champagne
    GuildShop_PR3 = "cheshire"

    # 配置组 `MedalShop2`
    MedalShop2_Filter = (
        "DR > PR\n"
        "> BookRedT3 > BookYellowT3 > BookBlueT3\n"
        "> BookRedT2 > BookYellowT2 > BookBlueT2\n"
        "> RetrofitT3\n"
        "> FoodT6 > FoodT5\n"
        "> PlateGeneralT3 > PlateWildT3"
    )
    # 可选项：dd, cl, bb, cv
    MedalShop2_RETROFIT_T1 = "cl"
    # 可选项：dd, cl, bb, cv
    MedalShop2_RETROFIT_T2 = "cl"
    # 可选项：dd, cl, bb, cv
    MedalShop2_RETROFIT_T3 = "cl"
    # 可选项：general, gun, torpedo, antiair, plane
    MedalShop2_PLATE_T1 = "general"
    # 可选项：general, gun, torpedo, antiair, plane
    MedalShop2_PLATE_T2 = "general"
    # 可选项：general, gun, torpedo, antiair, plane
    MedalShop2_PLATE_T3 = "general"

    # 配置组 `MeritShop`
    MeritShop_Refresh = False
    MeritShop_Filter = "Cube"

    # 配置组 `CoreShop`
    CoreShop_Filter = "Array"

    # 配置组 `ShipyardDr`
    # 可选项：2, 3, 4, 5
    ShipyardDr_ResearchSeries = 2
    # 可选项：0, 1, 2, 3, 4, 5, 6
    ShipyardDr_ShipIndex = 0
    ShipyardDr_BuyAmount = 2
    ShipyardDr_LastRun = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Shipyard`
    # 可选项：1, 2, 3, 4, 5, 6
    Shipyard_ResearchSeries = 1
    # 可选项：0, 1, 2, 3, 4, 5, 6
    Shipyard_ShipIndex = 0
    Shipyard_BuyAmount = 2
    Shipyard_LastRun = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `Gacha`
    # 可选项：light, heavy, special, event, wishing_well
    Gacha_Pool = "light"
    # 可选项：1, 2, 3, 4, 5, 6, 7, 8, 9, 10
    Gacha_Amount = 1
    Gacha_UseTicket = True
    Gacha_UseDrill = False

    # 配置组 `BattlePass`
    BattlePass_Collect = True

    # 配置组 `DataKey`
    DataKey_Collect = True
    DataKey_ForceCollect = False

    # 配置组 `Mail`
    Mail_ClaimMerit = True
    Mail_ClaimMaintenance = False
    Mail_ClaimTradeLicense = False
    Mail_DeleteCollected = True

    # 配置组 `SupplyPack`
    SupplyPack_Collect = True
    # 可选项：0, 1, 2, 3, 4, 5, 6
    SupplyPack_DayOfWeek = 0

    # 配置组 `Minigame`
    Minigame_Collect = False

    # 配置组 `PrivateQuarters`
    PrivateQuarters_BuyRoses = True
    PrivateQuarters_BuyCake = False
    PrivateQuarters_TargetInteract = True
    # 可选项：anchorage, noshiro, sirius, new_jersey, taihou, aegir, nakhimov
    PrivateQuarters_TargetShip = "anchorage"

    # 配置组 `Daily`
    Daily_UseDailySkip = True
    # 可选项：skip, first, second, third
    Daily_EscortMission = "first"
    # 可选项：1, 2, 3, 4, 5, 6
    Daily_EscortMissionFleet = 1
    # 可选项：skip, first, second, third
    Daily_AdvanceMission = "first"
    # 可选项：1, 2, 3, 4, 5, 6
    Daily_AdvanceMissionFleet = 1
    # 可选项：skip, first, second, third
    Daily_FierceAssault = "first"
    # 可选项：1, 2, 3, 4, 5, 6
    Daily_FierceAssaultFleet = 1
    # 可选项：skip, first, second, third
    Daily_TacticalTraining = "second"
    # 可选项：1, 2, 3, 4, 5, 6
    Daily_TacticalTrainingFleet = 1
    # 可选项：skip, first, second, third
    Daily_SupplyLineDisruption = "second"
    # 可选项：skip, first, second
    Daily_ModuleDevelopment = "first"
    # 可选项：1, 2, 3, 4, 5, 6
    Daily_ModuleDevelopmentFleet = 1
    # 可选项：skip, first, second
    Daily_EmergencyModuleDevelopment = "first"
    # 可选项：1, 2, 3, 4, 5, 6
    Daily_EmergencyModuleDevelopmentFleet = 1

    # 配置组 `Hard`
    Hard_HardStage = "11-4"
    # 可选项：1, 2
    Hard_HardFleet = 1

    # 配置组 `Exercise`
    # 可选项：max_exp, easiest, leftmost, easiest_else_exp
    Exercise_OpponentChooseMode = "max_exp"
    Exercise_OpponentTrial = 1
    # 可选项：aggressive, fri18, sat0, sat12, sat18, sun0, sun12, sun18
    Exercise_ExerciseStrategy = "aggressive"
    Exercise_LowHpThreshold = 0.4
    Exercise_LowHpConfirmWait = 0.1
    Exercise_OpponentRefreshValue = 0
    Exercise_OpponentRefreshRecord = datetime.datetime(2020, 1, 1, 0, 0)

    # 配置组 `OpsiAshAssist`
    OpsiAshAssist_Tier = 15

    # 配置组 `OpsiGeneral`
    OpsiGeneral_UseLogger = True
    # 可选项：0, 1, 2, 3, 4, 5
    OpsiGeneral_BuyActionPointLimit = 0
    OpsiGeneral_OilLimit = 1000
    OpsiGeneral_RepairThreshold = 0.4
    OpsiGeneral_DoRandomMapEvent = True
    OpsiGeneral_AkashiShopFilter = "ActionPoint > PurpleCoins"

    # 配置组 `OpsiAshBeacon`
    # 可选项：current, current_dossier
    OpsiAshBeacon_AttackMode = "current"
    OpsiAshBeacon_OneHitMode = True
    OpsiAshBeacon_DossierAutoAttackMode = False
    OpsiAshBeacon_RequestAssist = True
    OpsiAshBeacon_EnsureFullyCollected = True

    # 配置组 `OpsiFleetFilter`
    OpsiFleetFilter_Filter = "Fleet-4 > CallSubmarine > Fleet-2 > Fleet-3 > Fleet-1"

    # 配置组 `OpsiFleet`
    # 可选项：1, 2, 3, 4
    OpsiFleet_Fleet = 1
    OpsiFleet_Submarine = False

    # 配置组 `OpsiExplore`
    OpsiExplore_SpecialRadar = False
    OpsiExplore_ForceRun = False
    OpsiExplore_LastZone = 0

    # 配置组 `OpsiShop`
    # 可选项：max_benefit, max_benefit_meta, no_meta, all, custom
    OpsiShop_PresetFilter = "max_benefit_meta"
    OpsiShop_CustomFilter = (
        "LoggerAbyssalT6 > LoggerAbyssalT5 > LoggerObscure > LoggerAbyssalT4 > ActionPoint > PurpleCoins\n"
        "> GearDesignPlanT3 > PlateRandomT4 > DevelopmentMaterialT3 > GearDesignPlanT2 > GearPart\n"
        "> OrdnanceTestingReportT3 > OrdnanceTestingReportT2 > DevelopmentMaterialT2 > "
        "OrdnanceTestingReportT1\n"
        "> METARedBook > CrystallizedHeatResistantSteel > NanoceramicAlloy > NeuroplasticProstheticArm > "
        "SupercavitationGenerator"
    )

    # 配置组 `OpsiVoucher`
    OpsiVoucher_Filter = "LoggerAbyssal > LoggerObscure > Book > Coin > Fragment"

    # 配置组 `OpsiDaily`
    OpsiDaily_DoMission = True
    OpsiDaily_UseTuningSample = True

    # 配置组 `OpsiObscure`
    OpsiObscure_ForceRun = False

    # 配置组 `OpsiAbyssal`
    OpsiAbyssal_ForceRun = False

    # 配置组 `OpsiStronghold`
    OpsiStronghold_ForceRun = False

    # 配置组 `OpsiMonthBoss`
    # 可选项：normal, normal_hard
    OpsiMonthBoss_Mode = "normal"
    OpsiMonthBoss_CheckAdaptability = True
    OpsiMonthBoss_ForceRun = False

    # 配置组 `OpsiMeowfficerFarming`
    OpsiMeowfficerFarming_ActionPointPreserve = 1000
    # 可选项：3, 4, 5, 6, 10
    OpsiMeowfficerFarming_HazardLevel = 5
    OpsiMeowfficerFarming_TargetZone = 0

    # 配置组 `OpsiHazard1Leveling`
    # 可选项：0, 44, 22
    OpsiHazard1Leveling_TargetZone = 0

    # 配置组 `Daemon`
    Daemon_EnterMap = True

    # 配置组 `OpsiDaemon`
    OpsiDaemon_RepairShip = True
    OpsiDaemon_SelectEnemy = True

    # 配置组 `EventStory`
    # 可选项：True, False
    EventStory_SkipBattle = False

    # 配置组 `Benchmark`
    # 可选项：screenshot_click, screenshot, click
    Benchmark_TestScene = "screenshot_click"

    # 配置组 `GameManager`
    GameManager_AutoRestart = True

    # 配置组 `Storage`
    Storage_Storage: ClassVar[dict[str, MutableDeepValue]] = {}
