"""
An implementation of a logging.Handler for sending messages to Discord
"""

import datetime
import logging
import asyncio

from config import LOGGING_CHANNEL_ID
from discord import Colour, Embed
from discord.ext import commands
from discord.errors import HTTPException

from utils.formats import CustomEmbed
from libneko import FieldIsTooLong



LEVEL_COLORS = {
    logging.CRITICAL: Colour.red().value,
    logging.ERROR: Colour.red().value,
    logging.WARNING: Colour.gold().value,
    logging.INFO: Colour.blurple().value,
    logging.DEBUG: Colour.dark_grey().value
}


class DiscordHandler(logging.Handler):
    """
    A class implementing logging.Handler methods to send logs to a Discord channel.
    """
    def __init__(self, bot: commands.Bot, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self.client = bot
        self.log_channel = self.client.get_channel(LOGGING_CHANNEL_ID)

    @staticmethod
    def _level_to_color(level_number: int):
        return LEVEL_COLORS.get(level_number, Colour.orange().value)

    def emit(self, record):
        if not self.client.loop.is_running():
            # The event loop is not running (discord is not connected)
            return

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
            return print(err)

        if "discord_info" in record.__dict__:
            for field, value in record.__dict__["discord_info"].items():
                try:
                    e.add_field(name=field, value=value, inline=True)
                except FieldIsTooLong as err:
                    return print(err)

        if self.log_channel is None:
            self.log_channel = self.client.get_channel(LOGGING_CHANNEL_ID)

        # Create a task in the event loop to send the logging embed
        if self.log_channel is not None and hasattr(self.client, 'loop'):
            asyncio.ensure_future(self.client.loop.create_task(self.log_channel.send(embed=e)))
