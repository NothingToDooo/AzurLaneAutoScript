import traceback
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from collections.abc import Iterator, ValuesView

from module.coalition import assets as coalition_assets
from module.event_hospital.assets import HOSIPITAL_CHECK
from module.freebies.assets import MAIL_ENTER
from module.raid import assets as raid_assets
from module.retire.assets import DOCK_CHECK
from module.ui import assets as ui_assets
from module.ui_white import assets as ui_white_assets


class Page:
    all_pages: ClassVar[dict[str, Page]] = {}

    @classmethod
    def clear_connection(cls) -> None:
        for page in cls.all_pages.values():
            page.parent = None

    @classmethod
    def init_connection(cls, destination) -> None:
        """从目标页反向填充各页面的 parent，供 UI 导航沿跳转链前进。"""
        cls.clear_connection()

        visited = [destination]
        visited = set(visited)
        while 1:
            new = visited.copy()
            for page in visited:
                for link in cls.iter_pages():
                    if link in visited:
                        continue
                    if page in link.links:
                        link.parent = page
                        new.add(link)
            if len(new) == len(visited):
                break
            visited = new

    @classmethod
    def iter_pages(cls) -> ValuesView[Page]:
        return cls.all_pages.values()

    @classmethod
    def iter_check_buttons(cls) -> Iterator[object]:
        for page in cls.all_pages.values():
            yield page.check_button

    def __init__(self, check_button):
        self.check_button = check_button
        self.links = {}
        text = traceback.extract_stack()[-2].line or ""
        self.name = text[: text.find("=")].strip()
        self.parent = None
        Page.all_pages[self.name] = self

    def __eq__(self, other):
        return self.name == other.name

    def __hash__(self):
        return hash(self.name)

    def __str__(self):
        return self.name

    def link(self, button, destination):
        self.links[destination] = button


# 使用舰队入口作为主页检查点，切页时可更快避开 info_bar。
page_main = Page(ui_assets.MAIN_GOTO_FLEET)
page_campaign_menu = Page(ui_assets.CAMPAIGN_MENU_CHECK)
page_campaign = Page(ui_assets.CAMPAIGN_CHECK)
page_fleet = Page(ui_assets.FLEET_CHECK)
page_main.link(button=ui_assets.MAIN_GOTO_CAMPAIGN, destination=page_campaign_menu)
page_main.link(button=ui_assets.MAIN_GOTO_FLEET, destination=page_fleet)
page_campaign_menu.link(button=ui_assets.CAMPAIGN_MENU_GOTO_CAMPAIGN, destination=page_campaign)
page_campaign_menu.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_campaign.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_campaign.link(button=ui_assets.BACK_ARROW, destination=page_campaign_menu)
page_fleet.link(button=ui_assets.GOTO_MAIN, destination=page_main)

# 新版主页以最后出现的 MAIN_GOTO_CAMPAIGN_WHITE 作为检查点。
page_main_white = Page(ui_white_assets.MAIN_GOTO_CAMPAIGN_WHITE)
page_main_white.link(button=ui_white_assets.MAIN_GOTO_CAMPAIGN_WHITE, destination=page_campaign_menu)
page_main_white.link(button=ui_white_assets.MAIN_GOTO_FLEET_WHITE, destination=page_fleet)

page_unknown = Page(None)
page_unknown.link(button=ui_assets.GOTO_MAIN, destination=page_main)

# 练习页只从战役菜单进入。
page_exercise = Page(ui_assets.EXERCISE_CHECK)
page_exercise.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_exercise.link(button=ui_assets.BACK_ARROW, destination=page_campaign_menu)
page_campaign_menu.link(button=ui_assets.CAMPAIGN_MENU_GOTO_EXERCISE, destination=page_exercise)

