import random
import string
import asyncio
import asyncpg
import hashlib
import json
import textwrap
import datetime
import validators

from PIL import Image
from io import BytesIO

# this just allows for nice function annotation, and stops my IDE from complaining.
# from typing import Union

from discord.ext import commands
from discord.errors import NotFound
import typing
from discord import File, TextChannel, Guild, InvalidArgument, Forbidden, HTTPException, RawMessageDeleteEvent, \
    RawBulkMessageDeleteEvent

import logging
from config import VALID_STATS_ROLES, ADMIN_ROLE_NAMES, GUILD_ID, message_timeout, warn_limit, command_cooldown
from utils import db, helpers
from utils.formats import CustomEmbed
from libneko import pag

log = logging.getLogger('root')


class Themes(db.Table):
    theme_id = db.Column(db.Integer(big=True), primary_key=True)
    guild_id = db.Column(db.Integer(big=True), primary_key=True)
    theme_name = db.Column(db.String, nullable=False)
    theme_explanation = db.Column(db.String, default='')
    created_by = db.Column(db.Integer(big=True), nullable=False)
    timestamp = db.Column(db.Datetime, nullable=False)


class Talks(db.Table):
    talk_id = db.Column(db.Integer(big=True), primary_key=True)
    guild_id = db.Column(db.Integer(big=True), primary_key=True)
    theme_id = db.Column(db.Integer(big=True))
    talk_topic = db.Column(db.String, nullable=False)
    talk_explanation = db.Column(db.String, default='')
    additional_links = db.Column(db.JSON, default="'{}'::jsonb")
    created_by = db.Column(db.Integer(big=True), default=-1)
    timestamp = db.Column(db.Datetime, nullable=False)
    # theme_id = db.Column(db.ForeignKey("themes", "theme_id", sql_type=db.Integer(big=True),
    #                                    on_delete='CASCADE',
    #                                    on_update='CASCADE')
    #                      )
    # theme_guild_id = db.Column(db.ForeignKey("themes", "guild_id", sql_type=db.Integer(big=True),
    #                                          on_delete='CASCADE',
    #                                          on_update='CASCADE')
    #                            )

    @classmethod
    def create_table(cls, *, exists_ok=True):
        statement = super().create_table(exists_ok=exists_ok)
        sql = "FOREIGN KEY (guild_id, theme_id) REFERENCES themes (guild_id, theme_id) " \
              "ON DELETE CASCADE ON UPDATE CASCADE);"
        return statement[:-2] + ',' + sql

def wrapper_text_msg(context, is_empty=False):
    """
    Wrapper for wait_for predicate. It return c or - or any text with at least one letter.
    If is_empty is True, it will get - as well
    """
    def check_message(m):
        if m.author.id != context.author.id:
            return False
        if m.channel != context.channel:
            return False

        check_res = m.content == 'c' or (len(m.content) > 0 and any(c.isalpha() for c in m.content))
        if is_empty:
            check_res = check_res or m.content == '-'

        return check_res

    return check_message


