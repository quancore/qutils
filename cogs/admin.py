import re

from discord import AuditLogAction, Member, Role
from discord.ext import commands
from config import STRANGER_ROLE_NAME
from utils import permissions


class Admin(commands.Cog):
    """
    Admin functionality
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.command(name='remove_role', help='Remove / ban all members with a given role')
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True, kick_members=True, ban_members=True)
    async def remove_role(self, ctx, role: Role, remove_or_ban: int=0, exceptions: [Member]=None):
        guild=ctx.guild
        print(guild.name)
        print(role.name)


def setup(bot):
    bot.add_cog(Admin(bot))