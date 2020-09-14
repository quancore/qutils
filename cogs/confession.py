import random
import string
import asyncio
import asyncpg
import hashlib
import json
import textwrap

from PIL import Image
from io import BytesIO

# this just allows for nice function annotation, and stops my IDE from complaining.
# from typing import Union

from discord.ext import commands
from discord.errors import NotFound
import typing
from discord import File, TextChannel, Guild, InvalidArgument, Forbidden, HTTPException, RawMessageDeleteEvent, RawBulkMessageDeleteEvent

import logging
from config import CONFESSION_CHANNEL_ID, GUILD_ID, message_timeout
from utils import db, helpers
from utils.formats import CustomEmbed
from libneko import pag

log = logging.getLogger('root')


class Confessions(db.Table):
    # confession message id
    confession_id = db.Column(db.Integer(big=True), primary_key=True)
    # unique ban code for the confession
    confession_ban_code = db.Column(db.String, nullable=False, unique=True)
    # md5, 16 place hash code created by member id
    user_hash_id = db.Column(db.String, nullable=False)
    guild_id = db.Column(db.Integer(big=True), nullable=False)
    channel_id = db.Column(db.Integer(big=True), nullable=False)
    timestamp = db.Column(db.Datetime, nullable=False)
    confession_text = db.Column(db.String, default='')
    image_url = db.Column(db.String, default='')
    attachment_urls = db.Column(db.JSON, default="'{}'::jsonb")
    user_banned = db.Column(db.Boolean, default=False)


class BannedUsers(db.Table):
    user_hash_id = db.Column(db.String, primary_key=True)
    guild_id = db.Column(db.Integer(big=True), primary_key=True)
    channel_id = db.Column(db.Integer(big=True), nullable=False)
    confession_ban_code = db.Column(db.String, nullable=False)
    timestamp = db.Column(db.Datetime, nullable=False)
    reason = db.Column(db.String, default='')


class ConfessionServers(db.Table):
    guild_id = db.Column(db.Integer(big=True), primary_key=True)
    channel_id = db.Column(db.Integer(big=True), nullable=False)