class _Talks(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

    # ********** theme command group **********************
    @commands.group(name='theme', help='Command group for themes',
                    usage='This is not a command but a command group.', hidden=True,
                    aliases=['t'])
    async def theme(self, ctx):
        pass

    @theme.command(name='create', help='Create a theme',
                   usage='Type the command and follow the dialogs',
                   aliases=['make', 'c'])
    @commands.has_any_role(*ADMIN_ROLE_NAMES)
    @commands.guild_only()
    async def create_theme(self, ctx):
        """ Create a theme for topic creation. """
        author = ctx.author
        channel = ctx.message.channel
        guild = ctx.guild
        # Handle bots (me lol)
        if author.bot:
            return

        await channel.send(f"**What is your theme name?**\n"
                           f"Enter few word for theme name, no worries there is a screen for explanation\n"
                           f"**Ex: sexual relationship, politics**"
                           f"You have **{message_timeout} seconds** to complete.\n"
                           f"For canceling, send **'c'** ")
        try:
            theme_or_cancel = await self.bot.wait_for("message",
                                                      check=wrapper_text_msg(ctx),
                                                      timeout=message_timeout)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to give a server id has timed out. Please "
                                      "give your confession again to be able to provide another.")
        except commands.UserInputError as err:
            raise err

        if theme_or_cancel.content == 'c':
            return await channel.send('Command has cancelled.')

        theme_name = str(theme_or_cancel.content)
        theme_id = int(hashlib.md5(theme_name.encode('utf-8')).hexdigest(), 16) % (10 ** 16)

        theme_explanation = f'A theme for {theme_name} talks'

        await channel.send(f"**Explain your theme in few sentences?**\n"
                           f"Why have you created this theme\n"
                           f"Ex: I have created this theme for matching political talks"
                           f"You have **{message_timeout} seconds** to complete.\n"
                           f"**Default explanation: {theme_explanation}** \n"
                           f"For canceling, send **'c'**. For default, send **'-'**")
        try:
            theme_or_cancel = await self.bot.wait_for("message",
                                                      check=wrapper_text_msg(ctx, is_empty=True),
                                                      timeout=message_timeout)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to give a server id has timed out. Please "
                                      "give your confession again to be able to provide another.")
        except commands.UserInputError as err:
            raise err

        if theme_or_cancel.content == 'c':
            return await channel.send('Command has cancelled.')

        if theme_or_cancel.content != '-':
            theme_explanation = str(theme_or_cancel.content)

        query = 'INSERT INTO themes ' \
                'VALUES ($1, $2, $3, $4, $5, $6)'
        query_params = (theme_id, guild.id, theme_name, theme_explanation,
                        author.id, datetime.datetime.utcnow())
        try:
            await ctx.db.execute(query, *query_params)
        except asyncpg.UniqueViolationError:
            return await channel.send(f'The theme: **{theme_name}** has already in the system.')

    async def _list_and_get_theme(self, ctx, guild: Guild, question: str = None, any_theme: bool = False):
        """
        List all themes and get the selection if needed
        If question given, the question sent to user and return selected theme_id. Basically, it is a display function
        if question is not given.
        If question is not None and any_theme is True, the first option is Any theme, which return -1 if selected by user
        """
        query = 'SELECT * from themes ' \
                'WHERE guild_id = $1'

        records = await self.bot.pool.fetch(query, guild.id)
        if len(records) == 0:
            raise ValueError('No theme found')

        nav = pag.EmbedNavigatorFactory(max_lines=20)
        nav.add_line('**__Themes__**')
        if question is not None and any_theme:
            row_num_to_id = {1: -1}
            nav.add_line("**1) Any theme**")
            nav.add_line('**-----------------------------**')
        else:
            row_num_to_id = {}

        for index, (_id, _, theme_name, exp, member_id, date) in enumerate(records, start=len(row_num_to_id)):
            member = await helpers.get_member_by_id(guild, member_id)
            member_text = member.mention if member else "No member found"
            line = f'**{index + 1}) Theme ID**: {_id} | **{date.strftime("%Y-%m-%d")}**\n' \
                   f'**Theme name**: {theme_name}\n' \
                   f'**Exp**: {exp}\n' \
                   f'**Theme author**: {member_text}'
            row_num_to_id[index + 1] = _id
            nav.add_line(line)
            nav.add_line('**-----------------------------**')

        nav.start(ctx=ctx)

        if question:
            try:
                theme_id, _ = await helpers.get_multichoice_answer(self.bot, ctx, row_num_to_id, question, timeout=60)
            except asyncio.TimeoutError as e:
                raise e
            else:
                return theme_id

    @theme.command(name='fetch', help='Fetch all themes',
                   usage='Type the command and follow the dialogs',
                   aliases=['list', 'f'])
    @commands.has_any_role(*VALID_STATS_ROLES)
    @commands.guild_only()
    async def fetch_theme(self, ctx):
        try:
            await self._list_and_get_theme(ctx, ctx.guild)
        except ValueError:
            return await ctx.send('No record found...')

    @theme.command(name='delete', help='Delete a theme',
                   usage='Type the command and follow the dialogs',
                   aliases=['remove', 'd'])
    @commands.has_permissions(manage_messages=True, manage_channels=True)
    @commands.guild_only()
    async def delete_theme(self, ctx):
        question = 'Please type the row number for delete a theme otherwise type **"c"**\n' \
                   '**THE THEME AND ALL RELATED TALKS WILL BE DELETED IRREVOCABLY!!!**'

        try:
            theme_id = await self._list_and_get_theme(ctx, ctx.guild, question=question)
        except ValueError:
            return await ctx.send('No theme found...')
        except asyncio.TimeoutError:
            return await ctx.send('The command has timed out')

        if theme_id is None:
            return await ctx.send('Command has been cancelled.')

        query = f"""DELETE FROM themes
                    WHERE guild_id = $1
                    AND theme_id = $2
                 """

        await ctx.db.execute(query, ctx.guild.id, theme_id)

    # ********** talks command group **********************
    @commands.group(name='talks', help='Command group for talks',
                    usage='This is not a command but a command group.', hidden=True,
                    aliases=['ta'])
    async def talks(self, ctx):
        pass

    @talks.command(name='create', help='Create a talk topic for a theme',
                   usage='Type the command and follow the dialogs',
                   aliases=['make', 'c'])
    @commands.dm_only()
    async def create_talk(self, ctx):
        """ Create a talk for a theme. """
        all_sent_messages = []
        author = ctx.author
        channel = ctx.message.channel
        # Handle bots (me lol)
        if author.bot:
            return

        bot_guilds = await self.bot.fetch_guilds(limit=150).flatten()
        # filter guilds to keep only guild the user in
        guilds = [guild for guild in bot_guilds if await helpers.get_member_by_id(guild, author.id) is not None]
        if len(guilds) == 0:
            return await ctx.send('There is no server currently set for this command.\n')

        guild_dict = {index + 1: guild for index, guild in enumerate(guilds)}
        guild_text = '\n'.join([f'**{index}) {guild.name}**' for index, guild in guild_dict.items()])
        question = f"**Which server you want to create a talk topic?**\n" \
                   f"Please choose the number or press **c** cancel it\n" \
                   f"**__Servers__**\n" \
                   f"{guild_text}"

        try:
            guild, _ = await helpers.get_multichoice_answer(self.bot, ctx, guild_dict, question)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to provide the choice is timeout. Please "
                                      "give your confession again to be able to provide another.")
        except commands.UserInputError as err:
            raise err

        if guild is None:
            return await ctx.send('Command has been cancelled.')

        question = f"**First, select the theme you want to create a talk topic**\n" \
                   f"If you do not find related theme, contact with a privileged person to add a new theme\n" \
                   f"You have **60 seconds** to complete.\n" \
                   f"For canceling, send 'c' "
        try:
            theme_id = await self._list_and_get_theme(ctx, guild, question=question)
        except ValueError:
            return await ctx.send('No record found...')
        except asyncio.TimeoutError:
            return await ctx.send('The command has timed out')

        if theme_id is None:
            return await ctx.send('Command has been cancelled.')

        await channel.send(f"**Provide few sentences about your talk topic**\n "
                           f"No worries about details, there will be a screen for details of your talk.\n"
                           f"Ex: Which one is preferred: rude or polite males?\n"
                           f"You have **{message_timeout} seconds** to complete.\n"
                           f"For canceling, send 'c'.")
        try:
            talk_topic = await self.bot.wait_for("message",
                                                 check=wrapper_text_msg(ctx),
                                                 timeout=message_timeout)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to give a server id has timed out. Please "
                                      "give your confession again to be able to provide another.")
        except commands.UserInputError as err:
            raise err

        if talk_topic.content == 'c':
            return await channel.send('Command has cancelled.')

        talk_details_str = 'No details given for this talk'
        await channel.send(f"**Give the details of the talk if you have; otherwise, send '-'**\n "
                           f"Ex: Usually polite male may first seem attractive but it can change with time etc.\n"
                           f"You have **{message_timeout} seconds** to complete.\n"
                           f"For canceling, send 'c'.")
        try:
            talk_details = await self.bot.wait_for("message",
                                                   check=wrapper_text_msg(ctx, is_empty=True),
                                                   timeout=message_timeout)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to give a server id has timed out. Please "
                                      "give your confession again to be able to provide another.")
        except commands.UserInputError as err:
            raise err

        if talk_details.content == 'c':
            return await channel.send('Command has cancelled.')

        if talk_details.content != '-':
            talk_details_str = str(talk_details.content)

        def check_link_message(m):
            if m.author.id != author.id:
                return False
            if m.channel != ctx.channel:
                return False

            url_validator = lambda x: all((validators.url(link) for link in x.splitlines()))

            return m.content == 'c' or m.content == '-' or (len(m.content) > 0 and url_validator(m.content))

        talk_links_list = []
        await channel.send(f"**If you have additional links related to talk topic, please type them**\n "
                           f"Links should be formatted at one link per line. You can use ALT+ENTER to go new line.\n"
                           f"You have **{message_timeout} seconds** to complete.\n"
                           f"For canceling, send 'c'. For skipping, type '-'")
        try:
            talk_details = await self.bot.wait_for("message",
                                                   check=check_link_message,
                                                   timeout=message_timeout)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to give a server id has timed out. Please "
                                      "give your confession again to be able to provide another.")
        except commands.UserInputError as err:
            raise err

        if talk_details.content == 'c':
            return await channel.send('Command has cancelled.')

        if talk_details.content != '-':
            talk_links_list = str(talk_details.content).splitlines()

        talk_author_id = -1
        is_identity = await ctx.prompt(f'**Do you want to share your identity as the talk topic author?**',
                                       author_id=author.id)
        if is_identity:
            talk_author_id = author.id

        talk_id = int(hashlib.md5(talk_topic.content.encode('utf-8')).hexdigest(), 16) % (10 ** 16)

        query = 'INSERT INTO talks ' \
                'VALUES ($1, $2, $3, $4, $5::jsonb, $6, $7, $8)'
        query_params = (talk_id, guild.id, theme_id, talk_topic.content, talk_details_str,
                        json.dumps(talk_links_list), talk_author_id, datetime.datetime.utcnow())
        try:
            await ctx.db.execute(query, *query_params)
        except asyncpg.UniqueViolationError as err:
            return await channel.send(f'The talk topic: {talk_topic} has already in the system.')

    @talks.command(name='fetch', help='Fetch all talks',
                   usage='Type the command and follow the dialogs',
                   aliases=['list', 'f'])
    @commands.has_permissions(manage_messages=True, manage_channels=True)
    @commands.guild_only()
    async def fetch_all_talk(self, ctx):
        query = 'SELECT talk_id, talks.guild_id AS guild_id, talk_topic, talk_explanation, additional_links,' \
                'talks.created_by AS by, talks.timestamp AS creation_time, ' \
                'themes.theme_id AS theme_id, theme_name, theme_explanation FROM talks ' \
                'INNER JOIN themes ON talks.theme_id = themes.theme_id AND talks.guild_id = themes.guild_id ' \
                'WHERE talks.guild_id = $1'

        guild = ctx.guild
        records = await self.bot.pool.fetch(query, guild.id)
        if len(records) == 0:
            return await ctx.send('No talk topic found...')

        nav = pag.EmbedNavigatorFactory(max_lines=20)
        row_num_to_id = {}
        nav.add_line('**__Talks__**')
        for index, (talk_id, _, talk_topic, talk_exp, _, by, date, _, theme_name, _) in enumerate(records):
            shorten = textwrap.shorten(talk_exp, width=150)
            member = await helpers.get_member_by_id(guild, by)
            member_text = member.mention if member else "Anonymous"
            line = f'**{index + 1}) Talk ID**: {talk_id} | **{date.strftime("%Y-%m-%d")}**\n' \
                   f'**Talk topic**: {talk_topic}\n' \
                   f'**Exp**: {shorten}\n' \
                   f'**Talk author**: {member_text}'
            row_num_to_id[index + 1] = talk_id
            nav.add_line(line)
            nav.add_line('**-----------------------------**')

        nav.start(ctx=ctx)

        question = 'Please type the row number for check details otherwise type c'
        try:
            selected_talk_id, _ = await helpers.get_multichoice_answer(self.bot, ctx, row_num_to_id, question, timeout=60)
        except asyncio.TimeoutError:
            return await ctx.send('Please type in 60 seconds next time.')

        if selected_talk_id is None:
            return await ctx.send('Command has been cancelled.')

        record = next((record for record in records if record['talk_id'] == selected_talk_id), None)
        links = json.loads(record['additional_links'])
        member = await helpers.get_member_by_id(guild, record['by'])
        member_text = member.mention if member else "Anonymous"
        embed_dict = {'title': 'Talk topic',
                      'fields': [{'name': "Talk name", 'value': record['talk_topic'], 'inline': False},
                                 {'name': "Talk description", 'value': record['talk_explanation'], 'inline': False},
                                 {'name': "Additional URL", 'value': links if len(links) > 0 else "No link", 'inline': False},
                                 {'name': "Theme name", 'value': record['theme_name'], 'inline': False},
                                 {'name': "Created by", 'value': member_text, 'inline': True},
                                 {'name': "Created on", 'value': record['creation_time'].strftime('%Y-%m-%d'), 'inline': True},
                                 ]
                      }
        e = CustomEmbed.from_dict(embed_dict, avatar_url=self.bot.user.avatar_url, author_name=ctx.author.name)
        await ctx.send(embed=e.to_embed())

    @talks.command(name='random', help='Get a random talk topic for selected theme',
                   usage='Type the command and follow the dialogs',
                   aliases=['r'])
    @commands.has_any_role(*VALID_STATS_ROLES)
    @commands.guild_only()
    async def get_random(self, ctx):
        question = 'Please select the theme of talk topic, 1 for any theme or "c" for cancelling'

        try:
            theme_id = await self._list_and_get_theme(ctx, ctx.guild, question=question, any_theme=True)
        except ValueError:
            return await ctx.send('No theme found...')
        except asyncio.TimeoutError:
            return await ctx.send('The command has timed out')

        query = 'SELECT talk_id, talks.guild_id AS guild_id, talk_topic, talk_explanation, additional_links,' \
                'talks.created_by AS by, talks.timestamp AS creation_time, ' \
                'themes.theme_id AS theme_id, theme_name, theme_explanation FROM talks ' \
                'INNER JOIN themes ON talks.theme_id = themes.theme_id AND talks.guild_id = themes.guild_id ' \
                'WHERE talks.guild_id = $1' \
                'AND ($2::BIGINT is null or talks.theme_id = $2)' \
                'ORDER BY RANDOM()' \
                'LIMIT 1'

        guild = ctx.guild
        theme_id = None if theme_id == -1 else theme_id
        record = await ctx.db.fetchrow(query, guild.id, theme_id)

        if record is None:
            return await ctx.send('No talk topic found... You can change your theme or select any theme option.')

        links = json.loads(record['additional_links'])
        member = await helpers.get_member_by_id(guild, record['by'])
        member_text = member.mention if member else "Anonymous"
        embed_dict = {'title': 'Random Talk topic',
                      'fields': [{'name': "Talk name", 'value': record['talk_topic'], 'inline': False},
                                 {'name': "Talk description", 'value': record['talk_explanation'], 'inline': False},
                                 {'name': "Additional URL", 'value': links if len(links) > 0 else "No link", 'inline': False},
                                 {'name': "Theme name", 'value': record['theme_name'], 'inline': False},
                                 {'name': "Created by", 'value': member_text, 'inline': True},
                                 {'name': "Created on", 'value': record['creation_time'].strftime('%Y-%m-%d'), 'inline': True},
                                 ]
                      }
        e = CustomEmbed.from_dict(embed_dict, avatar_url=self.bot.user.avatar_url, author_name=ctx.author.name)
        await ctx.send(embed=e.to_embed())

    @talks.command(name='delete', help='Delete a talk topic',
                   usage='Type the command and follow the dialogs',
                   aliases=['remove', 'd'])
    @commands.has_permissions(manage_messages=True, manage_channels=True)
    @commands.guild_only()
    async def delete_talk(self, ctx):
        query = 'SELECT * FROM talks ' \
                'WHERE guild_id = $1'

        guild = ctx.guild
        records = await self.bot.pool.fetch(query, guild.id)
        if len(records) == 0:
            return await ctx.send('No talks found to delete')

        nav = pag.EmbedNavigatorFactory(max_lines=20)
        row_num_to_id = {}
        nav.add_line('**__Talks__**')
        for index, (talk_id, _, theme_id, talk_topic, talk_exp, _, by, date) in enumerate(records):
            shorten = textwrap.shorten(talk_exp, width=150)
            member = await helpers.get_member_by_id(guild, by)
            member_text = member.mention if member else "Anonymous"
            line = f'**{index + 1}) Talk ID**: {talk_id} | **{date.strftime("%Y-%m-%d")}**\n' \
                   f'**Talk topic**: {talk_topic}\n' \
                   f'**Exp**: {shorten}\n' \
                   f'**Talk author**: {member_text}'
            row_num_to_id[index + 1] = talk_id
            nav.add_line(line)
            nav.add_line('**-----------------------------**')

        nav.start(ctx=ctx)

        question = 'Please type the row number for check details otherwise type c'
        try:
            selected_talk_id, _ = await helpers.get_multichoice_answer(self.bot, ctx, row_num_to_id, question, timeout=60)
        except asyncio.TimeoutError:
            return await ctx.send('Please type in 60 seconds next time.')

        if selected_talk_id is None:
            return await ctx.send('Command has been cancelled.')

        query = f"""DELETE FROM talks
                    WHERE guild_id = $1
                    AND talk_id = $2
                 """
        return await self.bot.pool.execute(query, guild.id, selected_talk_id)


def setup(bot):
    bot.add_cog(_Talks(bot))
