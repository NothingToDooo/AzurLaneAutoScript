from module.guild.lobby import GuildLobby
from module.guild.logistics import GuildLogistics
from module.guild.operations import GuildOperations
from module.ui.page import page_guild, page_main


class RewardGuild(GuildLobby, GuildLogistics, GuildOperations):
    def run(self):
        """从主页执行公会大厅、后勤和作战任务，最后回到主页。"""
        if not self.config.GuildLogistics_Enable and not self.config.GuildOperation_Enable:
            self.config.Scheduler_Enable = False
            self.config.task_stop()

        self.ui_ensure(page_guild)
        success = True

        self.guild_lobby()

        if self.config.GuildLogistics_Enable:
            success &= self.guild_logistics()

        if self.config.GuildOperation_Enable:
            success &= self.guild_operations()

        self.ui_goto(page_main)

        if success:
            self.config.task_delay(server_update=True)
        else:
            self.config.task_delay(success=False, server_update=True)
