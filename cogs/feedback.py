import random
import string
import asyncio
import asyncpg
import hashlib
import json
import textwrap
import datetime

from PIL import Image
from io import BytesIO

# this just allows for nice function annotation, and stops my IDE from complaining.
# from typing import Union

from discord.ext import commands
from discord.errors import NotFound
import typing
from discord import File, TextChannel, Guild, InvalidArgument, Forbidden, HTTPException, RawMessageDeleteEvent, RawBulkMessageDeleteEvent

import logging
from config import ADMIN_CHANNEL_ID, FEEDBACK_CHANNEL_ID, GUILD_ID, \
    message_timeout, warn_limit, command_cooldown, short_delay, mid_delay, long_delay, TIER5
from utils import db, helpers
from utils.formats import CustomEmbed
from libneko import pag

log = logging.getLogger('root')

class Feedback(commands.Cog):

    def __init__(self, bot):
        self.bot = bot
        self.currently_feedbacking = set()

    @commands.command(name='feedback', help='Provide a feedback',
                      usage='Type the command and follow the dialogs',
                      aliases=['fb'])
    @commands.dm_only()
    async def feedback(self, ctx):
        await self.bot.wait_until_ready()

        author = ctx.author
        channel = ctx.message.channel
        # Handle bots (me lol)
        if author.bot:
            return
        if author.id in self.currently_feedbacking:
            return await ctx.send("You are already providing feedback")

        self.currently_feedbacking.add(author.id)
        guilds = [guild for guild in self.bot.guilds]
        # filter guilds to keep only guild the user in
        guilds = [guild for guild in guilds if await helpers.get_member_by_id(guild, author.id) is not None]
        if len(guilds) == 0:
            self.currently_feedbacking.remove(author.id)
            return await ctx.send('There is no server currently set for feedback.\n'
                                  'Please contact with moderator or owner.')

        guild_dict = {index + 1: guild for index, guild in enumerate(guilds)}
        guild_text = '\n'.join([f'**{index}) {guild.name}**' for index, guild in guild_dict.items()])
        question = f"Which server you want to create a feedback? " \
                   f"Please choose the number or press **c** cancel it\n" \
                   f"**__Servers__**\n" \
                   f"{guild_text}"

        try:
            guild, _ = await helpers.get_multichoice_answer(self.bot, ctx, guild_dict, question)
        except asyncio.TimeoutError:
            self.currently_feedbacking.remove(author.id)
            return await channel.send("The timer for you to provide the choice is timeout. Please "
                                      "give your feedback again to be able to provide another.")
        except commands.UserInputError as err:
            self.currently_feedbacking.remove(author.id)
            raise err

        if guild is None:
            self.currently_feedbacking.remove(author.id)
            return await ctx.send('Command has been cancelled.')

        # Get feedback message
        def check_message(m):
            if m.author.id != author.id:
                return False
            if m.channel != ctx.channel:
                return False

            return True

        await channel.send(f"What is your feedback message? "
                           f"Please write only one message and sent it.\n"
                           f"**The feedback first present to moderator approval then send to feedback"
                           f"channel. If rejected, you will receive an answer why it is rejected.**\n"
                           f"**PLEASE NOTE THAT YOU CANNOT DELETE YOUR FEEDBACK AFTER SUBMIT.**\n"
                           f"You can type 'c' to cancel.\n"
                           f"You have **{long_delay} seconds** to complete.")
        try:
            feedback_msg = await self.bot.wait_for("message",
                                                    check=check_message,
                                                    timeout=long_delay)
        except asyncio.TimeoutError:
            self.currently_feedbacking.remove(author.id)
            return await channel.send("The timer for you to give a server id has timed out. Please "
                                      "give your feedback again to be able to provide another.")

        if feedback_msg.content == 'c':
            self.currently_feedbacking.remove(author.id)
            return await ctx.send('Operation has been cancelled.')

        embed_dict = {"title": "A feedback", "description": feedback_msg.content}
        confirm = await ctx.prompt(f'Do you want to add **your identity** to feedback?', timeout=short_delay,
                                   author_id=ctx.author.id)
        if confirm:
            e = CustomEmbed.from_dict(embed_dict, avatar_url=self.bot.user.avatar_url, author_name=author.name)
        elif confirm is False:
            e = CustomEmbed.from_dict(embed_dict, avatar_url=self.bot.user.avatar_url)
        else:
            self.currently_feedbacking.remove(author.id)
            return ctx.send("Prompt has been timed out. Please try again.")

        administrator_channel = await helpers.get_channel_by_id(self.bot, guild, ADMIN_CHANNEL_ID)
        if administrator_channel:
            q = "A feedback has been received, do you want to publish this feedback?\n" \
                "If you decide not to publish, you will provide an explanation to " \
                "the member sent this feedback on the next message."
            response, msg = await helpers.prompt(self.bot, administrator_channel, q,
                                                 timeout=None, delete_after=False, embed=e)

            if response is True:
                feedback_channel = await helpers.get_channel_by_id(self.bot, guild, FEEDBACK_CHANNEL_ID)
                if feedback_channel:
                    await feedback_channel.send(embed=e)

                try:
                    response_text = f"Your feedback has been approved and it should be published in {feedback_channel.mention}"
                    await author.send(response_text, embed=e)
                except:
                    self.currently_feedbacking.remove(author.id)

            elif response is False:
                rejected_person = msg.member
                message_mention = helpers.prepare_message_mention(guild.id, administrator_channel.id, msg.message_id)

                # Get rejection feedback
                def check_message(m):
                    if m.author.id != rejected_person.id:
                        return False
                    if m.channel.id != msg.channel_id:
                        return False
                    return True

                await administrator_channel.send(f"{rejected_person.mention}, You have been rejected following message:\n"
                                                 f"<{message_mention}>\n"
                                                 f"Please provide an explanation why you have rejected this feedback.\n"
                                                 f"**Remember that it is important to provide an explanation why you "
                                                 f"rejected for the member provided this feedback.**\n"
                                                 f"You have **{long_delay} seconds** to complete.")
                try:
                    explanation = await self.bot.wait_for("message",
                                                          check=check_message,
                                                          timeout=long_delay)
                except asyncio.TimeoutError:
                    self.currently_feedbacking.remove(author.id)
                    await author.send("The moderator has been rejected your feedback "
                                      "request but could not provide an explanation.\n"
                                      "This could be a technical fault or "
                                      "the moderator was very busy. Please submit your "
                                      "feedback if you feel unsatisfied.", embed=e)
                    return await channel.send(f"{rejected_person.mention}, You could not provide an "
                                              f"rejection explanation for the related member on time.\n"
                                              f"Please do it better to provide an explanation on time for the next time.")

                try:
                    response_text = "You have been sent the feedback below and " \
                                    "**your feedback request has been rejected:(**.\n" \
                                    "Here is the response from a moderator:\n"
                    await author.send(f"{response_text}`{explanation.content}`", embed=e)
                except:
                    self.currently_feedbacking.remove(author.id)

            else:
                self.currently_feedbacking.remove(author.id)
                return ctx.send("An error occurred during processing the feedback. "
                                "Please try again later or contact with bot developer.")

            self.currently_feedbacking.remove(author.id)

        else:
            self.currently_feedbacking.remove(author.id)
            return ctx.send("An error occurred during sending feedback.")


def setup(bot):
    bot.add_cog(Feedback(bot))
