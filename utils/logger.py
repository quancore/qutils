"""
An implementation of a logging.Handler for sending messages to Discord
"""
import sys
import traceback
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import asyncio
import coloredlogs
from collections import Counter

import copy
from libneko.embeds import FieldIsTooLong

from utils.config import bot_config
from utils.formats import CustomEmbed
from discord import Colour
from discord.ext import commands

LEVEL_COLORS = {
    logging.CRITICAL: Colour.red().value,
    logging.ERROR: Colour.red().value,
    logging.WARNING: Colour.gold().value,
    logging.INFO: Colour.blurple().value,
    logging.DEBUG: Colour.dark_grey().value
}
# get logger name and log level from config file
LOGGER_NAME = bot_config.bot_settings.get_str("logger_name", "root")
LOG_LEVEL = bot_config.bot_settings.get_str("log_level", "DEBUG").upper()
SENTRY_URL = bot_config.auth.auth_conf.get_str("SENTRY_URL")


def setup_file_logger(logger: logging.getLoggerClass() = None) -> logging.getLoggerClass():
    """ Setup a text file logger by bot config """
    logger = logger or logging.getLogger(LOGGER_NAME)
    log_file = Path("logs", f'{LOGGER_NAME}.log')
    log_file.parent.mkdir(exist_ok=True)
    file_handler = RotatingFileHandler(log_file, maxBytes=5242880, backupCount=7, encoding="utf8")
    dt_fmt = '%Y-%m-%d %H:%M:%S'
    fmt_str = '[{levelname} | {asctime}][{filename}:{lineno} - {funcName}] {name}: {message}'
    fmt = logging.Formatter(fmt_str, dt_fmt, style='{')
    file_handler.setFormatter(fmt)
    logger.addHandler(file_handler)
    logger.setLevel(LOG_LEVEL)

    handler = logging.StreamHandler(sys.stdout)
    handler.setLevel(LOG_LEVEL)
    stream_format = "[%(asctime)s %(levelname)s] [%(filename)s:%(lineno)d] %(name)s %(message)s"
    fmt = logging.Formatter(stream_format, dt_fmt, style='{')
    handler.setFormatter(fmt)
    logger.addHandler(handler)

    coloredlogs.install(logger=logger, fmt=stream_format, datefmt=dt_fmt, level=LOG_LEVEL)

    return logger


def setup_sentry_logger(logger: logging.getLoggerClass() = None) -> logging.getLoggerClass():
    """ Setup remote sentry logger """
    import sentry_sdk
    from sentry_sdk.integrations.logging import LoggingIntegration

    sentry_logging = LoggingIntegration(
        level=LOG_LEVEL,  # Capture info and above as breadcrumbs
        event_level=logging.INFO  # Send errors as events
    )
    sentry_sdk.init(SENTRY_URL, integrations=[sentry_logging])
    sentry_logger = logging.getLogger('sentry_sdk')
    main_logger = logger or logging.getLogger(LOGGER_NAME)
    for handler in sentry_logger.handlers:
        main_logger.addHandler(handler)

    return main_logger


def setup_basic_loggers(set_sentry: bool = False):
    """
    Setup a basic rotating file logger, optionally a sentry logger.

    :param bool set_sentry: whether set a sentry logger or not
    """
    logging.getLogger("discord").setLevel(logging.WARNING)

    logger = logging.getLogger(LOGGER_NAME)
    try:
        # __enter__
        # setup text file logger
        logger = setup_file_logger(logger=logger)

        if set_sentry:
            logger = setup_sentry_logger(logger=logger)

    except Exception:
        print(f"Exception occurred during logger setup:\n{traceback.format_exc()}")
    else:
        logger.info("Basic Logger has been setup.")
    finally:
        logger = ILoggerAdapter(logger, extra={'guild_id': None})

    return logger


# ## Custom logger adapters and handlers ####
class ILoggerAdapter(logging.LoggerAdapter):
    def __init__(self, logger, extra):
        super(ILoggerAdapter, self).__init__(logger, extra)
        self.env = extra

    def process(self, msg, kwargs):
        msg, kwargs = super(ILoggerAdapter, self).process(msg, kwargs)

        result = copy.deepcopy(kwargs)

        default_kwargs_key = ['exc_info', 'stack_info', 'extra']
        custome_key = [k for k in result.keys() if k not in default_kwargs_key]
        result['extra'].update({k: result.pop(k) for k in custome_key})

        return msg, result


