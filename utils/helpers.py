import datetime
from typing import Optional, Union, Callable, Iterable
import asyncio
import typing
import functools


from discord import abc
from discord import Guild, Role, Client, NotFound, Forbidden,\
    HTTPException, InvalidData, Member, utils, TextChannel, DMChannel, Embed
from discord.ext import commands

from config import activity_min_day
from libneko import pag

# ******* Discord related ************
async def get_channel_by_id(client: Client, guild: Guild, channel_id: int) \
        -> Optional[Union[abc.GuildChannel, abc.PrivateChannel]]:
    """ Get a channel by id from a guild if exist else return None """
    channel = None
    if guild is not None:
        try:
            channel = guild.get_channel(channel_id) or await client.fetch_channel(channel_id)
        except (NotFound, Forbidden, InvalidData, HTTPException):
            pass

    return channel


async def get_channel_by_name(guild: Guild, channel_name: str, channel_type: str) \
        -> Optional[Union[abc.GuildChannel, abc.PrivateChannel]]:
    """ Get a channel by name and type from a guild if exist else return None """
    channel = None
    if guild is not None:
        channels = guild.channels
        channel = utils.find(lambda c: c.name == channel_name and str(c.type) == channel_type, channels)
        if channel is None:
            try:
                channels = await guild.fetch_channels()
            except (InvalidData, HTTPException):
                pass
            else:
                channel = utils.find(lambda c: c.name == channel_name and str(c.type) == channel_type, channels)

    return channel


async def get_role_by_name(guild: Guild, role_name: str) -> Role:
    """ Get a role by name and type from a guild if exist else return None """
    role = None
    if guild is not None:
        roles = guild.roles
        role = utils.get(roles, name=role_name)
        if role is None:
            try:
                roles = await guild.fetch_roles()
            except HTTPException:
                pass
            else:
                role = utils.get(roles, name=role_name)

    return role


async def get_member_by_id(guild: Guild, member_id: int) -> Optional[Member]:
    """ Get a member by id from a guild if exist else return None """
    member = None
    if guild is not None:
        try:
            member = guild.get_member(member_id) or await guild.fetch_member(member_id)
        except (HTTPException, Forbidden) as err:
            pass

    return member


async def get_guild_by_id(client: Client, guild_id: int) -> Optional[Guild]:
    """ Get or fetch a guild given in guild_id """
    guild = None
    try:
        guild = client.get_guild(guild_id) or await client.fetch_guild(guild_id)
    except (Forbidden, HTTPException):
        pass

    return guild


async def get_inactive_members(guild, included_roles: Iterable, activity_role, exceptions=None):
    """ Get inactive member ids """

    if exceptions is None:
        exceptions = []

    valid_members = []
    member_text = ''

    for member in guild.members:
        member_delta = datetime.datetime.utcnow() - member.joined_at
        is_active = is_included = False
        if member not in exceptions and member_delta.days >= activity_min_day:
            for role in member.roles:
                if role is activity_role:
                    is_active = True
                    break

                if role.name in included_roles:
                    is_included = True

            if not is_active and is_included:
                valid_members.append(member.id)
                member_text += (member.mention + '\n')

    return valid_members, member_text


# ******* Util functions ************
def prepare_message_mention(guild_id, channel_id, message_id):
    """ Build guild message mention """
    return f"https://discordapp.com/channels/{guild_id}/{channel_id}/{message_id}"


def representsInt(s):
    """ Try to cast given value to integer and return if possible else return -1"""
    if s is None:
        return -1

    try:
        s = int(s)
        return s
    except ValueError:
        return -1


