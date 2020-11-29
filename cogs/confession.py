import random
import string
import asyncio
import asyncpg
import hashlib
import json
import textwrap
import datetime
import functools

from PIL import Image
from io import BytesIO

# this just allows for nice function annotation, and stops my IDE from complaining.
# from typing import Union

from discord.ext import commands
from discord.errors import NotFound
import typing
from discord import File, TextChannel, utils, InvalidArgument, Forbidden, HTTPException, RawMessageDeleteEvent, RawBulkMessageDeleteEvent

import logging
from config import ADMIN_CHANNEL_ID, CONFESSION_CHANNEL_ID, GUILD_ID, valid_confession_roles,\
    message_timeout, warn_limit, command_cooldown, short_delay, mid_delay, long_delay, TIER5
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
    # whether the confession has been deleted
    is_deleted = db.Column(db.Boolean, default=False)


class BannedUsers(db.Table):
    user_hash_id = db.Column(db.String, primary_key=True)
    guild_id = db.Column(db.Integer(big=True), primary_key=True)
    channel_id = db.Column(db.Integer(big=True), nullable=False)
    confession_ban_code = db.Column(db.String, nullable=False)
    timestamp = db.Column(db.Datetime, nullable=False)
    reason = db.Column(db.String, default='')


class Warns(db.Table):
    confession_ban_code = db.Column(db.String, primary_key=True)
    confession_id = db.Column(db.Integer(big=True), unique=True)
    user_hash_id = db.Column(db.String, nullable=False)
    guild_id = db.Column(db.Integer(big=True), nullable=False)
    channel_id = db.Column(db.Integer(big=True), nullable=False)
    timestamp = db.Column(db.Datetime, nullable=False)
    reason = db.Column(db.String, default='')


class ConfessionServers(db.Table):
    guild_id = db.Column(db.Integer(big=True), primary_key=True)
    channel_id = db.Column(db.Integer(big=True), nullable=False)


class Irritations(db.Table):
    confession_id = db.Column(db.Integer(big=True), primary_key=True)
    # unique ban code for the confession
    confession_ban_code = db.Column(db.String, nullable=False, unique=True)
    # the member hash code irritated by this confession
    user_hash_id = db.Column(db.String, nullable=False)
    guild_id = db.Column(db.Integer(big=True), nullable=False)
    channel_id = db.Column(db.Integer(big=True), nullable=False)
    timestamp = db.Column(db.Datetime, nullable=False)
    reason = db.Column(db.String, default='')


