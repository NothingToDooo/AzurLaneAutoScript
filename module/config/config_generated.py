import datetime
from typing import ClassVar

# 本文件由 module/config/config_updater.py 自动生成。
# 不要手动修改。


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
    Emulator_Serial = "auto"
    # 可选项：auto, com.bilibili.azurlane
    Emulator_PackageName = "auto"
    # 可选项：disabled, cn_android-0, cn_android-1, cn_android-2, cn_android-3, cn_android-4, cn_android-5,
    # cn_android-6, cn_android-7, cn_android-8, cn_android-9, cn_android-10, cn_android-11, cn_android-12,
    # cn_android-13, cn_android-14, cn_android-15, cn_android-16, cn_android-17, cn_android-18, cn_android-19,
    # cn_android-20, cn_android-21, cn_android-22, cn_android-23, cn_android-24, cn_android-25, cn_android-26,
    # cn_android-27, cn_android-28
    Emulator_ServerName = "disabled"
    # 可选项：nemu_ipc
    Emulator_ScreenshotMethod = "nemu_ipc"
    # 可选项：minitouch
    Emulator_ControlMethod = "minitouch"
    Emulator_ScreenshotDedithering = False
    Emulator_AdbRestart = False

    # 配置组 `EmulatorInfo`
    # 可选项：auto, MuMuPlayer, MuMuPlayerX, MuMuPlayer12
    EmulatorInfo_Emulator = "auto"
    EmulatorInfo_name = None
    EmulatorInfo_path = None

    # 配置组 `Error`
    Error_HandleError = True
    Error_SaveError = True
    Error_ScreenshotLength = 1

    # 配置组 `Optimization`
    Optimization_ScreenshotInterval = 0.3
    Optimization_CombatScreenshotInterval = 1.0
    Optimization_TaskHoardingDuration = 0
    # 可选项：stay_there, goto_main, close_game
    Optimization_WhenTaskQueueEmpty = "goto_main"

    # 配置组 `DropRecord`
    DropRecord_SaveFolder = "./screenshots"
    # 可选项：do_not, save
    DropRecord_ResearchRecord = "do_not"
    # 可选项：do_not, save
    DropRecord_CommissionRecord = "do_not"
    # 可选项：do_not, save
    DropRecord_CombatRecord = "do_not"
    # 可选项：do_not, save
    DropRecord_OpsiRecord = "do_not"
    # 可选项：do_not, save
    DropRecord_MeowfficerBuy = "do_not"
    # 可选项：do_not, save
    DropRecord_MeowfficerTalent = "do_not"

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

    # 配置组 `C72MysteryFarming`
    C72MysteryFarming_StepOnA3 = True

    # 配置组 `C122MediumLeveling`
    # 可选项：0, 1, 2, 10
    C122MediumLeveling_LargeEnemyTolerance = 1

    # 配置组 `C124LargeLeveling`
    # 可选项：0, 1, 2
    C124LargeLeveling_NonLargeEnterTolerance = 1
    # 可选项：0, 1, 2, 10
    C124LargeLeveling_NonLargeRetreatTolerance = 1
    # 可选项：3, 4, 5
    C124LargeLeveling_PickupAmmo = 3

    # 配置组 `GemsFarming`
    # 可选项：any, langley, bogue, ranger, hermes
    GemsFarming_CommonCV = "any"
    # 可选项：disabled, ship
    GemsFarming_ChangeVanguard = "ship"
    # 可选项：any, favourite, aulick_or_foote, cassin_or_downes, z20_or_z21
    GemsFarming_CommonDD = "any"
    GemsFarming_CommissionLimit = True

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
    # 可选项：custom, series_8_blueprint_305, series_8_blueprint_only, series_8_305_only, series_7_blueprint_la9,
    # series_7_blueprint_only, series_7_la9_only, series_6_blueprint_203, series_6_blueprint_only,
    # series_6_203_only, series_5_blueprint_152, series_5_blueprint_only, series_5_152_only,
    # series_4_blueprint_tenrai, series_4_blueprint_only, series_4_tenrai_only, series_3_blueprint_234,
    # series_3_blueprint_only, series_3_234_only, series_2_than_3_457_234, series_2_blueprint_457,
    # series_2_blueprint_only, series_2_457_only
    Research_PresetFilter = "series_8_blueprint_305"
    Research_CustomFilter = (
        "S8-DR0.5 > S8-PRY0.5 > S8-Q0.5 > S8-H0.5 > Q0.5 > S8-DR2.5\n"
        "> S8-G1.5 > S8-Q1 > S8-DR5 > 0.5 > S8-G4 > S8-Q2 > S8-PRY2.5 > reset\n"
        "> S8-DR8 > Q1 > 1 > S8-E-315 > S8-G2.5 > G1.5 > 1.5 > S8-E-031\n"
        "> S8-Q4 > Q2 > E2 > 2 > DR2.5 > PRY2.5 > G2.5 > 2.5 > S8-PRY5\n"
        "> S8-PRY8 > Q4 > G4 > 4 > S8-C6 > DR5 > PRY5 > 5 > C6 > 6 > S8-C8\n"
        "> S8-C12 > DR8 > PRY8 > C8 > 8 > C12 > 12"
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
    GeneralShop_Filter = (
        "BookRedT3 > BookYellowT3 > BookBlueT3 > BookRedT2\n"
        "> Cube\n"
        "> FoodT6 > FoodT5"
    )

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

    # 配置组 `Sos`
    # 可选项：3, 4, 5, 6, 7, 8, 9, 10
    Sos_Chapter = 3

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
    # 可选项：emulator
    Benchmark_DeviceType = "emulator"
    # 可选项：screenshot_click, screenshot, click
    Benchmark_TestScene = "screenshot_click"

    # 配置组 `GameManager`
    GameManager_AutoRestart = True

    # 配置组 `Storage`
    Storage_Storage: ClassVar[dict[str, object]] = {}