# 每日页只从战役菜单进入。
page_daily = Page(ui_assets.DAILY_CHECK)
page_daily.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_daily.link(button=ui_assets.BACK_ARROW, destination=page_campaign_menu)
page_campaign_menu.link(button=ui_assets.CAMPAIGN_MENU_GOTO_DAILY, destination=page_daily)

page_event = Page(ui_assets.EVENT_CHECK)
page_event.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_event.link(button=ui_assets.BACK_ARROW, destination=page_campaign)
page_campaign_menu.link(button=ui_assets.CAMPAIGN_MENU_GOTO_EVENT, destination=page_event)
page_campaign.link(button=ui_assets.CAMPAIGN_GOTO_EVENT, destination=page_event)

page_sp = Page(ui_assets.SP_CHECK)
page_sp.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_sp.link(button=ui_assets.BACK_ARROW, destination=page_campaign)
page_campaign_menu.link(button=ui_assets.CAMPAIGN_MENU_GOTO_EVENT, destination=page_sp)
page_campaign.link(button=ui_assets.CAMPAIGN_GOTO_EVENT, destination=page_sp)

page_coalition = Page(coalition_assets.FROSTFALL_COALITION_CHECK)
page_coalition.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_coalition.link(button=ui_assets.BACK_ARROW, destination=page_campaign_menu)
page_campaign_menu.link(button=ui_assets.CAMPAIGN_MENU_GOTO_EVENT, destination=page_coalition)

page_os = Page(ui_assets.OS_CHECK)
page_os.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_campaign_menu.link(button=ui_assets.CAMPAIGN_MENU_GOTO_OS, destination=page_os)

# 档案页只从战役菜单进入。
page_archives = Page(ui_assets.WAR_ARCHIVES_CHECK)
page_archives.link(button=ui_assets.WAR_ARCHIVES_GOTO_CAMPAIGN_MENU, destination=page_campaign_menu)
page_campaign_menu.link(button=ui_assets.CAMPAIGN_MENU_GOTO_WAR_ARCHIVES, destination=page_archives)

page_reward = Page(ui_assets.REWARD_CHECK)
page_reward.link(button=ui_assets.REWARD_GOTO_MAIN, destination=page_main)
page_main.link(button=ui_assets.MAIN_GOTO_REWARD, destination=page_reward)
page_main_white.link(button=ui_white_assets.MAIN_GOTO_REWARD_WHITE, destination=page_reward)

page_mission = Page(ui_assets.MISSION_CHECK)
page_mission.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_main.link(button=ui_assets.MAIN_GOTO_MISSION, destination=page_mission)
page_main_white.link(button=ui_white_assets.MAIN_GOTO_MISSION_WHITE, destination=page_mission)

page_guild = Page(ui_assets.GUILD_CHECK)
page_guild.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_main.link(button=ui_assets.MAIN_GOTO_GUILD, destination=page_guild)
page_main_white.link(button=ui_white_assets.MAIN_GOTO_GUILD_WHITE, destination=page_guild)

# 委托页只从奖励页进入。
page_commission = Page(ui_assets.COMMISSION_CHECK)
page_commission.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_commission.link(button=ui_assets.BACK_ARROW, destination=page_reward)
page_reward.link(button=ui_assets.REWARD_GOTO_COMMISSION, destination=page_commission)

# 战术学院只从奖励页进入，不经学院页。
page_tactical = Page(ui_assets.TACTICAL_CHECK)
page_tactical.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_tactical.link(button=ui_assets.BACK_ARROW, destination=page_reward)
page_reward.link(button=ui_assets.REWARD_GOTO_TACTICAL, destination=page_tactical)

page_battle_pass = Page(ui_assets.BATTLE_PASS_CHECK)
page_battle_pass.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_reward.link(button=ui_assets.REWARD_GOTO_BATTLE_PASS, destination=page_battle_pass)

