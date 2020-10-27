import random
from collections import defaultdict
import os
import asyncio


from discord.ext import commands

import logging
from config import ADMIN_CHANNEL_ID, mid_delay, short_delay, base_truthdare_dir
from utils import helpers
from utils.formats import CustomEmbed

log = logging.getLogger('root')


class TruthDare(commands.Cog):

    def __init__(self, bot):
        self.bot = bot

        self.truths = {}
        self.dares = {}
        # self.hyes = {}
        # self.wyrs= {}

        asyncio.ensure_future(self._read_guilds_data(),
                              loop=self.bot.loop)

    @staticmethod
    def _read_text_file(base_dir, file_name, ext):
        """ Read a text file line by line """
        file_path = os.path.join(base_dir, file_name + "." + ext)
        lines = None
        if os.path.isfile(file_path):
            with open(file_path) as f:
                lines = f.read().splitlines()

        return lines

    def _read_guild_data(self, guild_id):
        """ Read a guild data """
        base_folder_path = os.path.join(base_truthdare_dir, str(guild_id))
        if not os.path.isdir(base_folder_path):
            log.info(f"Folder not found for truth and dare: {base_folder_path}")
            return

        truth_list = self._read_text_file(base_folder_path, 'truth', 'txt')
        if truth_list is not None and len(truth_list) > 0:
            self.truths[guild_id] = truth_list

        dare_list = self._read_text_file(base_folder_path, 'dare', 'txt')
        if dare_list is not None and len(dare_list) > 0:
            self.dares[guild_id] = dare_list

        # hye_list = self._read_text_file(base_folder_path, 'hye', 'txt')
        # if hye_list is not None and len(hye_list) > 0:
        #     self.hyes[guild_id] = hye_list
        #
        # wyr_list = self._read_text_file(base_folder_path, 'wyr', 'txt')
        # if wyr_list is not None and len(wyr_list) > 0:
        #     self.wyrs[guild_id] = truth_list

    async def _read_guilds_data(self):
        """ Read guilds data """
        await self.bot.wait_until_ready()

        guilds = self.bot.guilds
        loop = self.bot.loop
        futures = [asyncio.ensure_future(loop.run_in_executor(None, self._read_guild_data, guild.id)) for guild in guilds]
        await asyncio.gather(*futures)

    @commands.command(name='turn', help='Turn the bottle',
                      usage='Type the command and follow the dialogs')
    @commands.guild_only()
    async def turn(self, ctx):
        voice_state = ctx.author.voice
        if voice_state is None:
            return await ctx.send('You need to connect a voice channel in order to turn the bottle.',
                                  delete_after=short_delay)
        selected_vc = voice_state.channel
        if selected_vc.voice_states is False:
            return await ctx.send(f'Voice states are not allowed on 🔊{selected_vc.name}, '
                                  f'please contact the admin.', delete_after=short_delay)

        channel_members = selected_vc.members
        if len(channel_members) < 2:
            return await ctx.send(f'There should be at least 2 members connected to 🔊{selected_vc.name}'
                                  f'to turn the bottle', delete_after=short_delay)
        questioner = channel_members.pop(random.randrange(len(channel_members)))
        answerer = channel_members.pop(random.randrange(len(channel_members)))

        return await ctx.send(f"Selected pair of members:\n"
                              f" **{questioner.mention} (questioner) -> {answerer.mention} (answerer)**")

    @commands.command(name='truth', help='Give a truth question',
                      usage='Type the command and follow the dialogs')
    @commands.guild_only()
    async def truth(self, ctx):
        truth_q_for_guild = self.truths.get(ctx.guild.id)
        if truth_q_for_guild is None:
            return await ctx.send("There is no truth question set for this server, "
                                  "please contact with server moderators.", delete_after=short_delay)

        random_question = random.choice(truth_q_for_guild)
        if random_question:
            return await ctx.send(f"Here is the truth question: \n"
                                  f"**{random_question}**", delete_after=mid_delay)
        else:
            return await ctx.send("An error occurred during getting truth question.",
                                  delete_after=short_delay)

    @commands.command(name='dare', help='Give a dare question',
                      usage='Type the command and follow the dialogs')
    @commands.guild_only()
    async def dare(self, ctx):
        dare_q_for_guild = self.dares.get(ctx.guild.id)
        if dare_q_for_guild is None:
            return await ctx.send("There is no dare question set for this server, "
                                  "please contact with server moderators.", delete_after=short_delay)

        random_question = random.choice(dare_q_for_guild)
        if random_question:
            return await ctx.send(f"Here is the dare question: \n"
                                  f"**{random_question}**", delete_after=mid_delay)
        else:
            return await ctx.send("An error occurred during getting dare question.",
                                  delete_after=short_delay)

    # @commands.command(name='hye', help='Give a have you ever question',
    #                   usage='Type the command and follow the dialogs')
    # @commands.guild_only()
    # async def hye(self, ctx):
    #     hye_q_for_guild = self.hyes.get(ctx.guild.id)
    #     if hye_q_for_guild is None:
    #         return await ctx.send("There is no hye question set for this server, "
    #                               "please contact with server moderators.", delete_after=short_delay)
    #
    #     random_question = random.choice(hye_q_for_guild)
    #     if random_question:
    #         return await ctx.send(f"Here is the hye question: \n"
    #                               f"**{random_question}**", delete_after=mid_delay)
    #     else:
    #         return await ctx.send("An error occurred during getting hye question.",
    #                               delete_after=short_delay)
    #
    # @commands.command(name='wyr', help='Give a would you rather question',
    #                   usage='Type the command and follow the dialogs')
    # @commands.guild_only()
    # async def wyr(self, ctx):
    #     wyr_q_for_guild = self.wyrs.get(ctx.guild.id)
    #     if wyr_q_for_guild is None:
    #         return await ctx.send("There is no wyr question set for this server, "
    #                               "please contact with server moderators.", delete_after=short_delay)
    #
    #     random_question = random.choice(wyr_q_for_guild)
    #     if random_question:
    #         return await ctx.send(f"Here is the wyr question: \n"
    #                               f"**{random_question}**", delete_after=mid_delay)
    #     else:
    #         return await ctx.send("An error occurred during getting wyr question.",
    #                               delete_after=short_delay)


def setup(bot):
    bot.add_cog(TruthDare(bot))