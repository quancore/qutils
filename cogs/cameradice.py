import logging
import asyncio
import random
import typing
import itertools

from discord import Embed, TextChannel, VoiceChannel, VoiceState, Member
from discord.ext import commands
from utils.formats import CustomEmbed

from config import max_lost_member, ADMIN_ROLE_NAMES, start_game_delay, VALID_STATS_ROLES, short_delay, mid_delay

from utils import helpers
from libneko import pag

log = logging.getLogger('root')


class MemberRoll:

    def __init__(self, member: Member, text_ch: TextChannel, voice_ch: VoiceChannel,
                 roll_res: typing.Optional[int] = None):
        """
        Init method for an rolling event of a member in camdice game
        member: Member that roll the dice
        text_ch : Text channel of camdice game the member has been participated
        voice_ch : Voice channel of camdice game the member has been participated
        roll_res: Result of the rolling dice
        """
        self._member = member
        self._id = member.id
        self._tc = text_ch
        self._vc = voice_ch
        self._roll = roll_res
        # it will be true when the member completely finished rolling stage
        self._rolling_completed = False
        self._is_loser = False
        self._is_forbidden = False
        self._is_video_open = True

    def __repr__(self):
        member_text = f"{self._member.mention}({self._member.display_name}) "
        rolled_text = f"| Rolled-> {'Not yet' if self._roll is None else str(self._roll)} "
        lost_text = f"| Lost: {'No' if not self._is_loser else 'Yes'} "
        cam_text = f"| Cam open: {'No' if not self._is_video_open else 'Yes'}"
        if self._is_forbidden:
            return member_text
        else:
            member_text = member_text + rolled_text + lost_text
            if self._is_loser:
                member_text = member_text + cam_text

        return member_text.strip()

    def __eq__(self, other):
        """Overrides the default implementation"""
        if isinstance(other, MemberRoll):
            return self._id == other.id and self._tc == other.tc and self._vc == other.vc
        return False

    @property
    def tc(self):
        return self._tc

    @property
    def vc(self):
        return self._vc

    @property
    def member(self):
        return self._member

    @property
    def id(self):
        return self._id

    @property
    def roll(self):
        return self._roll

    @property
    def rolling_completed(self):
        return self._rolling_completed

    @rolling_completed.setter
    def rolling_completed(self, status: bool):
        self._rolling_completed = status

    @property
    def is_video_open(self):
        return self._is_video_open

    @is_video_open.setter
    def is_video_open(self, status: bool):
        self._is_video_open = status

    @property
    def is_loser(self):
        return self._is_loser

    @is_loser.setter
    def is_loser(self, status: bool):
        self._is_loser = status

    @property
    def is_forbidden(self):
        return self._is_forbidden

    @is_forbidden.setter
    def is_forbidden(self, status: bool):
        self._is_forbidden = status

    @roll.setter
    def roll(self, new_roll):
        if new_roll is None:
            self._roll = new_roll
        else:
            roll_int = helpers.representsInt(new_roll)
            if roll_int and 0 < roll_int <= 6:
                self._roll = new_roll

    def is_rolled(self):
        return False if self._roll is None else True


class _DiceGame:
    def __init__(self, text_ch: TextChannel, voice_ch: VoiceChannel,
                 member_rolls: typing.Dict[int, MemberRoll],
                 lead_member: Member, num_losers: int):
        """
        Init method for an camdice game object
        text_ch : Text channel of camdice game the member has been participated
        voice_ch : Voice channel of camdice game the member has been participated
        member_rolls: Dict storing initial member rolling objects
        lead_member: Member started this game
        num_losers: Number of players will be lost this game
        """
        self._tc = text_ch
        self._vc = voice_ch
        self._num_losers = num_losers
        # whether rolling phase of the game finished
        self._rolling_finished = False
        # whether game is finished
        self._game_finished = False
        # member_id : member roll
        self._member_rolls = member_rolls
        # member_id : member roll
        self._losers = {}
        # forbidden members (left the game or kicked by lead member), member_id : member roll
        self._forbidden_members = {}
        self._lead_member = lead_member

    def __repr__(self):
        main_text = f"➸Voice channel: 🔊{self._vc.name}\n ➸Text channel: {self._tc.mention}\n" \
                    f"➸Game initiator: {self._lead_member.mention}\n Rolling phase finished: {self._rolling_finished}\n" \
                    f"➸Game finished: {self._game_finished}\n Number of losers: {self._num_losers} " \
                    f"Current loser count: {len(self._losers)}\n"

        member_text = '\n'.join([f"{index}) {str(roll)}"
                                 for index, (_, roll) in enumerate(self._member_rolls.items(), start=1)])
        if member_text:
            main_text += f"**__Current participants__**\n {member_text}"

        forbidden_text = '\n'.join([f"{index}) {str(roll)}"
                                    for index, (_, roll) in enumerate(self._forbidden_members.items(), start=1)])
        if forbidden_text:
            main_text += f"**\n__Kicked or left members__**\n {forbidden_text}"

        return main_text

    def __eq__(self, other):
        """Overrides the default implementation"""
        if isinstance(other, _DiceGame):
            return self._tc == other.tc and self._vc == other.vc
        return False

    # *********** Getter and setters ********
    @property
    def tc(self):
        return self._tc

    @property
    def vc(self):
        return self._vc

    @property
    def rolling_finished(self):
        return self._rolling_finished

    @property
    def game_finished(self):
        return self._game_finished

    @property
    def losers(self):
        return self._losers

    @rolling_finished.setter
    def rolling_finished(self, new_state: bool):
        self._rolling_finished = new_state

    @property
    def rolls(self):
        return self._member_rolls

    @property
    def lead(self):
        return self._lead_member

    @property
    def num_losers(self):
        return self._num_losers

    @property
    def forbidden_members(self):
        return self._forbidden_members

