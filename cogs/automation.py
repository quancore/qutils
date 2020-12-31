import logging
import asyncio

from discord.ext import commands
from discord.ext.tasks import loop
from discord.utils import get


from utils.config import ANNOUNCEMENT_CHANNEL_ID, GUILD_ID, ACTIVITY_INCLUDED_ROLES, ACTIVITY_ROLE_NAME, \
    num_announce_days, announcement_template
from cogs.admin import Admin
from utils import helpers
from utils.formats import CustomEmbed

log = logging.getLogger('root')


class Announcement(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.guild = None
        self.announcement_channel = None

        self.announce_inactive_members.start()

    def cog_unload(self):
        self.announce_inactive_members.cancel()

    @commands.Cog.listener()
    async def on_ready(self):
        """ Schedule initial works for confession cog """
        asyncio.ensure_future(self.update_guild_channel(),
                              loop=self.bot.loop)

    async def update_guild_channel(self):
        """ Fetch guild and channel objects if not set """
        if self.guild is None:
            self.guild = await helpers.get_guild_by_id(self.bot, GUILD_ID)
            self.announcement_channel = await helpers.get_channel_by_id(self.bot, self.guild, ANNOUNCEMENT_CHANNEL_ID)

    @loop(hours=num_announce_days*24)
    async def announce_inactive_members(self):
        """ Announce inactive members from announcement channel """
        if self.announcement_channel:
            # get global exception members and include them in exceptions
            global_exception_member_records = await Admin.fetch_all_exceptions(self.bot.pool, self.guild.id)

            global_exception_members, exception_member_text = [], ''
            for record in global_exception_member_records:
                member = await helpers.get_member_by_id(self.guild, record['member_id'])
                if member:
                    global_exception_members.append(member)
                    exception_member_text += f'{member.mention} - ' \
                                             f'Until: **{record["until"].strftime("%Y-%m-%d %H:%M:%S")}**\n'

            activity_role = get(self.guild.roles, name=ACTIVITY_ROLE_NAME)
            if ACTIVITY_INCLUDED_ROLES and activity_role:
                member_ids, member_mention_text = await helpers.get_inactive_members(self.guild,
                                                                                     ACTIVITY_INCLUDED_ROLES,
                                                                                     activity_role,
                                                                                     exceptions=global_exception_members)

                if member_ids:
                    f_announcement_template = announcement_template.format(activity_role.name, activity_role.name)
                    embed_dict = {'title': 'Announcement',
                                  'description': f_announcement_template,
                                  'fields': [
                                      {'name': '**__Members__**:', 'value': member_mention_text, 'inline': False}, ]
                                  }
                    if exception_member_text:
                        val = {'name': '**__Server Wide exceptions__**', 'value': exception_member_text, 'inline': False}
                        embed_dict['fields'].append(val)

                    try:
                        e = CustomEmbed.from_dict(embed_dict, avatar_url=self.bot.user.avatar_url)
                    except Exception as err:
                        log.exception(err)
                    else:
                        await self.announcement_channel.send(embed=e.to_embed())

            if self.announce_inactive_members.next_iteration:
                log.info(f'Next iteration for inactive member announcement will occur: '
                         f'{self.announce_inactive_members.next_iteration.strftime("%Y-%m-%d %H:%M:%S")}')

    @announce_inactive_members.before_loop
    async def before_announce_inactive_members(self):
        """ Pre-task handler for announce_inactive_members"""
        await self.bot.wait_until_ready()
        await self.update_guild_channel()


def setup(bot):
    bot.add_cog(Announcement(bot))
