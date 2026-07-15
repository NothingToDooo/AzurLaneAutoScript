from module.guild.lobby import GuildLobby
from module.guild.logistics import GuildLogistics
from module.guild.operations import GuildOperations


class RewardGuild(GuildLobby, GuildLogistics, GuildOperations):
    """供 typed guild workflow 复用公会 UI 能力。"""