# ****** utility methods ************
    def get_remaining_members(self):
        """Return not rolled members """
        if self._member_rolls is None:
            return None

        not_rolled_members = {m.member for _, m in self._member_rolls.items() if not m.is_rolled()}
        return not_rolled_members

    def remove_member(self, member_id: int):
        """ Remove a member from the game """
        self._member_rolls.pop(member_id, None)
        self._losers.pop(member_id, None)

        if not self._rolling_finished and (len(self._member_rolls) <= self._num_losers):
            self._game_finished = True
            raise ValueError(f"The active camdice game in 🔊{self.vc.name} has been finished"
                             f" because there are less or equal member participated "
                             f"the game than number of losers.")

        equal_group = self.update_game_state()

        return equal_group

    def is_loser(self, member_id: int):
        """ Check whether a member is loser in the game """
        return True if self._losers.get(member_id) else False

    def is_participated(self, member_id: int):
        """ Check whether a member in the game. it is not the same as is_rolled """
        return True if self._member_rolls.get(member_id) else False

    def is_rolled(self, member_id: int):
        """ Check whether a member in the game already rolled a dice """
        member = self._member_rolls.get(member_id)
        if member and member.is_rolled():
            return True

        return False

    def get_member_roll(self, member_id):
        """ Get member roll object by member id """
        return self._member_rolls.get(member_id)

    def update_game_state(self):
        not_rolled_members = {m.member for _, m in self._member_rolls.items() if not m.is_rolled()}
        equal_group = None
        if len(not_rolled_members) == 0 and not self._rolling_finished:
            print("rolling finished")
            # rolling maybe finished, determine losers
            self._rolling_finished = True
            equal_group = self._determine_losers()
            # if there is a tie, the rolling phase not finished
            if equal_group is not None:
                self._rolling_finished = False

        elif self._rolling_finished:
            # check all losers have cam up
            all_losers_finished = all({loser.is_video_open for _, loser in self._losers.items()})

            if all_losers_finished:
                self._game_finished = True

        return equal_group

    def set_member_roll(self, member: Member):
        """ Roll a dice for given member and set the roll result """
        memberroll_or_none = self._member_rolls.get(member.id)
        if memberroll_or_none is None:
            raise ValueError(f'{member.mention} have not participated active camdice game in 🔊{self._vc.name}')

        if memberroll_or_none.roll is not None:
            raise ValueError(f"{memberroll_or_none.member.mention} has already "
                             f"rolled **{memberroll_or_none.roll}** for the game in 🔊{self._vc.name}")

        roll_res = random.randint(1, 6)
        # roll_res = 6
        memberroll_or_none.roll = roll_res

        # update the game state
        equal_group = self.update_game_state()

        return roll_res, equal_group

    def add_member_roll(self, member: Member):
        """ Add a dice for given member """
        memberroll_or_none = self._member_rolls.get(member.id)
        if memberroll_or_none is not None:
            raise ValueError(f'{member.mention} have already participated the game in 🔊{self._vc.name} '
                             f'so no need to add.')

        if self._rolling_finished:
            raise ValueError(f'{member.mention} rolling phase already finished for '
                             f'the game in in 🔊{self._vc.name} so you cannot join the game.\n'
                             f'Please wait a bit until the game end.')

        self._member_rolls[member.id] = MemberRoll(member, self._tc, self._vc)

    def _determine_losers(self):
        """ Sort the rolled dice values and get n players with least values """
        # store members with equal dice values, which will be use re-roll the dice for these members
        equal_group = None
        if self._rolling_finished:
            # filter available members (members that rolling phase not completed)
            available_members = [m for m in self._member_rolls.values() if not m.rolling_completed]
            # segment dice values into groups for available members
            sorted_members = sorted(available_members, key=lambda x: x.roll)
            rolling_groups, losers = {k: list(g) for k, g in itertools.groupby(sorted_members, lambda x: x.roll)}, {}
            # rolling_groups, losers = {k: list(g) for k, g in itertools.groupby(available_members, lambda x: x.roll)}, {}
            # get the number of loser place remaining
            remaining_loser_cap = self._num_losers - len(self._losers)
            print("***********************************************")
            print(f"Rolling groups: {rolling_groups}")
            # print(f"Rolling groups: {rolling_groups}")
            print(f"Remaining loser count: {remaining_loser_cap}")
            loser_and_equals_found = False
            for roll_value, group in sorted(rolling_groups.items()):
                print(f"Roll val: {roll_value} group: {group}")
                if len(losers) == remaining_loser_cap:
                    print("All losers and equals found")
                    loser_and_equals_found = True

                # the members neither loser nor in equal group
                if loser_and_equals_found:
                    for non_loser in group:
                        non_loser.rolling_completed = True
                else:
                    if len(losers) + len(group) <= remaining_loser_cap:
                        _loser = {}
                        for loser_member in group:
                            loser_member.rolling_completed = True
                            loser_member.is_loser = True
                            loser_member.is_video_open = False
                            _loser[loser_member.id] = loser_member

                        print(f"Loser group added: {group}")
                        losers.update(_loser)
                    else:
                        # if the last loser group is more them one member,
                        # they need to roll the dice again (equal group)
                        if len(group) > 1:
                            for equal_member in group:
                                equal_member.roll = None
                                equal_member.rolling_completed = False
                            print(f"Equal group added: {group}")
                            equal_group = (roll_value, group)
                            loser_and_equals_found = True

            self._losers.update(losers)

        return equal_group

    def get_losers_text(self):
        """ Return loser list in string format """
        return "\n".join({f"{index}) {loser.member.mention}  Rolled: {loser.roll}" for index, (_, loser)
                          in enumerate(self._losers.items(), start=1)})

    def set_loser_cam_state(self, member: Member, state: bool):
        """ Set loser video cam state """
        loser = self._losers.get(member.id)
        if loser is None:
            return

        loser.is_video_open = state

        # check all losers have cam up
        all_losers_finished = all({loser.is_video_open for _, loser in self._losers.items()})

        if all_losers_finished:
            self._game_finished = True

    def add_forbidden(self, member: Member):
        """ Add a forbidden member (cannot join game voice channel) """
        memberroll_or_none = self._member_rolls.get(member.id)
        if memberroll_or_none is None:
            raise ValueError(f'{member.mention} not in camdice game on 🔊{self._vc.name}')

        memberroll_or_none.is_forbidden = True
        self._forbidden_members[member.id] = memberroll_or_none

    def is_forbidden(self, member_id: int):
        """ Check whether the player is forbidden """
        return True if self._forbidden_members.get(member_id) else False

    def is_video_open(self, member_id: int):
        """ Check whether a member has already open the video cam """
        member = self._member_rolls.get(member_id)
        if member and member.is_video_open is True:
            return True

        return False