class Confession(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        # Get default server and channel id
        self.default_guild_id = GUILD_ID
        self.default_channel_id = CONFESSION_CHANNEL_ID
        self.currently_confessing = set()  # A set rather than a fetch_schedule because it uses a hash table

    # ********** Events **************
    async def cog_command_error(self, ctx: commands.Context, error):
        """
        Handles errors for this particular cog
        """
        err_msg = None
        if isinstance(error, commands.NoPrivateMessage):
            err_msg = f"In a reason, you could not run commands in DM. {error}"

        if isinstance(error, commands.BotMissingPermissions):
            err_msg = f"I'm missing the `{error.missing_perms[0]}` permission " \
                      f"that's required for me to run this command."

        elif isinstance(error, commands.MissingPermissions):
            # if ctx.author.id in self.bot.config['owners']:
            #     await ctx.reinvoke()
            #     return
            err_msg = f"You need to have the `{error.missing_perms[0]}` permission to run this command."

        elif isinstance(error, commands.MissingRequiredArgument):
            err_msg = f"You're missing the `{error.param.name}` argument, which is required to run this command."

        elif isinstance(error, commands.BadArgument):
            err_msg = f"You're running this command incorrectly - {error}. Please check the documentation."

        elif isinstance(error, commands.UserInputError):
            err_msg = f"User give wrong input:  {error}."

        if err_msg is not None:
            log.exception(err_msg)
            return await ctx.send(err_msg)

        raise error

    @commands.Cog.listener()
    async def on_ready(self):
        """ Schedule initial works for confession cog """
        asyncio.ensure_future(self.insert_and_update_servers(self.default_guild_id,
                                                             self.default_channel_id),
                              loop=self.bot.loop)
        asyncio.ensure_future(self.remove_unreachable_servers(),
                              loop=self.bot.loop)

    @commands.Cog.listener('on_guild_channel_delete')
    async def channel_delete_listener(self, channel: TextChannel):
        """ Checks to see if a tracked confession channel is being deleted """

        # Check for text channel
        if not isinstance(channel, TextChannel):
            return

        # Check for existing
        guild = channel.guild
        channel_id = self.confession_servers_map.get(guild.id, None)
        if channel_id is None:
            return

        # It exists

        query = 'DELETE FROM confessionservers WHERE channel_id=$1'
        res = await self.bot.pool.execute(query, channel_id)
        num_deleted = helpers.representsInt(res.split(' ')[-1])
        if num_deleted > 0:
            log.info(f"Deleting {num_deleted} inaccessible confession channel with **ID: {channel.id} "
                     f"({channel.name})** in **{guild.name}**.")
        del self.confession_servers_map[guild.id]

    @commands.Cog.listener('on_raw_message_delete')
    async def confession_delete_listener(self, payload: RawMessageDeleteEvent):
        """ Delete a confession log if a confession has been deleted. """
        query = f"""DELETE FROM confessions
                    WHERE confession_id = $1
                    AND guild_id = $2
                    AND channel_id = $3
                        """

        res = await self.bot.pool.execute(query, payload.message_id, payload.guild_id, payload.channel_id)
        num_deleted = helpers.representsInt(res.split(' ')[-1])
        if num_deleted > 0:
            log.info(f'{num_deleted} confession record have been deleted because of confession deletion.')

    @commands.Cog.listener('on_raw_bulk_message_delete')
    async def confession_bulk_delete_listener(self, payload: RawBulkMessageDeleteEvent):
        """ Delete bulk confessions log if confessions have been deleted. """
        query = f"""DELETE FROM confessions
                    WHERE confession_id = $1
                    AND guild_id = $2
                    AND channel_id = $3
                 """
        query_params = [(message_id, payload.guild_id, payload.channel_id) for message_id in payload.message_ids]
        await self.bot.pool.executemany(query, query_params)
    # *********************************

    # ********* Server and channel settings related ******
    async def insert_and_update_servers(self, guild_id, channel_id):
        """ Insert a confession channel with given server id
            and update server-confession channel map in the instance """
        # insert default confession server to DB
        await self.insert_confession_server(guild_id, channel_id)
        # fetch all confession server ids with corresponding channel ids from DB and update
        await self.update_confession_server_ids()

    async def remove_unreachable_servers(self):
        """ Remove unreachable (deleted or permission changed)
            channels with servers in DB """
        query = 'SELECT * FROM confessionservers'
        delete_query = 'DELETE FROM confessionservers WHERE channel_id=$1'

        # Fetch all confession servers with corresponding channels
        server_channel_ids = await self.bot.pool.fetch(query)

        # Go through and delete channels we don't care about any more
        for guild_id, channel_id in server_channel_ids:
            try:
                channel = self.bot.get_channel(channel_id) or await self.bot.fetch_channel(channel_id)
            except NotFound:
                channel = None

            if channel is None:
                log.info(f"Deleting inaccessible channel with ID {channel_id} in guild with ID: {guild_id}")
                await self.bot.pool.execute(delete_query, channel_id)
                del self.confession_servers_map[guild_id]

    async def update_confession_server_ids(self):
        """ Update confession server map"""
        self.confession_servers_map = await self.get_confession_server_ids()

    async def get_confession_server_ids(self):
        """ Get all confession servers ids with confession channel ids in dict format"""
        query = """ SELECT * FROM confessionservers """
        rows = await self.bot.pool.fetch(query)

        return {row['guild_id']: row['channel_id'] for row in rows}

    async def insert_confession_server(self, guild_id, channel_id):
        """ Insert or update a channel id with a confession server"""
        query = """ INSERT INTO confessionservers (guild_id, channel_id) 
                    VALUES($1, $2)
                    ON CONFLICT (guild_id) DO UPDATE 
                    SET channel_id=$2"""
        await self.bot.pool.execute(query, guild_id, channel_id)
# ***********************************************
# ******* Utils method for class ****************

    @staticmethod
    def get_code(n: int = 5) -> str:
        """ Get a random alphanumerical code with given n place"""
        return ''.join(random.choices(string.ascii_lowercase + string.digits, k=n))

    @staticmethod
    def get_hash_code(raw: str, n: int = 16):
        """ Get hash digest with given n place"""
        return hashlib.md5(raw.encode("utf-8")).hexdigest()[:n]

    @staticmethod
    async def get_unique_ban_code(ctx, n: int = 5, attempt: int = 10) -> str:
        """ Get unique ban code for a confession by checking DB """
        query = f"""SELECT *
                    FROM confessions
                    WHERE confession_ban_code = $1
                """

        # Check n attempts to get a unique code not in DB
        for _ in range(attempt):
            ban_code = Confession.get_code(n)
            row = await ctx.db.fetchrow(query, ban_code)
            if row is None:
                return ban_code

        raise ValueError(f'Failed to create a unique ban code after {attempt} attempts.')

    @staticmethod
    async def handle_attachments(attachments) -> (typing.Union[File, None], list):
        def get_concat_v_blank(im1, im2, color=(0, 0, 0)):
            dst = Image.new('RGB', (max(im1.width, im2.width), im1.height + im2.height), color)
            dst.paste(im1, (0, 0))
            dst.paste(im2, (0, im1.height))
            return dst

        def get_concat_v_multi_blank(im_list):
            _im = im_list.pop(0)
            for im in im_list:
                _im = get_concat_v_blank(_im, im)
            return _im

        # categorize attachments
        image_formats = ['bmp', 'jpeg', 'jpg', 'png', 'gif']
        check_image = lambda _attachment: True if _attachment.filename.split('.')[-1] in image_formats else False
        image_attachments, other_attachments = [], []
        for attachment in attachments:
            image_attachments.append(attachment) if check_image(attachment) else other_attachments.append(attachment)

        # if one or no image, no need to process
        if len(image_attachments) <= 1:
            return await image_attachments[0].to_file() if len(image_attachments) == 1 else None, other_attachments

        # for multiple images, first get the bytes of images and store them
        images = []
        for attachment in image_attachments:
            attachment_bytes = await attachment.read()
            images.append(Image.open(BytesIO(attachment_bytes)))

        # concat vertically image attachments
        concat_image_bytes = get_concat_v_multi_blank(images)
        # prepare the stream to save this image into
        final_buffer = BytesIO()

        # save into the stream, using png format.
        concat_image_bytes.save(final_buffer, "png")

        # seek back to the start of the stream
        final_buffer.seek(0)

        return File(filename="concatenated.png", fp=final_buffer), other_attachments

    async def _create_embed(self, record, is_detailed=True):
        """ Create original embed from a database record.
            If detailed True, a detailed embed has been created, which is useful for feedback to user etc."""
        attachments = json.loads(record['attachment_urls'])
        embed_dict = {'title': 'Anonymous confession',
                      'description': record['confession_text'],
                      'footer': {'text': f"Ban code for user: {record['confession_ban_code']}"},
                      }
        if is_detailed:
            guild, channel = await helpers.get_guild_by_id(self.bot, record['guild_id']), None
            if guild:
                channel = await helpers.get_channel_by_id(self.bot, guild, record['channel_id'])

            embed_dict['fields'] = [{'name': "User hash code", 'value': record['user_hash_id'], 'inline': True},
                                    {'name': 'Guild ID', 'value': guild.name if guild else record['guild_id'], 'inline': True},
                                    {'name': 'Channel ID', 'value': channel.mention if channel else record['channel_id'], 'inline': True},
                                    {'name': 'Date of confession', 'value': record['timestamp'].strftime('%Y-%m-%d'),
                                     'inline': True},
                                    {'name': 'User banned?', 'value': 'Yes' if record['user_banned'] else 'No',
                                     'inline': True}
                                    ]
        e = CustomEmbed.from_dict(embed_dict, avatar_url=self.bot.user.avatar_url)
        if record['image_url'] != '':
            e.set_image(url=record['image_url'])

        if attachments:
            attachment_str = '\n'.join(attachments)
            e.add_field(name='**Other attachments**', value=attachment_str, inline=False)

        return e

    def _find_member_by_hash_code(self, guild, user_hash_code):
        """ Find member with given hash code if exist else return None """
        for member in guild.members:
            user_hexdigest = Confession.get_hash_code(str(member.id), n=16)
            if user_hexdigest == user_hash_code:
                return member

        return None

    def _check_ban_code(self, ban_code):
        """ Return True if given ban code in a valid format """
        return len(ban_code) == 16 and ban_code.isalnum()

    async def _fetch_with_ban_code(self, ctx, guild_id, ban_code):
        """ Fetch confessions with ban code. """
        query = f"""SELECT *
                    FROM confessions
                    WHERE confession_ban_code = $1
                    AND guild_id = $2
                """

        # Make sure it's valid ban code
        if not self._check_ban_code(ban_code):
            raise commands.UserInputError(f"Given ban code is not valid: **{ban_code}**")

        rows = await ctx.db.fetch(query, ban_code, guild_id)

        # Check there is a confession with ban code
        if len(rows) == 0:
            raise commands.UserInputError(f"There is no confession with given **ban code: {ban_code}** in this server.")

        # Check number of confession related to given ban code
        if len(rows) > 1:
            raise commands.UserInputError(f'Multiple rows found with the same **ban code: {ban_code}**.\n'
                                          f'**__Records__**:\n **{rows}** \n '
                                          f'It should not be happening.')

        return rows[0]

    async def _delete_with_ban_code(self, ctx, guild_id, ban_code):
        """ Delete a confession with ban code."""
        query = f"""DELETE FROM confessions
                    WHERE confession_ban_code = $1
                    AND guild_id = $2
                """

        # Make sure it's valid ban code
        if not self._check_ban_code(ban_code):
            raise commands.UserInputError(f"Given ban code is not valid: **{ban_code}**")

        await ctx.db.execute(query, ban_code, guild_id)

    async def _fetch_with_user_code(self, ctx, guild_id, user_hash_code):
        """ Fetch confession with ban code """
        query = f"""SELECT *
                    FROM bannedusers
                    WHERE user_hash_id = $1 AND
                    guild_id = $2
                """
        row = await ctx.db.fetchrow(query, user_hash_code, guild_id)

        return row

    async def _set_ban_status(self, ctx, guild_id: int, ban_code: str, ban_status: bool = False):
        """ Set a user ban status for a confession."""
        update_query = """ UPDATE confessions
                       SET user_banned = $1
                       WHERE confession_ban_code = $2
                       AND guild_id = $3
                       """
        await ctx.db.execute(update_query, ban_status, ban_code, guild_id)

    async def _set_channel_id(self, ctx, guild_id: int, ban_code: str, new_channel_id: int):
        """ Set a new text channel if for a confession."""
        update_query = """ UPDATE confessions
                       SET channel_id = $1
                       WHERE confession_ban_code = $2
                       AND guild_id = $3
                       """
        await ctx.db.execute(update_query, new_channel_id, ban_code, guild_id)
# ******************************************

# ********** commands **********************
    @commands.group(name='confess', help='Command group for confession',
                    usage='This is not a command but a command group.', hidden=True,
                    aliases=['cf'])
    async def confess(self, ctx):
        pass

    @confess.command(name='create', help='Create a confession',
                     usage='Type the command and follow the dialogs',
                     aliases=['make', 'c'])
    @commands.dm_only()
    async def create(self, ctx):
        """ Create a confession for given server """
        author = ctx.author
        channel = ctx.message.channel
        # Handle bots (me lol)
        if author.bot:
            return

        # Handle them giving a code
        if author.id in self.currently_confessing:
            return await ctx.send("You are currently confessing already")

        # Okay it should be alright - add em to the cache
        self.currently_confessing.add(author.id)

        guilds = [await helpers.get_guild_by_id(self.bot, guild_id) for guild_id in self.confession_servers_map.keys()]
        if len(guilds) == 0:
            return await ctx.send('There is no server currently set for confession.\n'
                                  '__To set up a confession server__\n'
                                  '1) Invite the bot on your server and give required permissions \n'
                                  '2) Setup confession channel by using **confess set_channel** command')

        guild_dict = {index + 1: guild for index, guild in enumerate(guilds)}
        guild_text = '\n'.join([f'**{index}) {guild.name}**' for index, guild in guild_dict.items()])
        question = f"Which server you want to create a confessions? " \
                   f"Please choose the number or press **c** cancel it\n" \
                   f"If one of the server you have confessed is not in the list, please contact with" \
                   f"server moderation.\n" \
                   f"**__Servers__**\n" \
                   f"{guild_text}"

        try:
            guild = await helpers.get_multichoice_answer(self.bot, ctx, channel, guild_dict, question)
        except asyncio.TimeoutError:
            self.currently_confessing.discard(author.id)
            return await channel.send("The timer for you to provide the choice is timeout. Please "
                                      "give your confession again to be able to provide another.")
        except commands.UserInputError as err:
            self.currently_confessing.discard(author.id)
            raise err

        if guild is None:
            self.currently_confessing.discard(author.id)
            return await ctx.send('Command has been cancelled.')

        # Check guild has the confession channel given in settings
        channel_id = self.confession_servers_map[guild.id]
        confession_channel = await helpers.get_channel_by_id(self.bot, guild, channel_id)
        if confession_channel is None:
            self.currently_confessing.discard(author.id)
            return await channel.send(f"The confession channel saved before with **ID: {channel_id} is not exist or"
                                      "reachable currently.")

        # Check the user is in the guild for the channel
        member = await helpers.get_member_by_id(guild, author.id)
        if member is None:
            self.currently_confessing.discard(author.id)
            return await channel.send(f"You are not a member of server: **{guild.name}**"
                                      f" that trying to send a confession.")

        # Check the user can see the confession channel
        if confession_channel.permissions_for(member).read_messages is False:
            self.currently_confessing.discard(author.id)
            return await channel.send(f"You are not allowed to read confession channel: {confession_channel.name}.")

        # Check they're allowed to send messages to that guild (banned or not)
        user_hexdigest = Confession.get_hash_code(str(member.id), n=16)
        res = await self._fetch_with_user_code(ctx, guild.id, user_hexdigest)
        if res:
            self.currently_confessing.discard(author.id)
            return await channel.send(f"You've been banned from **{guild.name}** to send confession.\n"
                                      f"**Ban code**: {res['confession_ban_code']}.\n"
                                      f"**Ban date**: {res['timestamp'].strftime('%Y-%m-%d')} \n"
                                      f"**Reason**: {res['reason']}")

        # Get confession message
        def check_message(m):
            if m.author.id != author.id:
                return False
            if m.channel != ctx.channel:
                return False
            if m.mention_everyone:
                raise commands.UserInputError('You have been mentioning here or everyone, which is not allowed.')

            member_mentions = m.mentions
            if member_mentions:
                check_res = all([True if guild.get_member(member_.id) is not None else False
                                 for member_ in member_mentions])
                if not check_res:
                    raise commands.UserInputError('You have been mentioning a user not a member of given guild')

            return True

        await channel.send(f"What is your confession message? "
                           f"Please write only one message and sent it.\n"
                           f"If you want to add attachemnt, you can type your confession on"
                           f"attachment description.\n"
                           f"You have **{message_timeout} seconds** to complete.")
        try:
            confession_message = await self.bot.wait_for("message",
                                                         check=check_message,
                                                         timeout=message_timeout)
        except asyncio.TimeoutError:
            self.currently_confessing.discard(author.id)
            return await channel.send("The timer for you to give a server id has timed out. Please "
                                      "give your confession again to be able to provide another.")
        except commands.UserInputError as err:
            self.currently_confessing.discard(author.id)
            raise err

        # Now we can send the confession in embed format
        has_attachments = len(confession_message.attachments) > 0
        # has_embeds = len(confession_message.embeds) > 0
        user_ban_code = await Confession.get_unique_ban_code(ctx, 16)
        # Create a record for confession embed
        record = {'confession_text': confession_message.content, 'confession_ban_code': user_ban_code}

        # log.info(confession_message.attachments)
        # log.info(confession_message.embeds)

        # # handle embeds
        # if has_embeds:
        #     new_field = {'name': '**Other embeds**\n',
        #                  'value': '\n'.join([embed.url for embed in confession_message.embeds]),
        #                  'inline': False}
        #     e.add_field(**new_field)

        # handle attachments and image
        image, other_attachment_urls = None, []
        record['image_url'] = ''
        if has_attachments:
            image, other_attachments = await self.handle_attachments(confession_message.attachments)
            if image is not None:
                record['image_url'] = f"attachment://{image.filename}"

            if other_attachments:
                other_attachment_urls = [att.url for att in other_attachments]
        record['attachment_urls'] = json.dumps(other_attachment_urls)

        # Create embed message and send it
        _embed = await self._create_embed(record, is_detailed=False)
        try:
            confessed_message = await confession_channel.send(file=image, embed=_embed.to_embed())
        except Exception as e:
            self.currently_confessing.discard(author.id)
            return await channel.send(f"I encountered the error `{e}` trying to send in the confession :/")
        else:
            self.currently_confessing.discard(author.id)
            await channel.send(f"I successfully sent in your confession!\n URL: {confessed_message.jump_url}")

        query = 'INSERT INTO confessions ' \
                'VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9::jsonb)'
        query_params = (confessed_message.id, user_ban_code, user_hexdigest,
                        guild.id, confession_channel.id, confessed_message.created_at,
                        confession_message.content,
                        confessed_message.embeds[0].image.url if image is not None else '',
                        record['attachment_urls']
                        )
        await ctx.db.execute(query, *query_params)

    @confess.command(name='set_channel', help='Set a confession channel in the server',
                     usage='<channel_mention>\n [Ex: #confession]', aliases=['set', 's'])
    @commands.has_permissions(manage_messages=True, manage_channels=True)
    @commands.guild_only()
    async def set_channel(self, ctx, channel: TextChannel):
        guild = ctx.guild
        # insert given channel id with server id to DB and update the instance server dict
        await self.insert_and_update_servers(guild.id, channel.id)
        await ctx.send(f'Confession channel set to {channel.mention} for server **{guild.name}**')

    @confess.command(name='get_channel', help='Get confession channel if it has been set.',
                     usage='', aliases=['get', 'g'])
    @commands.guild_only()
    async def get_channel(self, ctx):
        guild = ctx.guild
        channel_id = self.confession_servers_map.get(guild.id, None)
        if channel_id:
            channel = await helpers.get_channel_by_id(self.bot, guild, channel_id)
            if channel:
                await ctx.send(f'Confession channel for **{guild.name}** is **{channel.mention}**')
            else:
                await ctx.send(f'Confession channel for **{guild.name}** has been set with channel ID {channel_id}'
                               f'however the channel is no longer reachable, maybe deleted or maybe restricted.\n'
                               f'Please use **set_channel** command to set a valid text channel.')

        else:
            await ctx.send(f'Confession channel has not been set for **{guild.name}**.\n'
                           f'Please use **set_channel** command to set a confession channel'
                           f'if you have required privileges.')

    @confess.command(name='fetchall', help='Fetch all the confession logs from DB for this guild',
                     usage='', aliases=['fa'])
    @commands.has_permissions(manage_messages=True, ban_members=True)
    @commands.guild_only()
    async def fetchall(self, ctx):
        query = """SELECT confession_id,
                    confession_ban_code,
                    user_hash_id,
                    guild_id,
                    channel_id,
                    timestamp,
                    confession_text,
                    image_url,
                    attachment_urls,
                    user_banned
                    FROM confessions
                    WHERE guild_id = $1"""

        guild = ctx.guild
        records = await ctx.db.fetch(query, guild.id)
        if len(records) == 0:
            return await ctx.send('No results found...')

        nav = pag.EmbedNavigatorFactory(max_lines=20)
        nav.add_line('**__Confession logs__**')
        row_num_to_id = {}
        for index, (_id, ban_code, _, _, _, date, text, _, _, ban_status) in enumerate(records):
            shorten = textwrap.shorten(text, width=150)
            line = f'**{index+1}) ID**: {_id} | **BCode**: {ban_code} | ' \
                   f'**{date}** -> {shorten}'
            row_num_to_id[index+1] = _id
            nav.add_line(line)
            nav.add_line('**-----------------------------**')

        nav.start(ctx=ctx)

        question = 'Please type the row number for check details otherwise type c'
        try:
            choice = await helpers.get_multichoice_answer(self.bot, ctx, ctx.channel, row_num_to_id, question, timeout=60)
        except asyncio.TimeoutError as e:
            return await ctx.send('Please type in 60 seconds next time.')

        if choice is None:
            return await ctx.send('Command has been cancelled.')

        record = next((record for record in records if record['confession_id'] == choice), None)
        e = await self._create_embed(record, is_detailed=False)
        await ctx.send(embed=e.to_embed())

    @confess.command(name='fetch', help='Fetch the confessions belongs to a member from DB',
                     usage='', aliases=['f'])
    @commands.dm_only()
    async def fetch(self, ctx):
        query = """SELECT confession_id,
                    confession_ban_code,
                    user_hash_id,
                    guild_id,
                    channel_id,
                    timestamp,
                    confession_text,
                    image_url,
                    attachment_urls,
                    user_banned
                    FROM confessions
                    WHERE user_hash_id=$1"""

        author = ctx.author
        channel = ctx.channel
        user_hexdigest = Confession.get_hash_code(str(author.id), n=16)

        records = await ctx.db.fetch(query, user_hexdigest)
        if len(records) == 0:
            return await ctx.send('No confession has been found...')

        # Get guilds for that user
        guild_ids = list({record['guild_id'] for record in records})
        guilds = [await helpers.get_guild_by_id(self.bot, guild_id) for guild_id in guild_ids]
        if len(guilds) == 0:
            return await ctx.send('There is no server can be reachable at that moment.')

        guild_dict = {index + 1: guild for index, guild in enumerate(guilds)}
        guild_text = '\n'.join([f'**{index}) {guild.name}**' for index, guild in guild_dict.items()])
        question = f"Which server you want to get confessions? " \
                   f"Please choose the number or press **c** cancel it\n" \
                   f"If one of the server you have confessed is not in the fetch_schedule, please contact with" \
                   f"server moderation.\n" \
                   f"**__Servers__**\n" \
                   f"{guild_text}"

        try:
            guild = await helpers.get_multichoice_answer(self.bot, ctx, channel, guild_dict, question)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to provide the choice is timeout. Please "
                                      "choose your confession server again to be able to provide another.")
        except commands.UserInputError as err:
            raise err

        if guild is None:
            return await ctx.send('Command has been cancelled.')

        # Filter retrieved confessions using guild id
        records = [record for record in records if record['guild_id'] == guild.id]

        nav = pag.EmbedNavigatorFactory(max_lines=20)
        nav.add_line('**__Confessions__**')
        row_num_to_id = {}
        for index, (_id, ban_code, _, _, _, date, text, _, _, ban_status) in enumerate(records):
            shorten = textwrap.shorten(text, width=150)
            line = f'**{index+1}) ID**: {_id} | **BCode**: {ban_code} | ' \
                   f'**{date}** -> {shorten}'
            row_num_to_id[index+1] = _id
            nav.add_line(line)
            nav.add_line('**-----------------------------**')

        nav.start(ctx=ctx)

        question = 'Please type the row number for check details otherwise type c'
        try:
            choice = await helpers.get_multichoice_answer(self.bot, ctx, channel, row_num_to_id, question, timeout=60)
        except asyncio.TimeoutError as e:
            return await ctx.send('Please type in 60 seconds next time.')

        if choice is None:
            return await ctx.send('Command has been cancelled.')

        record = next((record for record in records if record['confession_id'] == choice), None)
        e = await self._create_embed(record, is_detailed=False)
        await ctx.send(embed=e.to_embed())

    @confess.command(name='delete', help='Delete a confession',
                     usage='', aliases=['remove', 'd'])
    @commands.dm_only()
    async def delete(self, ctx):
        query = """SELECT confession_id,
                    confession_ban_code,
                    user_hash_id,
                    guild_id,
                    channel_id,
                    timestamp,
                    confession_text,
                    image_url,
                    attachment_urls,
                    user_banned
                    FROM confessions
                    WHERE user_hash_id=$1"""

        author = ctx.author
        channel = ctx.channel
        user_hexdigest = Confession.get_hash_code(str(author.id), n=16)

        records = await ctx.db.fetch(query, user_hexdigest)
        if len(records) == 0:
            return await ctx.send('No confession has been found...')

        # Get guilds for that user
        guild_ids = list({record['guild_id'] for record in records})
        guilds = [await helpers.get_guild_by_id(self.bot, guild_id) for guild_id in guild_ids]
        if len(guilds) == 0:
            return await ctx.send('There is no server can be reachable at that moment.')

        guild_dict = {index + 1: guild for index, guild in enumerate(guilds)}
        guild_text = '\n'.join([f'**{index}) {guild.name}**' for index, guild in guild_dict.items()])
        question = f"Which server you want to delete confession? " \
                   f"Please choose the number or press **c** cancel it\n" \
                   f"If one of the server you have confessed is not here, please contact with" \
                   f"server moderation.\n" \
                   f"**__Servers__**\n" \
                   f"{guild_text}"

        try:
            guild = await helpers.get_multichoice_answer(self.bot, ctx, channel, guild_dict, question)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to provide the choice is timeout. Please "
                                      "choose your confession server again to be able to provide another.")
        except commands.UserInputError as err:
            raise err

        if guild is None:
            return await ctx.send('Command has been cancelled.')

        # Check user banned from that guild
        res = await self._fetch_with_user_code(ctx, guild.id, user_hexdigest)
        if res:
            return await channel.send(f"You've been banned from **{guild.name}** to delete a confession.\n"
                                      f"**Confession ban code you get banned**: {res['confession_ban_code']}.\n"
                                      f"**Ban date**: {res['timestamp'].strftime('%Y-%m-%d')} \n"
                                      f"**Reason**: {res['reason']}")

        # Filter retrieved confessions using guild id
        records = [record for record in records if record['guild_id'] == guild.id]

        nav = pag.EmbedNavigatorFactory(max_lines=20)
        nav.add_line('**__Confessions__**')
        row_num_to_id = {}
        for index, (_id, ban_code, _, _, _, date, text, _, _, ban_status) in enumerate(records):
            shorten = textwrap.shorten(text, width=150)
            line = f'**{index + 1}) ID**: {_id} | **BCode**: {ban_code} | ' \
                   f'**{date}** -> {shorten}'
            row_num_to_id[index + 1] = _id
            nav.add_line(line)
            nav.add_line('**-----------------------------**')

        nav.start(ctx=ctx)

        question = 'Please type the row number for delete confession otherwise type c\n' \
                   'THE CONFESSION WILL BE DELETED IRREVOCABLY!!!'
        try:
            choice = await helpers.get_multichoice_answer(self.bot, ctx, channel, row_num_to_id, question, timeout=60)
        except asyncio.TimeoutError as e:
            return await ctx.send('Please type in 60 seconds next time.')

        if choice is None:
            return await ctx.send('Command has been cancelled.')

        record = next((record for record in records if record['confession_id'] == choice), None)
        # Remove the confession from DB
        await self._delete_with_ban_code(ctx, guild.id, record['confession_ban_code'])
        # Remove the message from channel
        channel = await helpers.get_channel_by_id(self.bot, guild, record['channel_id'])
        if channel:
            try:
                msg = await channel.fetch_message(record['confession_id'])
            except NotFound as err:
                log.exception(f"Message not found with id: "
                              f"{record['confession_id']} to delete.")
            else:
                if msg:
                    await msg.delete()

        e = await self._create_embed(record, is_detailed=False)
        await ctx.send('The following confession has been deleted.', embed=e.to_embed())

    @confess.command(name='ban', help='Ban a member to send confession',
                     usage='<ban_code> <reason> \n Use " " to define reason longer than one word',
                     aliases=['b'])
    @commands.has_permissions(manage_messages=True, ban_members=True)
    @commands.guild_only()
    async def ban(self, ctx, ban_code, reason):
        """Bans a user from being able to send in any more confessions to your server"""
        guild = ctx.guild

        # Fetch record with given ban code
        record = await self._fetch_with_ban_code(ctx, guild.id, ban_code)

        # Check if the user of the confession has already banned
        if not record['user_banned']:
            # set ban status of a confession in DB
            await self._set_ban_status(ctx, guild.id, ban_code, ban_status=True)
            record = dict(record)
            record['user_banned'] = True

            # Add user to banned user for this guild
            query = 'INSERT INTO bannedusers VALUES ($1, $2, $3, $4, $5, $6)'
            params = (record['user_hash_id'], guild.id, record['channel_id'],
                      record['confession_ban_code'],
                      record['timestamp'], reason)
            try:
                await ctx.db.execute(query, *params)
            except asyncpg.UniqueViolationError as err:
                log.exception(err)

            # Remove the message and update db record as banned
            channel = await helpers.get_channel_by_id(self.bot, guild, record['channel_id'])
            if channel:
                try:
                    msg = await channel.fetch_message(record['confession_id'])
                except NotFound as err:
                    log.exception(f"Message not found with **ID: "
                                  f"{record['confession_id']}** to delete "
                                  f"after **ban code: {ban_code}**. {err}")
                else:
                    if msg:
                        await msg.delete()

            # Find member with given user hash code if it is still in the guild
            ban_member = self._find_member_by_hash_code(guild, record['user_hash_id'])
            if ban_member:
                # Tell people about it
                e = await self._create_embed(record)
                try:
                    await ban_member.send(f"You've been banned from posting confessions on "
                                          f"the server **{guild.name}**. \n"
                                          f"**Reason**: {reason} \n"
                                          f"**Banned by**: {ctx.author.mention} \n"
                                          f"Your identity is still a secret. Don't worry about it too much.\n"
                                          f"Here is the confession caused to ban:",
                                          embed=e)
                except Exception:
                    pass

                return await ctx.send("That user has been banned from sending in more confessions on your server.")
            else:
                return await ctx.send("Given user has not been found to ban.")
        else:
            return await ctx.send("Given user has already been banned. "
                                  "If you have permissions, you can check banned users via **fetchban** command.")

    @confess.command(name='unban', help='Unban a user to send confession',
                     usage='<user_hash_code>', aliases=['ub'])
    @commands.has_permissions(manage_messages=True, ban_members=True)
    @commands.guild_only()
    async def unbanuser(self, ctx, user_hash_code):
        """ Unbans a user from messaging the confessional on your server """
        query = 'DELETE FROM bannedusers WHERE guild_id=$1 AND user_hash_id=$2'

        # First check whether user is indeed banned
        guild = ctx.guild
        res = await self._fetch_with_user_code(ctx, guild.id, user_hash_code)
        if res is None:
            return await ctx.send("That user has not been banned from sending confession in this server"
                                  " or you have given wrong user hash code.")

        await ctx.db.execute(query, guild.id, user_hash_code)
        await ctx.send(f"Member with **hash code: {user_hash_code}** has been unbanned for **{guild.name}**.")

        # unban in db
        await self._set_ban_status(ctx, guild.id, res['confession_ban_code'])

        # send a pm message to unbanned user
        member = self._find_member_by_hash_code(guild, user_hash_code)
        if member:
            await member.send(f'Congratulations, you have been unbanned in **{guild.name}**'
                              f' by {ctx.author.mention}')

        # send the deleted confession to newly set channel instead of the channel in DB
        confession_channel_id = self.confession_servers_map.get(guild.id, None)
        if confession_channel_id:
            confession_channel = await helpers.get_channel_by_id(self.bot, guild, confession_channel_id)
            if confession_channel:
                # Fetch record with given ban code
                confession = await self._fetch_with_ban_code(ctx, guild.id, res['confession_ban_code'])
                # Resend the deleted confession to current confession channel
                e = await self._create_embed(confession, is_detailed=False)
                try:
                    confessed_message = await confession_channel.send(embed=e.to_embed())
                except Exception as e:
                    await confession_channel.send(f"I encountered the error `{e}` "
                                                  f"trying to send your deleted confession to confession channel:/")
                else:
                    # if we resend the confession, we should update the confession channel
                    # since current confession channel and DB record may differ
                    await self._set_channel_id(ctx, guild.id, res['confession_ban_code'], confession_channel_id)

    @confess.command(name='fetchban', help='Fetch banned users from confession',
                     usage='', aliases=['fb'])
    @commands.has_permissions(manage_messages=True, ban_members=True)
    @commands.guild_only()
    async def fetch_ban(self, ctx):
        query = """SELECT user_hash_id,
                    guild_id,
                    confession_ban_code,
                    timestamp,
                    reason
                    FROM bannedusers
                    WHERE guild_id = $1"""

        guild = ctx.guild
        records = await ctx.db.fetch(query, guild.id)
        if len(records) == 0:
            return await ctx.send('No results found...')

        nav = pag.EmbedNavigatorFactory(max_lines=20)
        nav.add_line('**__Banned Users__**')
        row_num_to_code = {}
        for index, (_id, guild_id, confession_ban_code, date, reason) in records:
            line = f'**{index+1}) User Hash code**: {_id} | **Guild ID:** {guild_id}' \
                   f' **BCode**: {confession_ban_code} | **{date}** -> {reason}'
            row_num_to_code[index+1] = confession_ban_code
            nav.add_line(line)
            nav.add_line('**-----------------------------**')

        nav.start(ctx=ctx)

        question = 'Please type the row number for check details otherwise type c'
        try:
            choice = await helpers.get_multichoice_answer(self.bot, ctx, ctx.channel, row_num_to_code, question, timeout=60)
        except asyncio.TimeoutError as e:
            return await ctx.send('Please type in 60 seconds next time.')

        if choice is None:
            return await ctx.send('Command has been cancelled.')

        ban_record = next((record for record in records if record['confession_ban_code'] == choice), None)
        record = await self._fetch_with_ban_code(ctx, guild.id, ban_record['confession_ban_code'])
        e = await self._create_embed(record)
        await ctx.send(embed=e.to_embed())


def setup(bot):
    bot.add_cog(Confession(bot))
