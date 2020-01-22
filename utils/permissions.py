import discord

from discord.ext import commands
from config import OWNER_ID


def is_owner(ctx):
    return ctx.author.id in OWNER_ID


async def check_permissions(ctx, perms, *, check=all):
    if ctx.author.id in OWNER_ID:
        return True

    resolved = ctx.channel.permissions_for(ctx.author)
    return check(getattr(resolved, name, None) == value for name, value in perms.items())


def has_permissions(*, check=all, **perms):
    async def pred(ctx):
        return await check_permissions(ctx, perms, check=check)
    return commands.check(pred)