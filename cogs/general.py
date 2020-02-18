import logging
import random
import string
import typing


from discord import Embed, Color, Role, Member
from discord.ext import commands
from utils.formats import CustomEmbed


from utils.formats import colors
from config import ACTIVITY_ROLE_NAME, GENDER_ROLE_NAMES, STRANGER_ROLE_NAME

log = logging.getLogger('root')


class General(commands.Cog):
    """
    General Purpose Commands
    """

    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        log.info(f'{self.bot.user.name} has connected to Discord!')

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        # Try provide some user feedback instead of logging all errors.

        if isinstance(error, commands.CommandNotFound):
            return  # No need to log unfound commands anywhere or return feedback

        if isinstance(error, commands.MissingRequiredArgument):
            # Missing arguments are likely human error so do not need logging
            parameter_name = error.param.name
            return await ctx.send(f"\N{NO ENTRY SIGN} Required argument {parameter_name} was missing.\n {str(error)}")
        elif isinstance(error, commands.CheckFailure):
            return await ctx.send(f"\N{NO ENTRY SIGN} You do not have permission to use that command.\n {str(error)}")
        elif isinstance(error, commands.CommandOnCooldown):
            retry_after = round(error.retry_after)
            return await ctx.send(f"\N{HOURGLASS} Command is on cooldown, try again after {retry_after} seconds.\n {str(error)}")

        # All errors below this need reporting and so do not return

        if isinstance(error, commands.ArgumentParsingError):
            # Provide feedback & report error
            await ctx.send(f"\N{NO ENTRY SIGN} An issue occurred while attempting to parse an argument.\n {str(error)}")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"\N{NO ENTRY SIGN} Conversion of an argument failed.\n {str(error)}")
        else:
            await ctx.send(f"\N{NO ENTRY SIGN} An error occurred during execution, the error has been reported.\n {str(error)}")

        extra_context = {
            "discord_info": {
                "Channel": ctx.channel.mention,
                "User": ctx.author.mention,
                "Command": ctx.message.content
            }
        }

        if ctx.guild is not None:
            # We are NOT in a DM
            extra_context["discord_info"]["Message"] = (
                f'[{ctx.message.id}](https://discordapp.com/channels/'
                f'{ctx.guild.id}/{ctx.channel.id}/{ctx.message.id})'
            )
        else:
            extra_context["discord_info"]["Message"] = f"{ctx.message.id} (DM)"

        log.exception(error, extra=extra_context)

    @commands.group(name='stats', help='Command group for getting several statistics of the server',
                    hidden=True)
    async def stats(self, ctx):
        pass

    @commands.command(name='user', help='Get user avatar with information',
                      usage='[@user or username]\n'
                      'You can give member name or mention.')
    @commands.guild_only()
    async def user(self, ctx, members: commands.Greedy[Member], size: typing.Optional[str] = 's'):

        if size == 's':
            content_size = 1024
        elif size == 'm':
            content_size = 2048
        elif size == 'l':
            content_size = 4096
        else:
            raise commands.BadArgument('Size argument is not valid, please give: s.m or l')

        if not members:
            raise commands.BadArgument('No member is not given.')

        for member in members:
            avatar_url = str(member.avatar_url_as(size=content_size))
            member_text = f"Joined: {member.joined_at.strftime('%Y-%m-%d %H:%M:%S')}\n" \
                          f"Roles: {', '.join([role.name for role in member.roles if role.name != '@everyone'])}\n" \
                          f"Status: {str(member.status)}"
            embed_dict = {"title": "Avatar",
                          "author": {
                              "name": f"{member.display_name}",
                              "icon_url": avatar_url
                          },
                          "image": {"url": avatar_url},
                          'fields': [
                              {'name': "Information", 'value': member_text, 'inline': False},
                          ],
                          }
            e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name,
                                      avatar_url=self.bot.user.avatar_url,
                                      is_thumbnail=False)
            await ctx.send(embed=e.to_embed())

    @stats.command(name='gender', help='Get server statistics based on gender',
                   usage='gender [optional @role]\n'
                         'If a role is given, an additional gender statistics '
                         'based on this role will be given as well.')
    @commands.guild_only()
    async def gender(self, ctx, filter_role: typing.Optional[Role]):
        filter_role = filter_role or await commands.RoleConverter().convert(ctx, ACTIVITY_ROLE_NAME)

        if filter_role is None:
            raise commands.BadArgument('Role name is not valid.')
        else:
            if filter_role.name in GENDER_ROLE_NAMES:
                raise commands.BadArgument('You have given a gender role, please give another role.')

        guild = ctx.guild
        total_member = total_filtered_member = 0
        gender_dict = {gender: 0 for gender in GENDER_ROLE_NAMES}
        gender_dict_by_role = {gender: 0 for gender in GENDER_ROLE_NAMES}
        gender_undefined_members = ''
        for member in guild.members:
            has_gender_role = has_filter_role = False
            if member.bot or any(role.name == STRANGER_ROLE_NAME for role in member.roles):
                continue

            for index, member_role in enumerate(member.roles):
                if member_role.name == filter_role.name:
                    has_filter_role = True

                if member_role.name in GENDER_ROLE_NAMES:
                    has_gender_role = True
                    gender_dict[member_role.name] += 1
                    total_member += 1
                    if has_filter_role:
                        gender_dict_by_role[member_role.name] += 1
                        total_filtered_member += 1
                    else:
                        if filter_role in member.roles[index:]:
                            gender_dict_by_role[member_role.name] += 1
                            total_filtered_member += 1

                    # every member has one gender role
                    break

            if not has_gender_role:
                gender_undefined_members += f'<@{member.id}>\n'

        embed_dict = {'title': 'Gender statistics', 'color': Color.blue().value,
                      'fields': []
                      }
        if total_member > 0:
            gender_str = ''.join([f'**{gender}**: {"%.3f"%(count / total_member)}\u0009'
                                  for gender, count in gender_dict.items()])
            embed_dict['fields'].append({'name': "All member distribution", 'value': gender_str, 'inline': False})

        if total_filtered_member > 0:
            gender_filtered_str = ''.join([f'**{gender}**: {"%.3f"%(count / total_filtered_member)}\u0009'
                                           for gender, count in gender_dict_by_role.items()])
            embed_dict['fields'].append({'name': f"{filter_role.name} member distribution", 'value': gender_filtered_str, 'inline': False})

        if gender_undefined_members:
            embed_dict['fields'].append({'name': "Members with unassigned gender", 'value': gender_undefined_members, 'inline': False})

        if len(embed_dict['fields']):
            await ctx.send(embed=Embed.from_dict(embed_dict))
        else:
            await ctx.send('No statistics has been generated.')


    # async def help(self, ctx, *cog):
    #     """Gets all cogs and commands of mine."""
    #     try:
    #         if not cog:
    #             halp = Embed(title='Cog Listing and Uncatergorized Commands',
    #                         description='Use `!help *cog*` to find out more about them!\n(BTW, the Cog Name Must Be in Title Case, Just Like this Sentence.)')
    #             cogs_desc = ''
    #             for x in self.bot.cogs:
    #                 cogs_desc += ('{} - {}'.format(x, self.bot.cogs[x].__doc__) + '\n')
    #             halp.add_field(name='Cogs', value=cogs_desc[0:len(cogs_desc) - 1], inline=False)
    #             cmds_desc = ''
    #             for y in self.bot.walk_commands():
    #                 log.info(y)
    #                 if not y.cog_name and not y.hidden:
    #                     cmds_desc += ('{} - {}'.format(y.name, y.help) + '\n')
    #             halp.add_field(name='Uncatergorized Commands', value=cmds_desc[0:len(cmds_desc) - 1], inline=False)
    #             await ctx.message.add_reaction(emoji='✉')
    #             await ctx.send(embed=halp)
    #             # await ctx.message.author.send('', embed=halp)
    #         else:
    #             if len(cog) > 1:
    #                 halp = Embed(title='Error!', description='That is way too many cogs!',
    #                                      color=Color.red())
    #                 await ctx.message.author.send('', embed=halp)
    #             else:
    #                 found = False
    #                 for x in self.bot.cogs:
    #                     for y in cog:
    #                         if x == y:
    #                             halp = Embed(title=cog[0] + ' Command Listing',
    #                                                  description=self.bot.cogs[cog[0]].__doc__)
    #                             for c in self.bot.get_cog(y).get_commands():
    #                                 if not c.hidden:
    #                                     halp.add_field(name=c.name, value=c.help, inline=False)
    #                             found = True
    #                 if not found:
    #                     halp = Embed(title='Error!', description='How do you even use "' + cog[0] + '"?',
    #                                          color=Color.red())
    #                 else:
    #                     await ctx.message.add_reaction(emoji='✉')
    #                 await ctx.message.author.send('', embed=halp)
    #     except:
    #         pass
    @commands.command(name='help', description='The help command!', help='Help command', hidden=True,
                      aliases=['commands', 'command'], usage='section_name\n Ex: !help Admin')
    async def help_command(self, ctx, cog='all'):

        # The third parameter comes into play when
        # only one word argument has to be passed by the user

        # Prepare the embed

        color_list = [c for c in colors.values()]
        help_embed = Embed(
            title='Help',
            color=random.choice(color_list),
            description=f'Use `[@{self.bot.user.name}#{self.bot.user.discriminator} or prefix] help *section name*` '
                        f'to find out more about them!\n'
                        f'Ex: @{self.bot.user.name}#{self.bot.user.discriminator} help Admin'
        )
        help_embed.set_thumbnail(url=self.bot.user.avatar_url)
        help_embed.set_footer(
            text=f'Requested by {ctx.message.author.name}',
            icon_url=self.bot.user.avatar_url
        )

        # Get a list of all cogs
        cogs = [c for c in self.bot.cogs.keys()]
        command_list = set()

        # If cog is not specified by the user, we list all cogs and commands

        if cog == 'all':
            for cog in cogs:
                # Get a list of all commands under each cog

                cog_commands = self.bot.get_cog(cog).walk_commands()
                commands_list = ''
                for comm in cog_commands:
                    if not comm.hidden and comm.qualified_name not in command_list:
                        commands_list += f'**{comm.qualified_name}** - *{comm.help}.*\n'
                        command_list.add(comm.qualified_name)
                        # if comm.usage:
                        #     commands_list += f'*use: {comm.usage}*\n'

                # Add the cog's details to the embed.
                if commands_list:
                    help_embed.add_field(
                        name=cog,
                        value=commands_list,
                        inline=False
                    ).add_field(
                        name='\u200b', value='\u200b', inline=False
                    )

                # Also added a blank field '\u200b' is a whitespace character.
            pass
        else:

            # If the cog was specified

            lower_cogs = [c.lower() for c in cogs]

            # If the cog actually exists.
            if cog.lower() in lower_cogs:

                # Get a list of all commands in the specified cog
                commands_list = self.bot.get_cog(cogs[lower_cogs.index(cog.lower())]).walk_commands()
                help_text = ''

                # Add details of each command to the help text
                # Command Name
                # Help text
                # Usage
                # [Aliases]
                #
                # Format
                for command in commands_list:
                    if not command.hidden and command.qualified_name not in command_list:
                        help_text += f'```{command.qualified_name}```\n' \
                                     f'**{command.help}**\n\n'
                        # if command.usage:
                        #     help_text += f'*use: {command.usage}*\n'

                        # Also add aliases, if there are any
                        if len(command.aliases) > 0:
                            help_text += f'**Aliases :** `{"`, `".join(command.aliases)}`\n\n\n'
                        else:
                            # Add a newline character to keep it pretty
                            # That IS the whole purpose of custom help
                            help_text += '\n'

                        command_list.add(command.qualified_name)

                        # Finally the format
                        help_text += f'Format: `[@{self.bot.user.name}#{self.bot.user.discriminator} or prefix]' \
                                     f' {command.full_parent_name} {command.name} {command.usage if command.usage is not None else ""}`\n\n\n\n'

                help_embed.description = help_text
            else:
                # Notify the user of invalid cog and finish the command
                await ctx.send('Invalid cog specified.\nUse `help` command to list all cogs.')
                return

        await ctx.send(embed=help_embed)

        return


def setup(bot):
    bot.add_cog(General(bot))