class Camdice(commands.Cog):
    """
    Gambling cog called camdice. It is a rolling dice game and the losers will cam up.
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        # store voice_channel_id:text_channel_id for active games
        self.channel_list = {}
        # store current games in format text_channel_id:_DiceGame
        self.current_games = {}

# ********** Event listeners **********
    @commands.Cog.listener('on_voice_state_update')
    async def voice_state_update(self, member: Member, before: VoiceState, after: VoiceState):
        found_before_vc, found_after_vc = before.channel, after.channel
        # if the state update related with game voice channels, these text channel placeholders will
        # get non-None values
        found_before_tc, found_after_tc = None, None

        if found_before_vc is not None:
            found_before_tc_id = self.channel_list.get(found_before_vc.id)
            if found_before_tc_id is not None:
                found_before_tc = await helpers.get_channel_by_id(self.bot, found_before_vc.guild, found_before_tc_id)

        if found_after_vc is not None:
            found_after_vc_id = self.channel_list.get(found_after_vc.id)
            if found_after_vc_id is not None:
                found_after_tc = await helpers.get_channel_by_id(self.bot, found_after_vc.guild, found_after_vc_id)

        # if before or after channel is not one of the text channel the camdice game occurs
        # return
        if found_before_tc is None and found_after_tc is None:
            return

        # a member can jump from one game voice channel to other or he/she could change the voice state
        if found_before_tc is not None and found_after_tc is not None:
            previous_current_game = self.current_games[found_before_tc.id]
            after_current_game = self.current_games[found_after_tc.id]

            # cannot follow forbidden members
            if after_current_game.is_forbidden(member.id):
                return

            # in the same voice channel, just state changed
            if found_before_vc.id == found_after_vc.id:
                member_roll = after_current_game.get_member_roll(member.id)
                valid_cam_state = after.self_video and before.self_video != after.self_video
                if after_current_game.is_loser(member.id) and not member_roll.is_video_open and valid_cam_state:
                    after_current_game.set_loser_cam_state(member, after.self_video)
                    await found_after_tc.send(f"{member.mention} has been lost the camdice game and open the camera.\n "
                                              f"**WELL DONE TO FULFILL YOUR PROMISE**")
                    if after_current_game.game_finished:
                        # self.current_games.pop(found_after_tc.id, None)
                        # self.channel_list.pop(found_after_vc.id, None)
                        # return await found_after_tc.send(f"Active camdice game in 🔊{found_after_vc.name} has been finished.")
                        return await found_after_tc.send(f"Active camdice game in 🔊{found_after_vc.name} has been finished"
                                                         f" because all losers have opened camera. However, the channel will be locked"
                                                         f" until you run `close` command to finish game.")

                return

        # one of the member who connected one of game voice channel and then get disconnected
        if found_before_tc is not None:
            current_game = self.current_games[found_before_tc.id]
            # this member not in the game, so return
            if not current_game.is_participated(member.id):
                return

            # cannot follow forbidden members
            if current_game.is_forbidden(member.id):
                return

            if current_game.rolling_finished:
                # this member not one of the loser after rolling phase finished so no problem
                if not current_game.is_loser(member.id):
                    return

                return await found_before_tc.send(f"{member.mention} are the loser of camdice game "
                                                  f"but disconnected from 🔊{found_before_vc.name}.\n"
                                                  f"You need to open your webcam because you have **LOST**.\n"
                                                  f"**COME BACK AND OPEN YOUR CAM.**")

            # the member who already participated the game is left the game voice channel
            # and the rolling phase of the game not finished yet
            else:
                if current_game.is_rolled(member.id):
                    return await found_before_tc.send(f"{member.mention} have been participated the camdice by rolling "
                                                      f"a dice game but left 🔊{found_before_vc.name} "
                                                      f"before determining losers.\n"
                                                      f"**IT IS UNFAIR SO YOU NEED TO CONNECT BACK TO 🔊{found_before_vc.name}**")

        # one of the member who coming outside of game voice channels and then get connected to one of them
        if found_after_tc is not None:
            current_game = self.current_games[found_after_tc.id]

            # check first the member is forbidden
            if current_game.is_forbidden(member.id):
                try:
                    await member.move_to(None, reason="TRYING TO PARTICIPATE FORBIDDEN MEMBER FROM CAMDICE GAME")
                except:
                    pass
                else:
                    return await found_after_tc.send(f"{member.mention} is kicked or left active "
                                                     f"camdice game in 🔊{found_after_vc.name}.\n"
                                                     f"Please wait until the game finished.")

            # this member not in the game and trying to participate the game voice channel
            if not current_game.is_rolled(member.id):
                # first check whether the rolling phase of active game has been finished, if not, allow to participate
                if not current_game.rolling_finished:
                    try:
                        current_game.add_member_roll(member)
                    except ValueError as err:
                        return await found_after_tc.send(str(err))
                    else:
                        return await found_after_tc.send(f"{member.mention} has been participated "
                                                         f"active camdice game in 🔊{found_after_vc.name}.\n"
                                                         f"Please roll a dice and **do not forget if you roll the dice,"
                                                         f"YOU CANNOT LEAVE THE GAME**")
                else:
                    try:
                        await member.move_to(None, reason="TRYING TO PARTICIPATE CAMDICE GAME")
                    except:
                        pass
                    else:
                        return await found_after_tc.send(f"{member.mention}, there is a active camdice "
                                                         f"game in 🔊{found_after_vc.name}.\n"
                                                         f"You did not participate the game "
                                                         f"and cannot see the losers; so please wait "
                                                         f"until the game has been finished to connect this voice channel")

            # member in the game and come back to game voice channel
            else:
                if current_game.is_loser(member.id) and not current_game.get_member_roll(member.id).is_video_open:
                    return await found_after_tc.send(f"{member.mention} Welcome back 🔊{found_after_vc.name}.\n"
                                                     f"You have been lost the camdice game and still "
                                                     f"do not open the camera.\n"
                                                     f"**PLEASE FULFIL YOUR PROMISE!!!**")

    # ********** Commands ****************
    @commands.group(name='camdice', help='Command group for dice camera',
                    usage='This is not a command but a command group.', hidden=True,
                    aliases=['cd'])
    @commands.has_any_role(*VALID_STATS_ROLES)
    async def camdice(self, ctx):
        pass

    @camdice.command(name='start', help='Start a camdice game',
                     usage=f'<delay>\n\n'
                           f'delay: int, Optional, default: {start_game_delay} - '
                           f'Number of seconds to wait to read instructions and leave the game before start\n'
                           f'Ex: !cd s 5\n\n',
                     aliases=['s'])
    async def start(self, ctx, delay: int = start_game_delay):
        sent_messages = [ctx.message]
        try:
            voice_state = ctx.author.voice
            if voice_state is None:
                return await ctx.send('You need to connect a voice channel in order to start camdice.',
                                      delete_after=short_delay)

            selected_vc = voice_state.channel

            if self.channel_list.get(selected_vc.id) is not None:
                return await ctx.send(f'There is already an active game in  🔊{selected_vc.name}', delete_after=short_delay)

            if selected_vc.voice_states is False:
                return await ctx.send('Voice states are not allowed on this voice channel, '
                                      'please contact the admin.', delete_after=short_delay)

            if not (isinstance(ctx.channel, TextChannel) and
                    ctx.channel.permissions_for(ctx.author).read_messages and
                    ctx.channel.permissions_for(ctx.author).send_messages):
                return await ctx.send('The text channel you run the command is not suitable for camdice game.', delete_after=short_delay)

            selected_tc = ctx.channel
            current_connected_m_text = "\n".join([m.mention for m in selected_vc.members])
            info = f"**Welcome to camdice game**. This command starts a gambling competition, " \
                   f"which last n member will lose so they will open the camera as a punishment:DDD\n" \
                   f"__**The game has two phase:**__\n" \
                   f"1) All members connected to 🔊{selected_vc.name} will roll a dice.\n" \
                   f"2) When all participants finished the rolling dice phase, losers will be announced and" \
                   f" the game will remain active **until all losers open their webcam**\n" \
                   f"After rolling phase finished and until all losers cam up, no one **will participate" \
                   f" to 🔊{selected_vc.name}**\n" \
                   f"**__Initial participants__**\n" \
                   f"{current_connected_m_text}\n" \
                   f"**The members above have {delay} seconds to left 🔊{selected_vc.name} " \
                   f"if they do not want to join the game.**\n" \
                   f"**The participated members can also leave the game BEFORE ROLLING A DICE using `cd leave`**\n\n"

            msg = await ctx.channel.send(info)
            sent_messages.append(msg)
            # wait to read instr. and leave the game
            await asyncio.sleep(delay)

            max_allowed_member = min(max_lost_member, len(selected_vc.members)-1)
            question = f"Type a number for how many members will lose and open the camera when rolling phase finishes\n" \
                       f"Minimum: 1 | Maximum: {max_allowed_member}\n" \
                       f"Type 'c' to cancel"

            def check_msg(m):
                if m.author.id != ctx.author.id:
                    return False
                if m.channel != ctx.channel:
                    return False

                return m.content == 'c' or (0 < helpers.representsInt(m.content) <= max_allowed_member)

            msg = await ctx.channel.send(question)
            sent_messages.append(msg)
            try:
                member_count = await self.bot.wait_for("message", check=check_msg, timeout=60)
                sent_messages.append(member_count)
            except asyncio.TimeoutError:
                return await ctx.send('Please type in 60 seconds next time.')

            if member_count.content == 'c':
                return await ctx.send('Command has been cancelled.')

            num_losers = int(member_count.content)
            # initialize initial rolling object for each member
            member_roll_dict = {m.id: MemberRoll(m, selected_tc, selected_vc) for m in selected_vc.members}
            if len(member_roll_dict) == 0:
                return await ctx.send(f'There is no member in 🔊{selected_vc.name} you selected for game voice channel.', delete_after=short_delay)

            if len(member_roll_dict) <= num_losers:
                return await ctx.send(f'The loser number you entered is equal or higher than the member currently'
                                      f' connected in 🔊{selected_vc.name} you selected for game voice channel.',
                                      delete_after=short_delay)

            current_game = _DiceGame(selected_tc, selected_vc, member_roll_dict, ctx.author, num_losers)
            self.current_games[selected_tc.id] = current_game
            self.channel_list[selected_vc.id] = selected_tc.id
            return await ctx.send(f"**Game has been started.**\n {str(current_game)}")
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=0)

    @camdice.command(name='state', help='Get the state of current game', aliases=['st'])
    @commands.guild_only()
    async def state(self, ctx):
        sent_messages = [ctx.message]
        try:
            text_channel = ctx.channel
            current_game = self.current_games.get(text_channel.id)
            if current_game is None:
                return await ctx.send("There is no active camdice game in this channel.", delete_after=short_delay)

            return await ctx.send(str(current_game), delete_after=mid_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)

    @camdice.command(name='fetch', help='Fetch all active camdice games', aliases=['f'])
    @commands.guild_only()
    @commands.has_any_role(*ADMIN_ROLE_NAMES)
    async def fetch(self, ctx):
        sent_messages = [ctx.message]
        try:
            if len(self.current_games) == 0:
                return ctx.send('No active games at that moment.', delete_after=mid_delay)
            for _, game in self.current_games.items():
                await ctx.send(str(game)+"\n-------------------", delete_after=mid_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=mid_delay)

    @camdice.command(name='roll', help='Roll the dice', aliases=['r'])
    @commands.guild_only()
    async def roll(self, ctx):
        sent_messages = [ctx.message]
        try:
            author = ctx.author
            channel_id = ctx.channel.id
            current_game = self.current_games.get(channel_id)

            if current_game is None:
                return await ctx.send(f'There is no game setup for {ctx.channel.mention} to roll the dice.\n'
                                      f'To start a new game, please use `start` command.', delete_after=short_delay)

            if current_game.is_forbidden(author.id):
                return await ctx.send(f'{author.mention} has been left or kicked the game in 🔊{current_game.vc.name}.\n'
                                      f'You cannot participate this game and wait to finish it.', delete_after=short_delay)

            if current_game.rolling_finished:
                return await ctx.send('This game has been closed for dice rolling, '
                                      'please wait for the process of opening webcams', delete_after=short_delay)
            try:
                roll_res, equal_group = current_game.set_member_roll(ctx.author)
            except ValueError as err:
                return await ctx.send(str(err), delete_after=short_delay)

            not_rolled_members = '\n'.join({m.mention for m in current_game.get_remaining_members()})
            losers_text = current_game.get_losers_text()
            if equal_group is None:
                await ctx.send(f"{author.mention} rolled a **{roll_res}**, and it is saved.\n"
                               f"__**Not rolled members**__\n"
                               f"{not_rolled_members if not_rolled_members else 'All members rolled'}",
                               delete_after=mid_delay)
            else:
                roll_value, group = equal_group
                await ctx.send(f"{author.mention} rolled a **{roll_res}**, and it is saved.\n"
                               f"__**There is a tie between those members rolled {roll_value}**__\n"
                               f"{not_rolled_members if not_rolled_members else 'No member tied'}\n"
                               f"**__Absolute losers__**\n"
                               f"{losers_text if losers_text else 'No absolute loser yet'}\n"
                               f"Tied members will roll the dice again", delete_after=mid_delay)

            # rolling phase of game finished
            if current_game.rolling_finished:
                await ctx.send(f"** Rolling dice phase of the game in 🔊{current_game.vc.name} has finished.**\n"
                               f"**__Here are losers__**\n"
                               f"{losers_text}\n"
                               f"The related voice channel will be **LOCKED** until **all losers listed** cam up.\n"
                               f"If any losers has left the voice channel to flee on open the cam and do not come back,"
                               f"you can use **close** command to end this game\n"
                               f"**close** command can only be used by **the member that started the game.**\n"
                               f"** Ready to CAM UP FOR LOSERS, HAHAHAHAHAHA **", delete_after=mid_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)

    @camdice.command(name='close', help='Close a camdice game', aliases=['c'])
    @commands.guild_only()
    async def close(self, ctx):
        sent_messages = [ctx.message]
        try:
            author = ctx.author
            channel_id = ctx.channel.id
            current_game = self.current_games.get(channel_id)

            if current_game is None:
                return await ctx.send(f'There is no game setup for {ctx.channel.mention} to close a game.', delete_after=short_delay)

            if author != current_game.lead:
                return await ctx.send(f'The game in 🔊{current_game.vc.name} has been started by {current_game.lead.mention} '
                                      f'so only this member **can end the game.**', delete_after=short_delay)

            if current_game.is_loser(author.id) and not current_game.is_video_open(author.id):
                return await ctx.send(f'{author.mention} has lost game in 🔊{current_game.vc.name}'
                                      f' and trying to end the game without opening video cam.\n'
                                      f'You can close the game after opening your webcam.', delete_after=short_delay)

            confirm = await ctx.prompt("Are you sure to end this game?", author_id=current_game.lead.id,
                                       timeout=short_delay, delete_after=True)
            if confirm:
                self.current_games.pop(channel_id, None)
                self.channel_list.pop(current_game.vc.id, None)
                return await ctx.send(f"The active camdice game in 🔊{current_game.vc.name} has been finished.")
            elif confirm is None:
                await ctx.send("Operation has been cancelled.", delete_after=short_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)

    @camdice.command(name='force_close', help='Close a game forcefully.', aliases=['f_c'])
    @commands.guild_only()
    @commands.has_any_role(*ADMIN_ROLE_NAMES)
    async def force_close(self, ctx):
        sent_messages = [ctx.message]
        try:
            channel_id = ctx.channel.id
            current_game = self.current_games.get(channel_id)

            if current_game is None:
                return await ctx.send(f'There is no game setup for {ctx.channel.mention} to close a game.', delete_after=short_delay)

            confirm = await ctx.prompt("Are you sure to end this game?", author_id=current_game.lead.id,
                                       timeout=short_delay, delete_after=True)
            if confirm:
                self.current_games.pop(channel_id, None)
                self.channel_list.pop(current_game.vc.id, None)
                return await ctx.send(f"The active camdice game in 🔊{current_game.vc.name} has been finished.")
            elif confirm is None:
                await ctx.send("Operation has been cancelled.", delete_after=short_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)

    @camdice.command(name='leave', help='Leave a camdice game you participated.', aliases=['l'])
    @commands.guild_only()
    async def leave(self, ctx):
        sent_messages = [ctx.message]
        try:
            author = ctx.author
            channel_id = ctx.channel.id
            current_game = self.current_games.get(channel_id)

            if current_game is None:
                return await ctx.send(f'There is no game setup for {ctx.channel.mention} to leave.', delete_after=short_delay)

            if not current_game.is_participated(author.id):
                return await ctx.send(f'{author.mention} have not participated active '
                                      f'camdice game in 🔊{current_game.vc.name}.', delete_after=60)

            if author == current_game.lead:
                return await ctx.send(f'{author.mention} is the leader of the game in 🔊{current_game.vc.name}, '
                                      f'so you cannot leave the game.\n You can close the game if you want.',
                                      delete_after=short_delay)

            member_roll = current_game.get_member_roll(author.id)
            if member_roll.is_rolled():
                if current_game.rolling_finished:
                    if member_roll.is_loser:
                        return await ctx.send(f'**{member_roll.member.mention} CANNOT LEAVE THE GAME IN 🔊{current_game.vc.name} BECAUSE '
                                              f'YOU ALREADY ROLLED A DICE: {str(member_roll.roll)}** AND LOST THE GAME.', delete_after=short_delay)
                else:
                    return await ctx.send(f'**{member_roll.member.mention} CANNOT LEAVE THE GAME IN 🔊{current_game.vc.name} BECAUSE '
                                          f'YOU ALREADY ROLLED A DICE: {str(member_roll.roll)}** AND ROLLING PHASE NOT ENDED.',
                                          delete_after=short_delay)

            confirm = await ctx.prompt(f"Are you sure to left the game? "
                                       f"You cannot join 🔊{current_game.vc.name} until game finishes.",
                                       author_id=current_game.lead.id,
                                       timeout=60, delete_after=True)
            if confirm:

                try:
                    current_game.add_forbidden(author)
                    equal_group = current_game.remove_member(author.id)
                except ValueError as err:
                    return await ctx.send(str(err), delete_after=short_delay)
                else:
                    not_rolled_members = '\n'.join({m.mention for m in current_game.get_remaining_members()})
                    losers_text = current_game.get_losers_text()
                    if equal_group is not None:
                        roll_value, group = equal_group
                        return await ctx.send(f"** Rolling dice phase of the game in 🔊{current_game.vc.name} has finished.**\n"
                                              f"__**There is a tie between those members rolled {roll_value}**__\n"
                                              f"{not_rolled_members if not_rolled_members else 'No member tied'}\n"
                                              f"**__Absolute losers__**\n"
                                              f"{losers_text if losers_text else 'No absolute loser yet'}\n"
                                              f"Tied members will roll the dice again", delete_after=mid_delay)
                    else:
                        # rolling phase of game finished
                        if not current_game.game_finished and current_game.rolling_finished:
                            await ctx.send(f"** Rolling dice phase of the game in 🔊{current_game.vc.name} has finished.**\n"
                                           f"**__Here are losers__**\n"
                                           f"{losers_text}\n"
                                           f"The related voice channel will be **LOCKED** until **all losers listed** cam up.\n"
                                           f"If any losers has left the voice channel to flee on open the cam and do not come back,"
                                           f"you can use **close** command to end this game\n"
                                           f"**close** command can only be used by **the member that started the game.**\n"
                                           f"** Ready to CAM UP FOR LOSERS, HAHAHAHAHAHA **", delete_after=mid_delay)
                finally:
                    try:
                        await author.move_to(None, reason="TRYING TO PARTICIPATE CAMDICE GAME")
                    except:
                        pass
                    else:
                        return await ctx.send(f"{author.mention} have left the game.", delete_after=short_delay)

                    if current_game.game_finished:
                        self.current_games.pop(channel_id, None)
                        self.channel_list.pop(current_game.vc.id, None)
                        return await ctx.send(f"Game has been finished.", delete_after=short_delay)

            elif confirm is None:
                await ctx.send("Operation has been cancelled.", delete_after=short_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)

    @camdice.command(name='kick', help='Kick a member from active game', aliases=['k'])
    @commands.guild_only()
    async def kick(self, ctx, kick_member: Member):
        sent_messages = [ctx.message]
        try:
            author = ctx.author
            channel_id = ctx.channel.id
            current_game = self.current_games.get(channel_id)

            if current_game is None:
                return await ctx.send(f'There is no game setup for {ctx.channel.mention} to kick.', delete_after=short_delay)

            if not current_game.is_participated(kick_member.id):
                return await ctx.send(f'{kick_member.mention} have not participated active '
                                      f'camdice game in 🔊{current_game.vc.name}.', delete_after=short_delay)

            if author != current_game.lead:
                return await ctx.send(f'The game in 🔊{current_game.vc.name} has been started by {current_game.lead.mention} '
                                      f'so only this member **can kick a participant from the game.**', delete_after=short_delay)

            if author == kick_member:
                return await ctx.send(f'{author.mention} cannot kick yourself.\n'
                                      f'You can leave the game by `leave` comment.', delete_after=short_delay)

            if current_game.is_loser(author.id) and not current_game.is_video_open(author.id):
                return await ctx.send(f'{author.mention} has lost the game in 🔊{current_game.vc.name}'
                                      f' and trying to kick another member which is not valid.\n'
                                      f'You can kick a member after opening your webcam as promised.', delete_after=short_delay)

            if current_game.rolling_finished and not current_game.is_loser(kick_member.id):
                return await ctx.send(f'{kick_member.mention} has won the game in 🔊{current_game.vc.name}'
                                      f' and you trying to kick this member.\n'
                                      f'This member earned the right to see all losers.', delete_after=short_delay)

            confirm = await ctx.prompt(f"Are you sure to kick {kick_member.mention}? "
                                       f"The member cannot join 🔊{current_game.vc.name} until game finishes.",
                                       author_id=current_game.lead.id,
                                       timeout=60, delete_after=True)
            if confirm:
                try:
                    current_game.add_forbidden(kick_member)
                    equal_group = current_game.remove_member(kick_member.id)
                except ValueError as err:
                    return await ctx.send(str(err), delete_after=short_delay)
                else:
                    not_rolled_members = '\n'.join({m.mention for m in current_game.get_remaining_members()})
                    losers_text = current_game.get_losers_text()
                    if equal_group is not None:
                        roll_value, group = equal_group
                        return await ctx.send(f"** Rolling dice phase of the game in 🔊{current_game.vc.name} has finished.**\n"
                                              f"__**There is a tie between those members rolled {roll_value}**__\n"
                                              f"{not_rolled_members if not_rolled_members else 'No member tied'}\n"
                                              f"**__Absolute losers__**\n"
                                              f"{losers_text if losers_text else 'No absolute loser yet'}\n"
                                              f"Tied members will roll the dice again", delete_after=mid_delay)
                    else:
                        # rolling phase of game finished but not game finished
                        if not current_game.game_finished and current_game.rolling_finished:
                            await ctx.send(f"** Rolling dice phase of the game in 🔊{current_game.vc.name} has finished.**\n"
                                           f"**__Here are losers__**\n"
                                           f"{losers_text}\n"
                                           f"The related voice channel will be **LOCKED** until **all losers listed** cam up.\n"
                                           f"If any losers has left the voice channel to flee on open the cam and do not come back,"
                                           f"you can use **close** command to end this game\n"
                                           f"**close** command can only be used by **the member that started the game.**\n"
                                           f"** Ready to CAM UP FOR LOSERS, HAHAHAHAHAHA **", delete_after=mid_delay)
                finally:
                    # disconnect the member from channel
                    try:
                        await kick_member.move_to(None, reason="TRYING TO PARTICIPATE CAMDICE GAME")
                    except Exception as err:
                        print(err)
                    else:
                        await ctx.send(f"{kick_member.mention} have left the game.", delete_after=short_delay)

                    if current_game.game_finished:
                        self.current_games.pop(channel_id, None)
                        self.channel_list.pop(current_game.vc.id, None)
                        return await ctx.send(f"Game has been finished.", delete_after=short_delay)

            elif confirm is None:
                await ctx.send("Operation has been cancelled.", delete_after=short_delay)

        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)


def setup(bot):
    bot.add_cog(Camdice(bot))