class Confession(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        # Get default server and channel id
        self.default_guild_id = GUILD_ID
        self.default_channel_id = CONFESSION_CHANNEL_ID
        self.currently_confessing = set()  # A set rather than a fetch_schedule because it uses a hash table

    # ********** Events **************
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
        # query = f"""DELETE FROM confessions
        #             WHERE confession_id = $1
        #             AND guild_id = $2
        #             AND channel_id = $3
        #                 """
        #
        # res = await self.bot.pool.execute(query, payload.message_id, payload.guild_id, payload.channel_id)
        # num_deleted = helpers.representsInt(res.split(' ')[-1])
        # if num_deleted > 0:
        #     log.info(f'{num_deleted} confession record have been deleted because of confession deletion.')

        # No remove from DB but set the deleted flag
        res = await self._set_deletion_status(payload.guild_id, payload.message_id, deletion_status=True)
        if res > 0:
            log.info(f'{res} confession record have been set as deleted.')

    @commands.Cog.listener('on_raw_bulk_message_delete')
    async def confession_bulk_delete_listener(self, payload: RawBulkMessageDeleteEvent):
        """ Delete bulk confessions log if confessions have been deleted. """
        # query = f"""DELETE FROM confessions
        #             WHERE confession_id = $1
        #             AND guild_id = $2
        #             AND channel_id = $3
        #          """
        for message_id in payload.message_ids:
            await self._set_deletion_status(payload.guild_id, message_id, deletion_status=True)
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
        embed_dict = {'title': 'Anonymous confession',
                      'footer': {'text': f"Ban code for user: {record['confession_ban_code']}"},
                      }
        body_text = record.get('confession_text')
        if body_text:
            embed_dict['description'] = body_text

        if is_detailed:
            guild, channel = await helpers.get_guild_by_id(self.bot, record['guild_id']), None
            if guild:
                channel = await helpers.get_channel_by_id(self.bot, guild, record['channel_id'])

            embed_dict['fields'] = [{'name': "User hash code", 'value': record['user_hash_id'], 'inline': True},
                                    {'name': 'Guild ID', 'value': guild.name if guild else record['guild_id'], 'inline': True},
                                    {'name': 'Channel ID', 'value': channel.mention if channel else record['channel_id'], 'inline': True},
                                    {'name': 'Date of confession', 'value': record['timestamp'].strftime('%Y-%m-%d'),
                                     'inline': True}
                                    ]
            if 'user_banned' in record:
                val = {'name': 'User banned?', 'value': 'Yes' if record['user_banned'] else 'No', 'inline': True}
                embed_dict['fields'].append(val)

            if 'is_deleted' in record:
                val = {'name': 'Is deleted?', 'value': 'Yes' if record['is_deleted'] else 'No', 'inline': True}
                embed_dict['fields'].append(val)

            if 'reason' in record:
                val = {'name': 'Reason:', 'value': record['reason'], 'inline': False}
                embed_dict['fields'].append(val)

        e = CustomEmbed.from_dict(embed_dict, avatar_url=self.bot.user.avatar_url)
        if record['image_url'] != '':
            e.set_image(url=record['image_url'])

        json_attachments = record.get('attachment_urls')
        if json_attachments:
            attachments = json.loads(record['attachment_urls'])
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

    async def _fetch_warn_with_ban_code(self, ctx, guild_id, ban_code):
        """ Fetch user warns with confession warn code """
        query = f"""SELECT *
                    FROM warns
                    WHERE confession_ban_code = $1
                    AND guild_id = $2
                """

        # Make sure it's valid ban code
        if not self._check_ban_code(ban_code):
            raise commands.UserInputError(f"Given ban code is not valid: **{ban_code}**")

        return await ctx.db.fetch(query, ban_code, guild_id)

    # async def _delete_with_ban_code(self, ctx, guild_id, ban_code):
    #     """ Delete a confession with ban code."""
    #     query = f"""DELETE FROM confessions
    #                 WHERE confession_ban_code = $1
    #                 AND guild_id = $2
    #             """
    #
    #     # Make sure it's valid ban code
    #     if not self._check_ban_code(ban_code):
    #         raise commands.UserInputError(f"Given ban code is not valid: **{ban_code}**")
    #
    #     await ctx.db.execute(query, ban_code, guild_id)

    async def _fetch_with_user_code(self, ctx, guild_id, user_hash_code):
        """ Fetch banned user with ban code """
        query = f"""SELECT *
                    FROM bannedusers
                    WHERE user_hash_id = $1 AND
                    guild_id = $2
                """
        row = await ctx.db.fetchrow(query, user_hash_code, guild_id)

        return row

    async def _set_ban_status(self, ctx, guild_id: int, user_hash_id: str, ban_status: bool = False):
        """ Set a user ban status for a confession."""
        update_query = """ UPDATE confessions
                       SET user_banned = $1
                       WHERE user_hash_id = $2
                       AND guild_id = $3
                       """
        await ctx.db.execute(update_query, ban_status, user_hash_id, guild_id)

    async def _set_deletion_status(self, guild_id: int, confession_id: int, deletion_status: bool = False):
        """ Set whether a confession has been deleted"""
        update_query = """ UPDATE confessions
                       SET is_deleted = $1
                       WHERE confession_id = $2
                       AND guild_id = $3
                       """
        res = await self.bot.pool.execute(update_query, deletion_status, confession_id, guild_id)
        num_updated = helpers.representsInt(res.split(' ')[-1])
        return num_updated

    async def _set_message_info(self, ctx, guild_id: int, ban_code: str,
                                new_confession_id: int, new_channel_id: int):
        """ Update message and channel id for a confession"""
        update_query = """ UPDATE confessions
                       SET confession_id = $1, channel_id = $2
                       WHERE confession_ban_code = $3
                       AND guild_id = $4
                       """
        await ctx.db.execute(update_query, new_confession_id, new_channel_id, ban_code, guild_id)
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
        await self.bot.wait_until_ready()

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
        # filter guilds to keep only guild the user in
        guilds = [guild for guild in guilds if await helpers.get_member_by_id(guild, author.id) is not None]
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
            guild, _ = await helpers.get_multichoice_answer(self.bot, ctx, guild_dict, question)
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

        # check member has required role to confess
        try:
            helpers.has_any_role(member.roles, valid_confession_roles)
        except commands.MissingAnyRole as err:
            self.currently_confessing.discard(author.id)
            missing_roles_str = ', '.join(err.missing_roles[0])
            return await channel.send(f"You cannot create a confession because you are missing"
                                      f" at least one of the role: **{missing_roles_str}**")

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
        await ctx.send(f'Confession channel set to {channel.mention} for server **{guild.name}**',
                       delete_after=short_delay)

    @confess.command(name='get_channel', help='Get confession channel if it has been set.',
                     usage='', aliases=['get', 'g'])
    @commands.guild_only()
    async def get_channel(self, ctx):
        guild = ctx.guild
        channel_id = self.confession_servers_map.get(guild.id, None)
        if channel_id:
            channel = await helpers.get_channel_by_id(self.bot, guild, channel_id)
            if channel:
                await ctx.send(f'Confession channel for **{guild.name}** is **{channel.mention}**', delete_after=short_delay)
            else:
                await ctx.send(f'Confession channel for **{guild.name}** has been set with channel ID {channel_id}'
                               f'however the channel is no longer reachable, maybe deleted or maybe restricted.\n'
                               f'Please use **set_channel** command to set a valid text channel.', delete_after=short_delay)

        else:
            await ctx.send(f'Confession channel has not been set for **{guild.name}**.\n'
                           f'Please use **set_channel** command to set a confession channel'
                           f'if you have required privileges.', delete_after=short_delay)

    @confess.command(name='fetchall', help='Fetch all the confession logs from DB for this guild',
                     usage='<is_deleted>\n\n'
                           'is_deleted: bool, default False - whether list only deleted records',
                     aliases=['fa'])
    @commands.has_permissions(manage_messages=True, ban_members=True)
    @commands.guild_only()
    async def fetchall(self, ctx, is_deleted: bool = False):
        query = """SELECT confession_id,
                    confession_ban_code,
                    user_hash_id,
                    guild_id,
                    channel_id,
                    timestamp,
                    confession_text,
                    image_url,
                    attachment_urls,
                    user_banned,
                    is_deleted
                    FROM confessions
                    WHERE guild_id = $1
                    AND is_deleted=$2
                    ORDER BY timestamp"""

        sent_messages, sent_navs = [ctx.message], []
        try:
            guild = ctx.guild
            records = await ctx.db.fetch(query, guild.id, is_deleted)
            if len(records) == 0:
                return await ctx.send('No results found...', delete_after=short_delay)

            nav = pag.EmbedNavigatorFactory(max_lines=20)
            nav.add_line('**__Confession logs__**')
            row_num_to_id = {}
            for index, (_id, ban_code, _, _, _, date, text, _, _, ban_status, is_deleted) in enumerate(records):
                shorten = textwrap.shorten(text, width=150)
                line = f'**{index+1}) ID**: {_id} | **BCode**: {ban_code} | **Deleted?**: {is_deleted} | ' \
                       f'**{date}** -> {shorten}'
                row_num_to_id[index+1] = _id
                nav.add_line(line)
                nav.add_line('**-----------------------------**')

            emb_nav = nav.build(ctx=ctx)
            emb_nav.start()
            sent_navs.append(emb_nav)

            question = 'Please type the row number for check details otherwise type c'
            try:
                choice, msg = await helpers.get_multichoice_answer(self.bot, ctx, row_num_to_id, question, timeout=short_delay)
                sent_messages.extend(msg)
            except asyncio.TimeoutError as e:
                return await ctx.send('Please type in 60 seconds next time.')

            if choice is None:
                return await ctx.send('Command has been cancelled.', delete_after=short_delay)

            record = next((record for record in records if record['confession_id'] == choice), None)
            url = f'URL: <https://discordapp.com/channels/{guild.id}/{record["channel_id"]}/{record["confession_id"]}>'
            e = await self._create_embed(record, is_detailed=True)
            await ctx.send(url, embed=e.to_embed())
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=mid_delay)

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
                    WHERE user_hash_id=$1 
                    AND is_deleted=false"""

        author = ctx.author
        channel = ctx.channel
        user_hexdigest = Confession.get_hash_code(str(author.id), n=16)

        records = await ctx.db.fetch(query, user_hexdigest)
        if len(records) == 0:
            return await ctx.send('No confession has been found...', delete_after=short_delay)

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
            guild, _ = await helpers.get_multichoice_answer(self.bot, ctx, guild_dict, question)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to provide the choice is timeout. Please "
                                      "choose your confession server again to be able to provide another.")
        except commands.UserInputError as err:
            raise err

        if guild is None:
            return await ctx.send('Command has been cancelled.', delete_after=short_delay)

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
            choice, _ = await helpers.get_multichoice_answer(self.bot, ctx, row_num_to_id, question, timeout=60)
        except asyncio.TimeoutError as e:
            return await ctx.send('Please type in 60 seconds next time.', delete_after=short_delay)

        if choice is None:
            return await ctx.send('Command has been cancelled.', delete_after=short_delay)

        record = next((record for record in records if record['confession_id'] == choice), None)
        e = await self._create_embed(record, is_detailed=False)
        url = f'URL: <https://discordapp.com/channels/{guild.id}/{record["channel_id"]}/{record["confession_id"]}>'
        await ctx.send(url, embed=e.to_embed())

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
                    WHERE user_hash_id=$1
                    AND is_deleted=false """

        author = ctx.author
        channel = ctx.channel
        user_hexdigest = Confession.get_hash_code(str(author.id), n=16)

        records = await ctx.db.fetch(query, user_hexdigest)
        if len(records) == 0:
            return await ctx.send('No confession has been found...', delete_after=short_delay)

        # Get guilds for that user
        guild_ids = list({record['guild_id'] for record in records})
        guilds = [await helpers.get_guild_by_id(self.bot, guild_id) for guild_id in guild_ids]
        if len(guilds) == 0:
            return await ctx.send('There is no server can be reachable at that moment.', delete_after=short_delay)

        guild_dict = {index + 1: guild for index, guild in enumerate(guilds)}
        guild_text = '\n'.join([f'**{index}) {guild.name}**' for index, guild in guild_dict.items()])
        question = f"Which server you want to delete confession? " \
                   f"Please choose the number or press **c** cancel it\n" \
                   f"If one of the server you have confessed is not here, please contact with" \
                   f"server moderation.\n" \
                   f"**__Servers__**\n" \
                   f"{guild_text}"

        try:
            guild, _ = await helpers.get_multichoice_answer(self.bot, ctx, guild_dict, question)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to provide the choice is timeout. Please "
                                      "choose your confession server again to be able to provide another.",
                                      delete_after=short_delay)
        except commands.UserInputError as err:
            raise err

        if guild is None:
            return await ctx.send('Command has been cancelled.', delete_after=short_delay)

        # Check user banned from that guild
        res = await self._fetch_with_user_code(ctx, guild.id, user_hexdigest)
        if res:
            return await channel.send(f"You've been banned from **{guild.name}** to delete a confession.\n"
                                      f"**Confession ban code you get banned**: {res['confession_ban_code']}.\n"
                                      f"**Ban date**: {res['timestamp'].strftime('%Y-%m-%d')} \n"
                                      f"**Reason**: {res['reason']}", delete_after=short_delay)

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
            choice, _ = await helpers.get_multichoice_answer(self.bot, ctx, row_num_to_id, question, timeout=short_delay)
        except asyncio.TimeoutError as e:
            return await ctx.send('Please type in 60 seconds next time.', delete_after=short_delay)

        if choice is None:
            return await ctx.send('Command has been cancelled.', delete_after=short_delay)

        record = next((record for record in records if record['confession_id'] == choice), None)
        # Remove the confession from DB
        # await self._delete_with_ban_code(ctx, guild.id, record['confession_ban_code'])
        # # No remove from DB but set the deleted flag
        # await self._set_deletion_status(guild.id, record['confession_id'], deletion_status=True)
        # Remove the message from channel
        channel = await helpers.get_channel_by_id(self.bot, guild, record['channel_id'])
        if channel:
            try:
                msg = await channel.fetch_message(record['confession_id'])
            except NotFound as err:
                # Manually set the deletion status
                await self._set_deletion_status(guild.id, record['confession_id'], deletion_status=True)
                log.exception(f"Message not found with id: "
                              f"{record['confession_id']} to delete.")
            else:
                if msg:
                    await msg.delete()

        e = await self._create_embed(record, is_detailed=False)
        await ctx.send('The following confession has been deleted.', embed=e.to_embed(), delete_after=short_delay)

    async def _ban(self, ctx, ban_code, reason, record=None):
        """ Ban method """
        guild = ctx.guild

        # Fetch record with given ban code
        if record is None:
            record = await self._fetch_with_ban_code(ctx, guild.id, ban_code)

        # Check if the user of the confession has already banned
        if not record['user_banned']:
            # set ban status of a confession in DB
            await self._set_ban_status(ctx, guild.id, record['user_hash_id'], ban_status=True)
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
                except Exception as err:
                    # Manually set the deletion status
                    await self._set_deletion_status(guild.id, record['confession_id'], deletion_status=True)
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
                e = await self._create_embed(record, is_detailed=False)
                try:
                    await ban_member.send(f"You've been banned from posting confessions on "
                                          f"the server **{guild.name}**. \n"
                                          f"**Reason**: {reason} \n"
                                          f"**Banned by**: {ctx.author.mention} \n"
                                          f"Your identity is still a secret. Don't worry about it too much.\n"
                                          f"Here is the confession caused to ban:",
                                          embed=e, delete_after=short_delay)
                except Exception:
                    pass

                return await ctx.send("That user has been banned from sending in more confessions on your server.",
                                      delete_after=short_delay)
            else:
                return await ctx.send("Given user has not been found to ban.", delete_after=short_delay)
        else:
            return await ctx.send("Given user has already been banned. "
                                  "If you have permissions, you can check banned users via **fetchban** command.",
                                  delete_after=short_delay)

    @confess.command(name='ban', help='Ban a member to send confession',
                     usage='<ban_code> <reason> \n Use " " to define reason longer than one word',
                     aliases=['b'])
    @commands.has_permissions(manage_messages=True, ban_members=True)
    @commands.guild_only()
    async def ban(self, ctx, ban_code, reason):
        """Bans a user from being able to send in any more confessions to your server"""
        return await self._ban(ctx, ban_code, reason)

    @confess.command(name='warn', help='Warn a user for a confession',
                     usage='<ban_code> <reason> \n Use " " to define reason longer than one word',
                     aliases=['w'])
    @commands.has_permissions(manage_messages=True, ban_members=True)
    @commands.guild_only()
    async def warn(self, ctx, ban_code, reason):
        """Warn a user for a confession"""
        guild = ctx.guild

        # Fetch record and warn record  with given ban code
        record = await self._fetch_with_ban_code(ctx, guild.id, ban_code)
        warn_records = await self._fetch_user_warns(guild.id, record['user_hash_id'])

        if warn_records:
            is_already_warned = any([True for record in warn_records if ban_code == record['confession_ban_code']])

            if is_already_warned:
                return await ctx.send('The member has already been warned for this confession', delete_after=short_delay)

            if len(warn_records) == warn_limit:
                return await ctx.send(f'The member has already reached warn limits: {warn_limit}', delete_after=short_delay)

        if len(record) == 0:
            return await ctx.send('There is no confession for this server with given ban code', delete_after=short_delay)

        if record['user_banned']:
            return await ctx.send('The user has already banned from confession server', delete_after=short_delay)

        # get number of remaining warning for this user and check if it get banned
        num_warned = len(warn_records) + 1
        num_remaining = warn_limit - num_warned
        get_banned = False if num_remaining > 0 else True
        if get_banned:
            confirm = await ctx.prompt(f'The user has been reached warn limit: {warn_limit}\n '
                                       f'If you give this warning, he/she will be **BANNED!!** from sending confession.'
                                       f'Are you sure you want to warn?', timeout=short_delay,
                                       delete_after=True, user_id=ctx.author.id)
            if not confirm:
                return await ctx.send('Operation has been cancelled', delete_after=short_delay)

        # Add user to warned user for this guild
        query = 'INSERT INTO warns VALUES ($1, $2, $3, $4, $5, $6, $7)'
        params = (ban_code, record['confession_id'],
                  record['user_hash_id'], guild.id,
                  record['channel_id'], datetime.datetime.utcnow(), reason)
        try:
            await ctx.db.execute(query, *params)
        except asyncpg.UniqueViolationError as err:
            log.exception(err)

        # Remove the original confession and tell the other people the user has been warned
        e = await self._create_embed(record, is_detailed=False)
        channel = await helpers.get_channel_by_id(self.bot, guild, record['channel_id'])
        if channel:
            if not get_banned:
                try:
                    msg = await channel.fetch_message(record['confession_id'])
                except NotFound as err:
                    # Manually set the deletion status
                    await self._set_deletion_status(guild.id, record['confession_id'], deletion_status=True)
                    log.exception(f"Message not found with **ID: "
                                  f"{record['confession_id']}** to delete "
                                  f"after **ban code: {ban_code}**. {err}")
                else:
                    if msg:
                        await msg.delete()

            try:
                await channel.send('A member has been warned for the following confession.',
                                   embed=e, delete_after=long_delay)
            except Exception as err:
                log.exception(f'Member warning announcement cannot send in warning op: \n {err}')

        # Find member with given user hash code if it is still in the guild
        warn_member = self._find_member_by_hash_code(guild, record['user_hash_id'])
        if warn_member:
            try:
                await warn_member.send(f"You've been warned from posting confessions on "
                                       f"the server **{guild.name}**. \n"
                                       f"**Warn: {num_warned}/{warn_limit}\n"
                                       f"**Reason**: {reason} \n"
                                       f"**Warned by**: {ctx.author.mention} \n"
                                       f"Your identity is still a secret. Don't worry about it too much.\n"
                                       f"Here is the confession caused to warn:",
                                       embed=e, delete_after=short_delay)
            except Exception as err:
                log.exception(f'The user to send pm message in warn operation not found:\n {err}')

        else:
            await ctx.send("Given user has not been found to warn.", delete_after=short_delay)

        if get_banned:
            ban_reason = f'Banned after {warn_limit} warnings'
            return await self._ban(ctx, ban_code, ban_reason)

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
                                  " or you have given wrong user hash code.", delete_after=short_delay)

        await ctx.db.execute(query, guild.id, user_hash_code)
        await ctx.send(f"Member with **hash code: {user_hash_code}** has been unbanned for **{guild.name}**.",
                       delete_after=short_delay)

        # unban in db
        await self._set_ban_status(ctx, guild.id, res['user_hash_id'])

        # send a pm message to unbanned user
        member = self._find_member_by_hash_code(guild, user_hash_code)
        if member:
            await member.send(f'Congratulations, you have been unbanned in **{guild.name}**'
                              f' by {ctx.author.mention}', delete_after=short_delay)

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
                                                  f"trying to send your deleted confession to confession channel:/",
                                                  delete_after=short_delay)
                else:
                    # Set the confession deletion status to False
                    await self._set_deletion_status(guild.id, confession['confession_id'], deletion_status=False)
                    # if we resend the confession, we should update the confession id and confession channel
                    # since current confession channel and DB record may differ
                    await self._set_message_info(ctx, guild.id, res['confession_ban_code'], confessed_message.id,
                                                 confession_channel_id)

        # Last, remove all warnings for that user
        await self._delete_user_warns(guild.id, res['user_hash_id'])

    @confess.command(name='fetchban', help='Fetch banned users from confession',
                     usage='', aliases=['fb'])
    @commands.has_permissions(manage_messages=True, ban_members=True)
    @commands.guild_only()
    @commands.is_owner()
    async def fetch_ban(self, ctx):
        query = """SELECT user_hash_id,
                    guild_id,
                    confession_ban_code,
                    timestamp,
                    reason
                    FROM bannedusers
                    WHERE guild_id = $1"""

        sent_messages, sent_navs = [ctx.message], []
        try:
            guild = ctx.guild
            records = await ctx.db.fetch(query, guild.id)
            if len(records) == 0:
                return await ctx.send('No results found...')

            nav = pag.EmbedNavigatorFactory(max_lines=20)
            nav.add_line('**__Banned Users__**')
            row_num_to_code = {}
            for index, (_id, guild_id, confession_ban_code, date, reason) in enumerate(records):
                line = f'**{index+1}) User Hash code**: {_id} | **Guild ID:** {guild_id}' \
                       f' **BCode**: {confession_ban_code} | **{date}** -> {reason}'
                row_num_to_code[index+1] = confession_ban_code
                nav.add_line(line)
                nav.add_line('**-----------------------------**')

            emb_nav = nav.build(ctx=ctx)
            emb_nav.start()
            sent_navs.append(emb_nav)

            question = 'Please type the row number for check details otherwise type c'
            try:
                choice, msg = await helpers.get_multichoice_answer(self.bot, ctx, row_num_to_code, question, timeout=short_delay)
                sent_messages.extend(msg)
            except asyncio.TimeoutError as e:
                return await ctx.send('Please type in 60 seconds next time.', delete_after=short_delay)

            if choice is None:
                return await ctx.send('Command has been cancelled.', delete_after=short_delay)

            ban_record = next((record for record in records if record['confession_ban_code'] == choice), None)
            record = await self._fetch_with_ban_code(ctx, guild.id, ban_record['confession_ban_code'])
            e = await self._create_embed(record)
            await ctx.send(embed=e.to_embed(), delete_after=short_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=short_delay)

    @confess.command(name='fetchwarn', help='Fetch warned users for confession',
                     usage='', aliases=['fw'])
    @commands.has_permissions(manage_messages=True, ban_members=True)
    @commands.guild_only()
    @commands.is_owner()
    async def fetchwarn(self, ctx):
        query = """SELECT confession_ban_code,
                    confession_id,
                    user_hash_id,
                    guild_id,
                    channel_id,
                    timestamp,
                    reason
                    FROM warns
                    WHERE guild_id = $1"""

        sent_messages, sent_navs = [ctx.message], []
        try:
            guild = ctx.guild
            records = await ctx.db.fetch(query, guild.id)
            if len(records) == 0:
                return await ctx.send('No results found...', delete_after=short_delay)

            nav = pag.EmbedNavigatorFactory(max_lines=20)
            nav.add_line('**__Warned Users__**')
            row_num_to_code = {}
            for index, (confession_ban_code, confession_id, _id, guild_id, _, date, reason) in enumerate(records):
                line = f'**{index+1}) User Hash code**: {_id} | **Guild ID:** {guild_id}' \
                       f' **BCode**: {confession_ban_code} | **{date}** -> {reason}'
                row_num_to_code[index+1] = confession_ban_code
                nav.add_line(line)
                nav.add_line('**-----------------------------**')

            emb_nav = nav.build(ctx=ctx)
            emb_nav.start()
            sent_navs.append(emb_nav)

            question = 'Please type the row number for check details otherwise type c'
            try:
                choice, msg = await helpers.get_multichoice_answer(self.bot, ctx, row_num_to_code, question, timeout=short_delay)
            except asyncio.TimeoutError:
                return await ctx.send('Please type in 60 seconds next time.', delete_after=short_delay)

            if choice is None:
                return await ctx.send('Command has been cancelled.')

            warn_record = next((record for record in records if record['confession_ban_code'] == choice), None)
            record = await self._fetch_with_ban_code(ctx, guild.id, warn_record['confession_ban_code'])
            e = await self._create_embed(record)
            await ctx.send(embed=e.to_embed(), delete_after=short_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=short_delay)

    async def _fetch_all_user_warns(self, guild_id):
        """ Fetch all user warns for given guild """
        query = """SELECT COUNT(confession_ban_code) AS warn_count,
                user_hash_id
                FROM warns
                WHERE guild_id = $1
                GROUP BY user_hash_id
                ORDER BY COUNT(confession_ban_code) DESC"""

        return await self.bot.pool.fetch(query, guild_id)

    async def _fetch_user_warns(self, guild_id, user_hash_id):
        """ Fetch a user warns for given server and user ID """
        query = """SELECT confessions.confession_id,  confession_ban_code,
                    user_hash_id, guild_id, channel_id, timestamp, confession_text,
                    image_url, attachment_urls, user_banned
                    FROM confessions
                    INNER JOIN(SELECT confession_id
                               FROM warns
                               WHERE guild_id = $1 AND user_hash_id = $2) user_warns
                    ON user_warns.confession_id = confessions.confession_id"""

        return await self.bot.pool.fetch(query, guild_id, user_hash_id)

    async def _delete_user_warns(self, guild_id, user_hash_id):
        """ Delete a user warns """
        query = f"""DELETE FROM warns
                    WHERE guild_id = $1
                    AND user_hash_id = $2
                 """
        return await self.bot.pool.execute(query, guild_id, user_hash_id)

    @confess.command(name='fetch_u_warn', help='Fetch warned users by number of warnings',
                     usage='', aliases=['fuw'])
    @commands.has_permissions(manage_messages=True, ban_members=True)
    @commands.guild_only()
    @commands.is_owner()
    async def fetch_u_warn(self, ctx):
        sent_messages, sent_navs = [ctx.message], []
        try:
            guild = ctx.guild
            records = await self._fetch_all_user_warns(guild.id)
            if len(records) == 0:
                return await ctx.send('No results found...', delete_after=short_delay)

            nav = pag.EmbedNavigatorFactory(max_lines=20)
            nav.add_line('**__Warned Users by count__**')
            row_num_to_code = {}
            for index, (count, user_hash_id) in enumerate(records):
                line = f'**{index+1})** ID: **{user_hash_id}**  | **{count}**'
                row_num_to_code[index+1] = user_hash_id
                nav.add_line(line)

            emb_nav = nav.build(ctx=ctx)
            emb_nav.start()
            sent_navs.append(emb_nav)

            question = 'Please type the row number for check details otherwise type c'
            try:
                choice, msg = await helpers.get_multichoice_answer(self.bot, ctx, row_num_to_code, question, timeout=short_delay)
                sent_messages.extend(msg)
            except asyncio.TimeoutError:
                return await ctx.send('Please type in 60 seconds next time.', delete_after=short_delay)

            if choice is None:
                return await ctx.send('Command has been cancelled.', delete_after=short_delay)

            correct_record = next((record for record in records if record['user_hash_id'] == choice), None)

            records = await self._fetch_user_warns(guild.id, correct_record['user_hash_id'])
            if len(records) == 0:
                raise ValueError('The warning records does not match with confessions records')

            for record in records:
                e = await self._create_embed(record)
                await ctx.send(embed=e.to_embed(), delete_after=short_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=short_delay)

    @confess.command(name='decrypt', hidden=True,
                     usage='', aliases=['dc'])
    @commands.has_role(TIER5)
    @commands.guild_only()
    @commands.is_owner()
    async def decrypt(self, ctx, user_hash_code: str):
        found_member = self._find_member_by_hash_code(ctx.guild, user_hash_code)
        return await ctx.send(f'Member is: {found_member.mention if found_member else "No member"}')

    # *************** irritation ****************

    @confess.command(name='irritate', help='Report a confession that irritates you',
                     usage='', aliases=['ir'])
    @commands.dm_only()
    @commands.cooldown(1, command_cooldown, commands.BucketType.user)
    async def irritate(self, ctx):
        author = ctx.author
        channel = ctx.channel
        user_hexdigest = Confession.get_hash_code(str(author.id), n=16)

        # Get guilds for that user
        guilds = [await helpers.get_guild_by_id(self.bot, guild_id) for guild_id in self.confession_servers_map.keys()]
        # filter guilds to keep only guild the user in
        guilds = [guild for guild in guilds if await helpers.get_member_by_id(guild, author.id) is not None]

        if len(guilds) == 0:
            return await ctx.send('There is no server can be reachable at that moment.')

        guild_dict = {index + 1: guild for index, guild in enumerate(guilds)}
        guild_text = '\n'.join([f'**{index}) {guild.name}**' for index, guild in guild_dict.items()])
        question = f"Which server you want to report irritation? " \
                   f"Please choose the number or press **c** cancel it\n" \
                   f"**__Servers__**\n" \
                   f"{guild_text}"

        try:
            guild, _ = await helpers.get_multichoice_answer(self.bot, ctx, guild_dict, question)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to provide the choice is timeout. Please "
                                      "choose your confession server again to be able to provide another.")
        except commands.UserInputError as err:
            raise err

        if guild is None:
            return await ctx.send('Command has been cancelled.')

        question_2 = f"Please enter the ban code of confession you irritate\n " \
                     f"You can find the ban code at the bottom of a confession.\n" \
                     f"Type **c** to cancel the command."

        def check_msg(m):
            if m.author.id != ctx.author.id:
                return False
            if m.channel != ctx.channel:
                return False

            return m.content == 'c' or self._check_ban_code(m.content)

        await channel.send(question_2)
        try:
            ban_code_msg = await self.bot.wait_for("message", check=check_msg, timeout=short_delay)
        except asyncio.TimeoutError as err:
            return await ctx.send('Timeout error, please enter the code faster than 60 seconds')
        else:
            if ban_code_msg.content == 'c':
                return await ctx.send('Command has been cancelled')

        ban_code = ban_code_msg.content
        record = await self._fetch_with_ban_code(ctx, guild.id, ban_code)

        # Check user banned from that guild
        res = await self._fetch_with_user_code(ctx, guild.id, record['user_hash_id'])
        if res:
            return await channel.send(f"The user you have been irritated has been already **BANNED**"
                                      f"from confessions server, so no worries.")

        if record['user_hash_id'] == user_hexdigest:
            return await ctx.send('The confession ban code belongs to your confessions.\n'
                                  'If you irritated your own confession, you can delete by using **?confess delete**')

        # check the user already report irritation for this confession
        check_query = "SELECT confession_ban_code FROM irritations " \
                      "WHERE confession_ban_code = $1" \
                      "AND user_hash_id = $2" \
                      "AND guild_id=$3"
        if await ctx.db.fetchrow(check_query, ban_code, user_hexdigest, guild.id) is not None:
            return await ctx.send('You have been send your irritations for this confession already.\n'
                                  'Please beware that excessive use of this command may'
                                  ' **BAN** you to use other commands.')

        # Get irritation
        def check_msg(m):
            if m.author.id != ctx.author.id:
                return False
            if m.channel != ctx.channel:
                return False

            return True

        await channel.send(f"Please explain your irritation. "
                           f"PLease use letters to cleanly explain your pinpoints.\n"
                           f"You have **{message_timeout} seconds** to complete.")
        try:
            irritation_msg = await self.bot.wait_for("message",
                                                     check=check_msg,
                                                     timeout=message_timeout)
        except asyncio.TimeoutError:
            return await channel.send("The timer for you to give a server id has timed out. Please "
                                      "give your confession again to be able to provide another.")

        # Add user to warned user for this guildto get irritated for this confession
        query = 'INSERT INTO irritations VALUES ($1, $2, $3, $4, $5, $6, $7)'
        params = (record['confession_id'], ban_code,
                  user_hexdigest, guild.id,
                  record['channel_id'], datetime.datetime.utcnow(), irritation_msg.content)
        try:
            await ctx.db.execute(query, *params)
        except asyncpg.UniqueViolationError as err:
            print(err)
            log.exception(err)

        # Report irritation msg to admin channel
        admin_channel = await helpers.get_channel_by_id(self.bot, guild, ADMIN_CHANNEL_ID)
        if admin_channel:
            url = f'URL: <https://discordapp.com/channels/{guild.id}/{record["channel_id"]}/{record["confession_id"]}>'
            admin_msg = f"A member has been report an irritation:\n" \
                        f"**{irritation_msg.content}**\n" \
                        f"{url}\n" \
                        f"Here is the confession the member has been irritated:"

            e = await self._create_embed(record, is_detailed=False)
            try:
                await admin_channel.send(admin_msg, embed=e.to_embed())
            except Exception as e:
                await ctx.send(f"I encountered the error `{e}` "
                               f"trying to send your deleted confession to confession channel:/")
        return await ctx.send('Operation finished.')

    @confess.command(name='fetch_irritation', help='Fetch all irritations',
                     usage='<ban_code>\n\n'
                           'ban_code: str,  default None - if ban ode given, '
                           'only the record with ban code returned.\n\n',
                     aliases=['fir'])
    @commands.has_permissions(manage_messages=True, ban_members=True)
    @commands.guild_only()
    @commands.is_owner()
    async def fetch_irritation(self, ctx, ban_code: str = None):
        sent_messages, sent_navs = [ctx.message], []
        try:
            query = """SELECT *
                        FROM irritations
                        WHERE guild_id = $1"""
            guild = ctx.guild
            if ban_code is not None:
                query += ' AND confession_ban_code=$2'
                records = await ctx.db.fetch(query, guild.id, ban_code)
            else:
                records = await ctx.db.fetch(query, guild.id)

            if len(records) == 0:
                return await ctx.send('No results found...')

            nav = pag.EmbedNavigatorFactory(max_lines=20)
            nav.add_line('**__Irritations__**')
            row_num_to_code = {}
            for index, (_id, bcode, user_hash_id, _, _, date, msg) in enumerate(records):
                line = f'**{index + 1})** Irritated ID: **{user_hash_id}**  | Confession ID: **{_id}** | \n' \
                       f'BCode: **{bcode}** | **{date}** --> {msg}'
                row_num_to_code[index + 1] = _id
                nav.add_line(line)

            emb_nav = nav.build(ctx=ctx)
            emb_nav.start()
            sent_navs.append(emb_nav)

            question = 'Please type the row number for check details otherwise type c'
            try:
                choice, msg = await helpers.get_multichoice_answer(self.bot, ctx, row_num_to_code, question, timeout=short_delay)
                sent_messages.extend(msg)
            except asyncio.TimeoutError:
                return await ctx.send('Please type in 60 seconds next time.', delete_after=short_delay)

            if choice is None:
                return await ctx.send('Command has been cancelled.', delete_after=short_delay)

            correct_record = next((record for record in records if record['confession_id'] == choice), None)
            record = await self._fetch_with_ban_code(ctx, guild.id, correct_record['confession_ban_code'])
            e = await self._create_embed(record)
            await ctx.send(embed=e.to_embed(), delete_after=short_delay)

        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=short_delay)


def setup(bot):
    bot.add_cog(Confession(bot))