page_event_list = Page(ui_assets.EVENT_LIST_CHECK)
page_event_list.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_main.link(button=ui_assets.MAIN_GOTO_EVENT_LIST, destination=page_event_list)
page_main_white.link(button=ui_white_assets.MAIN_GOTO_EVENT_LIST_WHITE, destination=page_event_list)

# Raid 仅从活动入口进入。
page_raid = Page(ui_assets.RAID_CHECK)
page_raid.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_raid.link(button=ui_assets.BACK_ARROW, destination=page_campaign_menu)
page_campaign_menu.link(button=ui_assets.CAMPAIGN_MENU_GOTO_EVENT, destination=page_raid)

page_dock = Page(DOCK_CHECK)
page_dock.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_main.link(button=ui_assets.MAIN_GOTO_DOCK, destination=page_dock)
page_main_white.link(button=ui_white_assets.MAIN_GOTO_DOCK_WHITE, destination=page_dock)

# 研究页只从研究菜单进入。
page_research = Page(ui_assets.RESEARCH_CHECK)
page_research.link(button=ui_assets.GOTO_MAIN, destination=page_main)

page_shipyard = Page(ui_assets.SHIPYARD_CHECK)
page_shipyard.link(button=ui_assets.GOTO_MAIN, destination=page_main)

page_meta = Page(ui_assets.META_CHECK)
page_meta.link(button=ui_assets.GOTO_MAIN, destination=page_main)

page_storage = Page(ui_assets.STORAGE_CHECK)
page_storage.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_main.link(button=ui_assets.MAIN_GOTO_STORAGE, destination=page_storage)
page_main_white.link(button=ui_white_assets.MAIN_GOTO_STORAGE_WHITE, destination=page_storage)

page_reshmenu = Page(ui_assets.RESHMENU_CHECK)
page_reshmenu.link(button=ui_assets.RESHMENU_GOTO_RESEARCH, destination=page_research)
page_reshmenu.link(button=ui_assets.RESHMENU_GOTO_SHIPYARD, destination=page_shipyard)
page_reshmenu.link(button=ui_assets.RESHMENU_GOTO_META, destination=page_meta)
page_reshmenu.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_main.link(button=ui_assets.MAIN_GOTO_RESHMENU, destination=page_reshmenu)
page_main_white.link(button=ui_assets.MAIN_GOTO_RESHMENU, destination=page_reshmenu)

page_dormmenu = Page(ui_assets.DORMMENU_CHECK)
page_dormmenu.link(button=ui_assets.DORMMENU_GOTO_MAIN, destination=page_main)
page_main.link(button=ui_assets.MAIN_GOTO_DORMMENU, destination=page_dormmenu)
page_main_white.link(button=ui_white_assets.MAIN_GOTO_DORMMENU_WHITE, destination=page_dormmenu)

# DORM_CHECK 取最后加载的“管理”按钮作为页面检查点。
page_dorm = Page(ui_assets.DORM_CHECK)
page_dormmenu.link(button=ui_assets.DORMMENU_GOTO_DORM, destination=page_dorm)
page_dorm.link(button=ui_assets.DORM_GOTO_MAIN, destination=page_main)

page_meowfficer = Page(ui_assets.MEOWFFICER_CHECK)
page_dormmenu.link(button=ui_assets.DORMMENU_GOTO_MEOWFFICER, destination=page_meowfficer)
page_meowfficer.link(button=ui_assets.MEOWFFICER_GOTO_DORMMENU, destination=page_main)

page_academy = Page(ui_assets.ACADEMY_CHECK)
page_dormmenu.link(button=ui_assets.DORMMENU_GOTO_ACADEMY, destination=page_academy)
page_academy.link(button=ui_assets.GOTO_MAIN, destination=page_main)

page_private_quarters = Page(ui_assets.PRIVATE_QUARTERS_CHECK)
page_dormmenu.link(button=ui_assets.DORMMENU_GOTO_PRIVATE_QUARTERS, destination=page_private_quarters)
page_private_quarters.link(button=ui_assets.PQ_GOTO_MAIN, destination=page_main)

