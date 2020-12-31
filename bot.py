import datetime
import json
import logging
import traceback
import aiohttp
import sys
from collections import Counter, deque

from discord.ext import commands
import discord

from utils.config import bot_config
from utils import context, logger
from utils.logger import LOGGER
from utils.json_db import Config


description = """
Qutils bot provides several important utilities for the server.
"""

initial_extensions = (
    # 'cogs.admin',
    'cogs.general',
    # 'cogs.remainder',
    # 'cogs.fun',
    # 'cogs.cameradice',
    # 'cogs.talks',
    # 'cogs.confession',
    # 'cogs.feedback',
    # 'cogs.automation',
    # 'cogs.truthdare'
)


def _prefix_callable(bot, msg):
    if msg.guild is None:
        return commands.when_mentioned_or(*bot.base_prefixes)(bot, msg)
    else:
        return commands.when_mentioned_or(*bot.prefixes.get(msg.guild.id, bot.base_prefixes))(bot, msg)


def exception_handler(loop, ctx):
    err = f'{ctx.get("message", "-")} | {ctx.get("exception", "-")}\n' \
          f'{ctx.get("future", "-")}'
    LOGGER.exception(err)


class Qutils(commands.AutoShardedBot):
    def __init__(self, intents):
        super().__init__(command_prefix=_prefix_callable, description=description, case_insensitive=True,
                         pm_help=None, help_attrs=dict(hidden=True), fetch_offline_members=True,
                         activity=discord.Game(name=":help for mods"), intents=intents
                         )

        self.client_id = bot_config.auth.client_id

        self.session = aiohttp.ClientSession(loop=self.loop)

        self._prev_events = deque(maxlen=10)

        self.owner_ids = bot_config.owner_ids

        # setup prefix per guild
        self.prefixes = {}
        for guild_id, guild_conf in bot_config.guilds.items():
            guild_prefix = guild_conf.prefix
            if guild_prefix:
                self.prefixes[guild_id] = guild_prefix

        self.prefixes = bot_config

        # base default prefixes
        self.base_prefixes = ['?', '!']

        # guild_id and user_id mapped to True
        # these are users and guilds globally blacklisted
        # from using the bot
        self.blacklist = Config('blacklist.json')

        # in case of even further spam, add a cooldown mapping
        # for people who excessively spam commands
        self.spam_control = commands.CooldownMapping.from_cooldown(10, 12.0, commands.BucketType.user)

        # A counter to auto-ban frequent spammers
        # Triggering the rate limit 5 times in a row will auto-ban the user from the bot.
        self._auto_spam_count = Counter()
        # remove default help command for a custom help
        self.remove_command('help')
        for extension in initial_extensions:
            try:
                self.load_extension(extension)
            except Exception as e:
                print(e)
                LOGGER.exception(f'Failed to load extension {extension}.', exc_info=True)
            else:
                LOGGER.info(f'Extension loaded: {extension}')

        # Set event loop exception handler
        self.loop.set_exception_handler(exception_handler)

    async def on_socket_response(self, msg):
        self._prev_events.append(msg)

    async def on_command_error(self, ctx, error):
        if isinstance(error, commands.NoPrivateMessage):
            await ctx.author.send('This command cannot be used in private messages.')
        elif isinstance(error, commands.DisabledCommand):
            await ctx.author.send('Sorry. This command is disabled and cannot be used.')
        elif isinstance(error, commands.CommandInvokeError):
            original = error.original
            if not isinstance(original, discord.HTTPException):
                print(f'In {ctx.command.qualified_name}:', file=sys.stderr)
                traceback.print_tb(original.__traceback__)
                print(f'{original.__class__.__name__}: {original}', file=sys.stderr)
        elif isinstance(error, commands.ArgumentParsingError):
            await ctx.send(error)

    def get_guild_prefixes(self, guild: discord.Guild, *, local_inject=_prefix_callable):
        proxy_msg = discord.Object(id=0)
        proxy_msg.guild = guild
        return local_inject(self, proxy_msg)

    def get_raw_guild_prefixes(self, guild_id):
        return bot_config.get_guild_by_id(guild_id).prefix or self.base_prefixes

    async def set_guild_prefixes(self, guild, prefixes):
        if len(prefixes) == 0:
            await self.prefixes.put(guild.id, [])
        elif len(prefixes) > 10:
            raise RuntimeError('Cannot have more than 10 custom prefixes.')
        else:
            await self.prefixes.put(guild.id, sorted(set(prefixes), reverse=True))

    async def add_to_blacklist(self, object_id):
        await self.blacklist.put(object_id, True)

    async def remove_from_blacklist(self, object_id):
        try:
            await self.blacklist.remove(object_id)
        except KeyError:
            pass

    async def on_ready(self):
        if not hasattr(self, 'uptime'):
            self.uptime = datetime.datetime.utcnow()

        # bot is ready, so we can setup discord logging handler
        logger.setup_discord_logger(self)
        LOGGER.info(f'Bot ready, User: {self.user} (ID: {self.user.id})')

    async def on_resumed(self):
        print('Season has been resumed...')

    @property
    def stats_webhook(self):
        wh_id, wh_token = self.config.stat_webhook
        hook = discord.Webhook.partial(id=wh_id, token=wh_token, adapter=discord.AsyncWebhookAdapter(self.session))
        return hook

    def log_spammer(self, ctx, message, retry_after, *, autoblock=False):
        guild_name = getattr(ctx.guild, 'name', 'No Guild (DMs)')
        guild_id = getattr(ctx.guild, 'id', None)
        fmt = 'User %s (ID %s) in guild %r (ID %s) spamming, retry_after: %.2fs'
        LOGGER.warning(fmt, message.author, message.author.id, guild_name, guild_id, retry_after)
        if not autoblock:
            return

        wh = self.stats_webhook
        embed = discord.Embed(title='Auto-blocked Member', colour=0xDDA453)
        embed.add_field(name='Member', value=f'{message.author} (ID: {message.author.id})', inline=False)
        embed.add_field(name='Guild Info', value=f'{guild_name} (ID: {guild_id})', inline=False)
        embed.add_field(name='Channel Info', value=f'{message.channel} (ID: {message.channel.id}', inline=False)
        embed.timestamp = datetime.datetime.utcnow()
        return wh.send(embed=embed)

    async def process_commands(self, message):
        ctx = await self.get_context(message, cls=context.Context)

        if ctx.command is None:
            return

        if ctx.author.id in self.blacklist:
            return

        if ctx.guild is not None and ctx.guild.id in self.blacklist:
            return

        bucket = self.spam_control.get_bucket(message)
        current = message.created_at.replace(tzinfo=datetime.timezone.utc).timestamp()
        retry_after = bucket.update_rate_limit(current)
        author_id = message.author.id
        if retry_after and author_id != self.owner_id:
            self._auto_spam_count[author_id] += 1
            if self._auto_spam_count[author_id] >= 5:
                await self.add_to_blacklist(author_id)
                del self._auto_spam_count[author_id]
                await self.log_spammer(ctx, message, retry_after, autoblock=True)
            else:
                self.log_spammer(ctx, message, retry_after)
            return
        else:
            self._auto_spam_count.pop(author_id, None)

        try:
            await self.invoke(ctx)
        finally:
            # Just in case we have any outstanding DB connections
            await ctx.release()

    async def on_message(self, message):
        if message.author.bot:
            return

        # Send back the prefixes when bot mentioned
        if not message.mention_everyone and self.user.mentioned_in(message):
            guild = message.guild
            prefixes = self.get_guild_prefixes(guild)
            await message.channel.send(f'My prefixes are: **{prefixes}**')

        await self.process_commands(message)

    async def on_guild_join(self, guild):
        if guild.id in self.blacklist:
            await guild.leave()

    async def close(self):
        await super().close()
        await self.session.close()

    def run(self):
        try:
            super().run(bot_config.auth.token, reconnect=True)
        finally:
            with open('prev_events.log', 'w', encoding='utf-8') as fp:
                for data in self._prev_events:
                    try:
                        x = json.dumps(data, ensure_ascii=True, indent=4)
                    except:
                        fp.write(f'{data}\n')
                    else:
                        fp.write(f'{x}\n')

    @property
    def config(self):
        return __import__('config')