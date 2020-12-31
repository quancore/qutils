import discord
import functools
from discord.ext import commands
from utils.config import bot_config


def has_any_config_role(cog_setting_name: str):
    """ Check whether command invoker has a role indicated in a cog setting related to roles """
    def predicate(ctx):
        if not isinstance(ctx.channel, discord.abc.GuildChannel):
            raise commands.NoPrivateMessage()

        guild_settings = bot_config.get_guild_by_id(ctx.guild.id)
        if guild_settings is not None:
            roles = guild_settings.find_cog_setting(cog_setting_name)
            if roles is not None:
                getter = functools.partial(discord.utils.get, ctx.author.roles)
                if any(getter(id=item) is not None if isinstance(item, int) else getter(name=item) is not None
                       for item in roles):
                    return True
                else:
                    raise commands.MissingAnyRole(roles)

        return True

    return commands.check(predicate)


async def check_permissions(ctx, perms, *, check=all):
    if is_owner(ctx):
        return True

    resolved = ctx.channel.permissions_for(ctx.author)
    return check(getattr(resolved, name, None) == value for name, value in perms.items())


def has_permissions(*, check=all, **perms):
    async def pred(ctx):
        return await check_permissions(ctx, perms, check=check)
    return commands.check(pred)