page_game_room = Page(ui_assets.GAME_ROOM_CHECK)
page_academy.link(button=ui_assets.ACADEMY_GOTO_GAME_ROOM, destination=page_game_room)
page_game_room.link(button=ui_assets.GAME_ROOM_GOTO_MAIN, destination=page_main)

page_shop = Page(ui_assets.SHOP_CHECK)
page_shop.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_main.link(button=ui_assets.MAIN_GOTO_SHOP, destination=page_shop)
page_main_white.link(button=ui_white_assets.MAIN_GOTO_SHOP_WHITE, destination=page_shop)

page_munitions = Page(ui_assets.MUNITIONS_CHECK)
# 选择学院入口，载入后默认在普通商店，背景色更稳定。
page_academy.link(button=ui_assets.ACADEMY_GOTO_MUNITIONS, destination=page_munitions)
page_munitions.link(button=ui_assets.GOTO_MAIN, destination=page_main)

page_supply_pack = Page(ui_assets.SUPPLY_PACK_CHECK)
page_shop.link(button=ui_assets.SHOP_GOTO_SUPPLY_PACK, destination=page_supply_pack)
page_supply_pack.link(button=ui_assets.GOTO_MAIN, destination=page_main)

page_build = Page(ui_assets.BUILD_CHECK)
page_build.link(button=ui_assets.GOTO_MAIN, destination=page_main)
page_main.link(button=ui_assets.MAIN_GOTO_BUILD, destination=page_build)
page_main_white.link(button=ui_white_assets.MAIN_GOTO_BUILD_WHITE, destination=page_build)

page_mail = Page(ui_white_assets.MAIL_CHECK)
page_mail.link(button=ui_white_assets.GOTO_MAIN_WHITE, destination=page_main)
# 新旧主页使用不同邮件入口。
page_main_white.link(button=ui_white_assets.MAIL_ENTER_WHITE, destination=page_mail)
page_main.link(button=MAIL_ENTER, destination=page_mail)

# 新旧 UI 共用 CHANNEL_CHECK；点击左侧空白区域退出。
page_channel = Page(ui_assets.CHANNEL_CHECK)
page_channel.link(button=ui_assets.CAMPAIGN_MENU_GOTO_CAMPAIGN, destination=page_main)

page_rpg_stage = Page(raid_assets.RPG_GOTO_STORY)
page_rpg_story = Page(raid_assets.RPG_GOTO_STAGE)
page_rpg_stage.link(button=raid_assets.RPG_GOTO_STORY, destination=page_rpg_story)
page_rpg_stage.link(button=raid_assets.RPG_HOME, destination=page_main)
page_rpg_stage.link(button=raid_assets.RPG_BACK, destination=page_campaign_menu)
page_rpg_story.link(button=raid_assets.RPG_GOTO_STAGE, destination=page_rpg_stage)
page_rpg_story.link(button=raid_assets.RPG_HOME, destination=page_main)
page_rpg_story.link(button=raid_assets.RPG_BACK, destination=page_campaign_menu)

page_campaign_menu.link(button=ui_assets.CAMPAIGN_MENU_GOTO_EVENT, destination=page_rpg_stage)

page_rpg_city = Page(raid_assets.RPG_LEAVE_CITY)
page_rpg_city.link(button=raid_assets.RPG_LEAVE_CITY, destination=page_rpg_stage)
page_rpg_city.link(button=raid_assets.RPG_HOME, destination=page_main)

# Raid 模块会直接导入独立的 page_rpg_stage。

page_hospital = Page(HOSIPITAL_CHECK)
page_hospital.link(button=ui_white_assets.GOTO_MAIN_WHITE, destination=page_main)
page_campaign_menu.link(button=ui_assets.CAMPAIGN_MENU_GOTO_EVENT, destination=page_hospital)