async def get_multichoice_answer(client, ctx, choices: dict, question: str, timeout: int = 120,
                                 check: Optional[Callable[..., bool]] = None):
    """ Send a multi choice question, check the answer to get correct integer choice and return choice item or None"""
    def check_msg(m):
        if m.author.id != ctx.author.id:
            return False
        if m.channel != ctx.channel:
            return False

        return m.content == 'c' or (min_choice <= representsInt(m.content) <= max_choice)

    value_type = set(type(k) for k in choices.keys())
    if value_type != {int}:
        raise ValueError('The keys of choices must be integer.')

    max_choice = max(choices, key=int)
    min_choice = min(choices, key=int)
    if min_choice < 0:
        raise ValueError('Min value in choices dict could not be smaller than 0')

    question_msg = await ctx.channel.send(question)

    try:
        # await self.bot.loop.create_task(self.bot.wait_for('message', check=check, timeout=60))
        choice = await client.wait_for("message", check=(check_msg if check is None else check), timeout=timeout)
    except asyncio.TimeoutError as err:
        raise err
    except commands.UserInputError as err:
        raise err

    choice_int = representsInt(choice.content)
    # if the result of choice after casting to int is smaller than zero,
    # user has been provided c meaning to cancel the command
    return None if choice_int < 0 else choices[choice_int], (choice, question_msg)


async def cleanup_messages(channel: TextChannel, messages: Iterable[abc.Snowflake],
                           navigators: Optional[Iterable[pag.BaseNavigator]] = None, delete_after: int = 5):
    """ Bulk delete messages in the given iterator """

    if not isinstance(channel, TextChannel):
        raise ValueError('The channel type is not TextChannel')

    await asyncio.sleep(delete_after)

    # cleanup all sent messages after successful operation
    try:
        await channel.delete_messages(messages)
    except:
        pass

    # kill navigators
    if navigators:
        for nav in navigators:
            nav.kill()


async def prompt(bot: commands.Bot, channel: typing.Union[DMChannel, TextChannel], message: str, *,
                 timeout: typing.Optional[float] = 60.0, delete_after: bool = True,
                 author_id: typing.Optional[int] = None, embed: typing.Optional[Embed] = None):
    """An interactive reaction confirmation dialog.

    Parameters
    -----------
    bot: commands.Bot
        Discord.py Bot class
    channel: typing.Union[DMChannel, TextChannel]
        Channel to send the message.
    message: str
        The message to show along with the prompt.
    timeout: typing.Optional[float]
        How long to wait before returning.
    delete_after: bool
        Whether to delete the confirmation message after we're done.
    author_id: Optional[int]
        The member who should respond to the prompt. Defaults to the author of the
        Context's message.
    embed: Optional[Discord.embed]
        Optional Discord Embed message.

    Returns
    --------
    Optional[bool]
        ``True`` if explicit confirm,
        ``False`` if explicit deny,
        ``None`` if deny due to timeout
    """

    if channel.guild is not None and not channel.permissions_for(channel.guild.me).add_reactions:
        raise RuntimeError('Bot does not have Add Reactions permission.')

    fmt = f'{message}\n\nReact with \N{WHITE HEAVY CHECK MARK} to confirm or \N{CROSS MARK} to deny.'

    msg = await channel.send(fmt, embed=embed)

    confirm = None

    def check(payload):
        nonlocal confirm

        if payload.user_id == bot.user.id:
            return False
        if payload.message_id != msg.id:
            return False
        if author_id and payload.user_id != author_id:
            return False

        codepoint = str(payload.emoji)

        if codepoint == '\N{WHITE HEAVY CHECK MARK}':
            confirm = True
            return True
        elif codepoint == '\N{CROSS MARK}':
            confirm = False
            return True

        return False

    for emoji in ('\N{WHITE HEAVY CHECK MARK}', '\N{CROSS MARK}'):
        await msg.add_reaction(emoji)

    try:
        response = await bot.wait_for('raw_reaction_add', check=check, timeout=timeout)
    except asyncio.TimeoutError:
        confirm, response = None, None

    try:
        if delete_after:
            await msg.delete()
    finally:
        return confirm, response


# ********** Checkers ******************
def has_any_role(member_roles, *items):
    getter = functools.partial(utils.get, member_roles)
    if any(getter(id=item) is not None if isinstance(item, int) else getter(name=item) is not None for item in items):
        return True
    raise commands.MissingAnyRole(items)