class DiscordHandler(logging.Handler):
    """
    A class implementing logging.Handler methods to send logs to a Discord channel.
    """
    def __init__(self, bot: commands.Bot, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.client = bot

        # store guild_id: log channel id
        self.log_channel_id_map = {}
        self.setup_log_channel_ids()

        # shorthand to whether all channels fetched or not
        self.all_channels_fetched = False

        # store guild_id: log channel
        self.log_channel_map = {}
        self.setup_log_channels()

    def setup_log_channel_ids(self):
        """ Fetch log channel ids with guild ids and store in a dict """
        for guild_id, guild_conf in bot_config.guilds.items():
            log_channel_id = guild_conf.get_channels(fallback={}).get("LOGGING_CHANNEL_ID")
            if log_channel_id:
                self.log_channel_id_map[guild_id] = log_channel_id

    def setup_log_channels(self):
        """ Setup log channels using guild config """
        # if the log channel fetched is not equal to log channel ids from config
        # some log channels cannot be fetched, so fetch the log channels again
        if not self.all_channels_fetched:
            for guild_id, log_channel_id in self.log_channel_id_map.items():
                if guild_id not in self.log_channel_map:
                    log_channel = self.client.get_channel(int(log_channel_id))
                    if log_channel:
                        self.log_channel_map[guild_id] = log_channel

            # finally we have fetched all log channels
            if Counter(self.log_channel_map.keys()) == Counter(self.log_channel_id_map.keys()):
                self.all_channels_fetched = True


    # def get_log_channel(self, log_channel_id: int):
    #     for _ in range(5):
    #         loop = getattr(self.client, "loop", None) or asyncio.get_running_loop()
    #         if loop is not None and loop.is_running():
    #             task = asyncio.create_task(helpers.get_channel_by_id(self.client, None, log_channel_id))
    #             loop.run_until_complete(task)
    #             return task.result()
    #         else:
    #             await asyncio.sleep(2)
    #
    #     return None

    @staticmethod
    def _level_to_color(level_number: int):
        return LEVEL_COLORS.get(level_number, Colour.orange().value)

    def emit(self, record: logging.LogRecord):
        if not self.client.loop.is_running():
            # The event loop is not running (discord is not connected)
            return

        # setup log channels if not already done
        self.setup_log_channels()

        # if guild id indicated, send the log only this guild else sent it to all recorded guild
        guild_id = getattr(record, 'guild_id', None)
        if guild_id is not None:
            self.send_log_to_guild(guild_id, record)
        else:
            for guild_id in self.log_channel_map.keys():
                self.send_log_to_guild(guild_id, record)

    def send_log_to_guild(self, guild_id: int, record: logging.LogRecord):
        """
        Send a log message to a guild indicated by guild id.

        :param guild_id: Guild id the log will sent to it.
        :param record: Log record will be sent
        :return: None
        """
        log_channel = self.log_channel_map.get(guild_id)
        if log_channel is not None:
            # Create an embed with a title like "Info" or "Error" and a color
            # relating to the level of the log message
            embed_dict = {'title': record.levelname.title(), 'color': self._level_to_color(record.levelno),
                          'fields': [
                              {'name': "Message", 'value': record.msg, 'inline': False},
                              {'name': "Function", 'value': f"`{record.funcName}`", 'inline': True},
                              {'name': "File name", 'value': f"`{record.filename}`", 'inline': True},
                              {'name': "Line number", 'value': record.lineno, 'inline': True},
                          ],
                          }
            try:
                if self.client.user:
                    e = CustomEmbed.from_dict(embed_dict, avatar_url=self.client.user.avatar_url)
                else:
                    e = CustomEmbed.from_dict(embed_dict)

            except FieldIsTooLong as err:
                print(f"Exception occurred during sending log to guild: {guild_id}:\n{traceback.format_exc()}")
            else:
                if "discord_info" in record.__dict__:
                    for field, value in record.__dict__["discord_info"].items():
                        try:
                            e.add_field(name=field, value=value, inline=True)
                        except FieldIsTooLong as err:
                            print(f"Exception occurred during sending log to guild: {guild_id}:\n{traceback.format_exc()}")

                # Create a task in the event loop to send the logging embed
                if hasattr(self.client, 'loop'):
                    asyncio.ensure_future(self.client.loop.create_task(log_channel.send(embed=e)))


def setup_discord_logger(bot: commands.AutoShardedBot,
                         logger: logging.getLoggerClass() = None) -> ILoggerAdapter:
    """
    Add discord handler using bot to given logger.
    If no logger given, global LOGGER instance will be set.

    :param bot: Discord bot instance needed for Discordhandler.
    :param logger: logger class instance
    :return: adapter logger class instance
    """
    # setup discord logger with custom discord handler
    discord_handler = DiscordHandler(bot)
    if logger is not None:
        logger.addHandler(discord_handler)
        logger.setLevel(LOG_LEVEL)
        wrapped_logger = ILoggerAdapter(logger, extra={'guild_id': None})
        return wrapped_logger
    else:  # if no logger given, setup global LOGGER
        global LOGGER
        LOGGER.logger.addHandler(discord_handler)
        LOGGER.setLevel(LOG_LEVEL)
        return LOGGER


# basic logger instance used for cross modules
LOGGER = setup_basic_loggers(set_sentry=False)
