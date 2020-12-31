import logging
import datetime
from fuzzywuzzy import process
from collections import defaultdict

from discord import TextChannel
from discord.ext import commands

from utils.formats import CustomEmbed
from utils.logger import LOGGER
from utils import helpers, checkers
from bot import Qutils


class General(commands.Cog):
    """
    General Purpose Commands
    """

    def __init__(self, bot: Qutils):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        LOGGER.info(f'{self.bot.user.name} has connected to Discord!')

    @commands.Cog.listener()
    async def on_command_error(self, ctx, error):
        # Try provide some user feedback instead of logging all errors.
        if isinstance(error, commands.CommandNotFound):
            await ctx.send(f"\N{NO ENTRY SIGN} The command has not found.\n {str(error)}")
        elif isinstance(error, commands.NoPrivateMessage):
            await ctx.send(f"\N{NO ENTRY SIGN} This command cannot use in DM.\n {str(error)}")
        elif isinstance(error, commands.BotMissingPermissions):
            await ctx.send(f"\N{NO ENTRY SIGN} The bot has missing permission: `{error.missing_perms[0]}`"
                           f" required to run the command.\n {str(error)}")
        elif isinstance(error, commands.MissingPermissions):
            await ctx.send(f"\N{NO ENTRY SIGN} The author of the command has missing permission:"
                           f" `{error.missing_perms[0]}`"
                           f" required to run the command.\n {str(error)}")
        elif isinstance(error, commands.MissingRequiredArgument):
            # Missing arguments are likely human error so do not need logging
            parameter_name = error.param.name
            await ctx.send(f"\N{NO ENTRY SIGN} Required argument {parameter_name} was missing.\n {str(error)}")
        elif isinstance(error, commands.CheckFailure):
            await ctx.send(f"\N{NO ENTRY SIGN} Check has been failed \n {str(error)}")
        elif isinstance(error, commands.CommandOnCooldown):
            retry_after = round(error.retry_after)
            await ctx.send(f"\N{HOURGLASS} Command is on cooldown, try again after {retry_after} seconds.\n {str(error)}")
        elif isinstance(error, commands.ArgumentParsingError):
            await ctx.send(f"\N{NO ENTRY SIGN} An issue occurred while attempting to parse an argument.\n {str(error)}")
        elif isinstance(error, commands.BadArgument):
            await ctx.send(f"\N{NO ENTRY SIGN} Conversion of an argument failed.\n {str(error)}")
        elif isinstance(error, commands.UserInputError):
            await ctx.send(f"\N{INPUT SYMBOL FOR LATIN LETTERS} You have provided wrong input.\n {str(error)}")
        else:
            await ctx.send(f"\N{NO ENTRY SIGN} An error occurred during execution, the error has been reported.\n {str(error)}")

        if isinstance(ctx.channel, TextChannel):
            extra_context = {
                "discord_info": {
                    "Channel": ctx.channel.mention,
                    "User": ctx.author.mention,
                    "Command": ctx.message.content
                }
            }
        else:
            extra_context = {
                "discord_info": {
                    "Channel": ctx.channel,
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
            LOGGER.exception(error, extra=extra_context, guild_id=ctx.guild.id)
        else:
            extra_context["discord_info"]["Message"] = f"{ctx.message.id} (DM)"
            LOGGER.exception(error, extra=extra_context)

    @commands.command(name='user', help='Get user avatar with information',
                      usage='[@user or username]\n'
                            'You can give member name or mention. If the name of member consists of'
                            'multiple words, use "..."',
                      aliases=['u'])
    # @commands.has_any_role(*VALID_STATS_ROLES)
    @checkers.has_any_config_role("all_valid_roles")
    @commands.guild_only()
    async def user(self, ctx, *, raw_member):
        # Fetch the config for this command
        try:
            guild_cf, cog_cf = helpers.get_common_settings(ctx.guild.id, ctx.cog.qualified_name.lower())
        except ValueError as err:
            return await ctx.send(err)

        short_delay = guild_cf.find_cog_setting("short_delay")

        sent_messages = []
        try:
            member = await commands.MemberConverter().convert(ctx, raw_member)
        except commands.MemberNotFound:
            member = None

        if member is None:
            threshold = 0.8
            if isinstance(raw_member, str):
                member_dict = defaultdict(list)
                for _member in ctx.guild.members:
                    member_dict[_member.name].append(_member)
                matching = process.extract(raw_member, list(member_dict.keys()), limit=3)
                if matching:
                    matching_strings = [str_ for str_, score in matching if score > threshold]
                    if matching_strings:
                        try:
                            matched_member_name = await ctx.disambiguate(matching_strings)
                        except ValueError as err:
                            return await ctx.send(err, delete_after=short_delay)

                        if matched_member_name:
                            members = member_dict.get(matched_member_name)
                            if len(members) > 1:
                                try:
                                    member_id = await ctx.disambiguate([f"{m.name} ({m.id})" for m in members])
                                except ValueError as err:
                                    return await ctx.send(err, delete_after=short_delay)

                                member = await helpers.get_member_by_id(ctx.guild, member_id)
                            elif len(members) == 1:
                                member = members[0]
        if member is None:
            raise commands.BadArgument(f'There is no member with given name')

        now = datetime.datetime.now()
        # avatar_url = str(member.avatar_url_as(size=content_size, static_format='webp'))
        avatar_url = str(member.avatar_url_as(static_format='webp'))
        days_created = (now - member.created_at).days
        days_joined = (now - member.joined_at).days
        member_text = f"**Created**: {member.created_at.strftime('%Y-%m-%d %H:%M:%S')} **({days_created} days)**\n" \
                      f"**Joined**: {member.joined_at.strftime('%Y-%m-%d %H:%M:%S')} **({days_joined} days)**\n" \
                      f"**Roles**: {', '.join([role.name for role in member.roles if role.name != '@everyone'])}\n" \
                      f"**Status**: {('Do not disturb' if (str(member.status) == 'dnd') else str(member.status))}\n" \
                      f"**Current activity**: {helpers.activity_to_str(member.activities)}\n" \
                      f"**Connected voice channel**: {member.voice.channel.name if member.voice else 'Not connected'}\n" \
                      # f"**Full avatar URL: **: {avatar_url}"

        top_hierarchy_role, top_h_dict = helpers.get_top_hierarchy_role(guild_cf, member.roles)
        if top_hierarchy_role is not None:
            member_text += f"**Top hierarchy role**: {top_hierarchy_role.name}\n"
            # check whether there is a upper level role by probing tonext variable
            tonext = top_h_dict.get_int("TONEXT")
            if tonext is not None:
                days_left = tonext - days_joined
                next_role = await helpers.get_role_by_id(ctx.guild, top_h_dict.get_int("NEXTID"))
                if next_role is not None:
                    role_upgrade_text = f'{top_hierarchy_role.name}  ➡️ {next_role}'
                    if days_left >= 0:
                        role_upgrade_text += f' **({days_left} days left)**'
                    else:
                        role_upgrade_text += f'**(have to update immediately!!!)**'

                    member_text += f"**Upgrade**: {'-' if role_upgrade_text is None else role_upgrade_text}\n"

        embed_dict = {"title": "Member profile",
                      "author": {
                          "name": f"{member.name}",
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

    @commands.group(name='stats', help='Command group for getting several statistics of the server',
                    hidden=True, aliases=['s'])
    @checkers.has_any_config_role("all_valid_roles")
    async def stats(self, ctx):
        pass

    @stats.command(name='summary', help='Get server summary statistics',
                   usage='summary', aliases=['sum'])
    @commands.guild_only()
    async def summary(self, ctx):
        guild = ctx.guild

        # Fetch the config for this command
        try:
            guild_cf, _ = helpers.get_common_settings(guild.id, ctx.cog.qualified_name.lower())
        except ValueError as err:
            return await ctx.send(err)

        embed_dict = {'title': '__Server info and statistics__',
                      'fields': []}

        # add basic server info
        server_info = f"**Name**: {guild.name}\n**Owner**: {guild.owner.display_name}\n**Description**: {guild.description}\n" \
                      f"**Created at**: {guild.created_at.strftime('%m/%d/%Y')}\n**Rules channel**: {guild.rules_channel.mention}\n" \
                      f"**# of voice channels**: {len(guild.voice_channels)}\n**# of text channels**: {len(guild.text_channels)}"
        embed_dict['fields'].append({'name': "__General info__", 'value': server_info, 'inline': False})

        total_member_count, valid_member_count = guild.member_count, 0
        valid_stats_role_ids = guild_cf.find_cog_setting("all_valid_roles", fallback=[])
        activity_role_id = int(guild_cf.get_helper_roles(fallback={}).get("ACTIVE_ROLE", default={}).get("ID", 0))
        activity_role = await helpers.get_role_by_id(guild, activity_role_id)

        # filter active members by valid roles
        active_members = []
        if activity_role:
            for member in activity_role.members:
                top_hierarchy_role, _ = helpers.get_top_hierarchy_role(guild_cf, member.roles)
                if top_hierarchy_role and top_hierarchy_role.id in valid_stats_role_ids:
                    active_members.append(member)

        # get member statistics by role and by active members
        member_role_text, activity_role_text = "", ""
        stats_roles = guild_cf.find_cog_setting("all_guild_roles", [])
        for role_id in stats_roles:
            role = await helpers.get_role_by_id(guild, int(role_id))
            if role is not None:
                role_member_count = len(role.members)
                member_role_text += f"\u21a6 **{role.name}:** {str(role_member_count)} /  {str(total_member_count)}" \
                                    f"(%{str(round((role_member_count / total_member_count)*100, 2))})\n"

                if role.id in valid_stats_role_ids:
                    valid_member_count += role_member_count

                    if activity_role is not None and active_members and role_member_count > 0:
                        active_m_with_role = set(role.members).intersection(active_members)
                        activity_role_text += f"\u21a6 **{role.name}:** {str(len(active_m_with_role))} (out of " \
                                              f"{str(role_member_count)}: %{str(round((len(active_m_with_role) / role_member_count) * 100, 2))}) " \
                                              f"/ {str(len(active_members))}" \
                                              f" (%{str(round((len(active_m_with_role) / len(active_members)) * 100, 2))})\n"

        member_role_text = f"**Total members:** {str(total_member_count)}\n " \
                           f"**Total valid members(exc. bot role and stranger role):** {str(valid_member_count)}\n" + member_role_text
        embed_dict['fields'].append({'name': "__By role distribution__", 'value': member_role_text, 'inline': False})

        # get role stats by active member grouped by role
        if activity_role_text:
            active_member_count = len(active_members)
            activity_role_text = f"**Active ({activity_role.name}) members:** " \
                                 f"{str(active_member_count)} / {str(valid_member_count)}\n" + activity_role_text
            embed_dict['fields'].append({'name': "__By active role distribution__", 'value': activity_role_text, 'inline': False})

        # list members who have the leader role
        leader_role_id = int(guild_cf.get_helper_roles({}).get("LEADER_ROLE", {}).get("ID", 0))
        leader_role = await helpers.get_role_by_id(guild, leader_role_id)
        if leader_role is not None:
            leader_members = leader_role.members
            leader_role_text = ""
            for member in leader_members:
                leader_role_text += f"* **{member.mention}** ({str(member.top_role)})\n"

            if leader_role_text:
                leader_role_text += str("""**```css\nCongratulations to all leader members!!! \nYou are the most precious building blocks of this channel.```**""")
                embed_dict['fields'].append({'name': f"__Leader ({leader_role.name}) members (Random order)__",
                                             'value': leader_role_text, 'inline': False})

        e = CustomEmbed.from_dict(embed_dict,
                                  author_name=ctx.author.name,
                                  avatar_url=self.bot.user.avatar_url,
                                  is_thumbnail=False)

        return await ctx.send(embed=e.to_embed(), delete_after=300)

    @stats.command(name='gender', help='Get server statistics based on gender',
                   usage='gender', aliases=['g'])
    @commands.guild_only()
    async def gender(self, ctx):
        guild = ctx.guild

        # Fetch the config for this command
        try:
            guild_cf, _ = helpers.get_common_settings(guild.id, ctx.cog.qualified_name.lower())
        except ValueError as err:
            return await ctx.send(err)

        valid_stats_role_ids = guild_cf.find_cog_setting("all_valid_roles", fallback=[])
        activity_role_id = int(guild_cf.get_helper_roles(fallback={}).get("ACTIVE_ROLE", default={}).get("ID", 0))
        activity_role = await helpers.get_role_by_id(guild, activity_role_id)

        valid_member_count = 0
        embed_dict = {'title': '__Gender statistics__',
                      'fields': []}

        # filter active members by valid roles
        active_members = []
        if activity_role:
            for member in activity_role.members:
                top_hierarchy_role, _ = helpers.get_top_hierarchy_role(guild_cf, member.roles)
                if top_hierarchy_role and top_hierarchy_role.id in valid_stats_role_ids:
                    active_members.append(member)

        # collect gender roles and find total valid members given gender roles
        gender_role_ids = guild_cf.get_gender_roles(fallback=[])
        gender_roles = {}
        for role_id in gender_role_ids:
            role = await helpers.get_role_by_id(guild, role_id)
            if role is not None:
                gender_roles[role.name] = role
                role_member_count = len(role.members)
                valid_member_count += role_member_count

        # get member stats by gender roles
        member_gender_text, member_activity_gender_text, = "", ""
        for role_name, role in gender_roles.items():
            role_member_count = len(role.members)
            member_gender_text += f"\u21a6 ** {role_name}:** {str(role_member_count)} /  {str(valid_member_count)}" \
                                  f"  (%{str(round((role_member_count / valid_member_count) * 100, 2))})\n"
            if activity_role is not None and active_members and role_member_count > 0:
                active_m_with_gender = set(role.members).intersection(active_members)
                active_m_with_gender_count = len(active_m_with_gender)
                if active_m_with_gender_count > 0:
                    member_activity_gender_text += f" **{role_name[0]}**:{str(active_m_with_gender_count)} /  {str(len(active_members))}" \
                                                   f" (%{str(round((active_m_with_gender_count / len(active_members)) * 100, 2))})"

        # get member stats by gender roles and being active
        valid_roles = await helpers.get_roles_by_id(guild, valid_stats_role_ids)
        member_role_gender_text, member_activity_role_gender_text = "", ""
        for valid_role in valid_roles:
            valid_role_member_count = len(valid_role.members)
            temp_text, temp_text2 = f"\u21a6 **{valid_role.name} =  **", f"\u21a6 **{valid_role.name} = **"
            for role_name, role in gender_roles.items():
                valid_role_with_gender = set(role.members).intersection(valid_role.members)
                valid_role_gender_count = len(valid_role_with_gender)
                if valid_role_gender_count > 0:
                    temp_text += f" **{role_name[0]}**:{str(valid_role_gender_count)} (out of {str(valid_role_member_count)}:" \
                                 f" %{str(round((valid_role_gender_count / valid_role_member_count) * 100, 2))}) /" \
                                 f" {str(valid_member_count)} (%{str(round((valid_role_gender_count / valid_member_count) * 100, 2))})"
                if activity_role is not None and active_members:
                    active_m_with_role = valid_role_with_gender.intersection(active_members)
                    active_role_gender_count = len(active_m_with_role)
                    if active_role_gender_count > 0:
                        temp_text2 += f" **{role_name[0]}**:{str(active_role_gender_count)} /  {str(len(active_members))}" \
                                      f" (%{str(round((active_role_gender_count / len(active_members)) * 100, 2))})"

            temp_text += "\n"
            temp_text2 += "\n"
            member_role_gender_text += temp_text
            member_activity_role_gender_text += temp_text2

        member_gender_text = f"**Total valid members(exc. bot role and stranger role):** {str(valid_member_count)}\n" + member_gender_text
        member_role_gender_text = f"**Total valid members(exc. bot role and stranger role):** {str(valid_member_count)}\n" + member_role_gender_text

        if activity_role is not None:
            member_activity_role_gender_text = f"**Total active ({activity_role.name}) members:** " \
                                               f"{str(len(active_members))}\n" + \
                                               f"**Active ({activity_role.name}) members by gender:** " + \
                                               member_activity_gender_text + "\n" + member_activity_role_gender_text

        embed_dict['fields'].append({'name': "__Overall Gender distribution__", 'value': member_gender_text, 'inline': False})
        embed_dict['fields'].append({'name': "__Gender distribution by role__", 'value': member_role_gender_text, 'inline': False})
        embed_dict['fields'].append({'name': "__Gender distribution by activity__", 'value': member_activity_role_gender_text, 'inline': False})

        e = CustomEmbed.from_dict(embed_dict,
                                  author_name=ctx.author.name,
                                  avatar_url=self.bot.user.avatar_url,
                                  is_thumbnail=False)

        return await ctx.send(embed=e.to_embed(), delete_after=300)

    @commands.command(name='help', description='The help command!', help='Help command', hidden=True,
                      aliases=['commands', 'command'], usage='section_name\n Ex: !help Admin')
    async def help_command(self, ctx, cog='all'):

        # The third parameter comes into play when
        # only one word argument has to be passed by the user

        # Get a list_role of all cogs
        cogs = [c for c in self.bot.cogs.keys()]
        command_list = set()
        guild = ctx.guild

        # If cog is not specified by the user, we list_role all cogs and commands

        if cog == 'all':
            help_embed = self._get_boilerplate_embed(guild=guild, author_name=ctx.author.name)
            for cog in cogs:
                command_list_with_parent = {}
                # Get a list_role of all commands under each cog
                cog_commands = self.bot.get_cog(cog).walk_commands()
                commands_list = ''
                for comm in cog_commands:
                    try:
                        is_able_run = await comm.can_run(ctx)
                    except commands.CommandError:
                        is_able_run = False

                    is_parent_able_run = True
                    if comm.parent:
                        try:
                            is_parent_able_run = await comm.parent.can_run(ctx)
                        except commands.CommandError:
                            is_parent_able_run = False

                    can_run_final = is_able_run and is_parent_able_run

                    if not comm.hidden and comm.qualified_name not in command_list and can_run_final:
                        root_parent = comm.root_parent
                        qua_name = comm.qualified_name
                        if root_parent:
                            # remove root parent name from full name for hierarchical repr.
                            qua_name = qua_name.replace(root_parent.name, '').strip()
                            command_with_help = f'**➸ {qua_name}** - *{comm.help}.*\n'
                            root_with_help = f'**{root_parent.name}** - *{root_parent.help}.*\n'
                            command_list_with_parent.setdefault(root_with_help, []).append(command_with_help)
                        else:
                            commands_list += f'**{qua_name}** - *{comm.help}.*\n'

                        command_list.add(comm.qualified_name)
                        # if comm.usage:
                        #     commands_list += f'*use: {comm.usage}*\n'

                for root_, child_list in command_list_with_parent.items():
                    commands_list += root_
                    for child in child_list:
                        commands_list += child

                # Add the cog's details to the embed.
                if commands_list:
                    help_embed.add_field(
                        name=f'__{cog}__',
                        value=commands_list,
                        inline=False
                    ).add_field(
                        name='\u200b', value='\u200b', inline=False
                    )

                # Also added a blank field '\u200b' is a whitespace character.
            return await ctx.send(embed=help_embed)
        else:

            # If the cog was specified

            lower_cogs = [c.lower() for c in cogs]

            # helper fetch_schedule for splitting long help embeds
            help_command_texts = []

            # If the cog actually exists.
            if cog.lower() in lower_cogs:

                # Get a list_role of all commands in the specified cog
                commands_list = self.bot.get_cog(cogs[lower_cogs.index(cog.lower())]).walk_commands()

                # Add details of each command to the help text
                # Command Name
                # Help text
                # Usage
                # [Aliases]
                #
                # Format
                for command in commands_list:
                    try:
                        is_able_run = await command.can_run(ctx)
                    except commands.CommandError:
                        is_able_run = False

                    is_parent_able_run = True
                    if command.parent:
                        try:
                            is_parent_able_run = await command.parent.can_run(ctx)
                        except commands.CommandError:
                            is_parent_able_run = False

                    can_run_final = is_able_run and is_parent_able_run

                    help_text = ''
                    if not command.hidden and command.qualified_name not in command_list and can_run_final:
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
                                     f' {command.full_parent_name} {command.name} {command.usage if command.usage is not None else ""}`\n\n'
                        help_command_texts.append(help_text)

                help_embeds = self._create_help_embeds(help_command_texts, author_name=ctx.author.name, cog_name=cog)
                return [await ctx.send(embed=help_embed) for help_embed in help_embeds]

            else:
                # Notify the user of invalid cog and finish the command
                return await ctx.send('Invalid cog specified.\n'
                                      'Use `help` command to list_role all cogs.')

    def _get_boilerplate_embed(self, guild=None, author_name=None, title='Help'):
        """ Create a boilerplate empty help embed """
        embed_dict = {'title': title,
                      'description': f'Use `{self.bot.get_guild_prefixes(guild)}help section_name` '
                                     f'to find out more about them!\n'
                                     f'Ex: @{self.bot.user.name}#{self.bot.user.discriminator} help Admin',
                      }
        try:
            embed = CustomEmbed.from_dict(embed_dict, avatar_url=self.bot.user.avatar_url, author_name=author_name)
        except Exception as e:
            if guild is not None:
                LOGGER.exception(e, guild_id=guild.id)
            else:
                LOGGER.exception(e)
        else:
            return embed

    def _create_help_embeds(self, help_command_texts, author_name=None, cog_name=None):
        """ Split help commands into chunks """
        new_help_text = ''
        help_embeds = []
        is_embed_created = False
        cog_text = f' **({cog_name})**'if cog_name is not None else ''
        for help_text in help_command_texts:
            if len(new_help_text) + len(help_text) < 2048:
                new_help_text += help_text
                is_embed_created = False
            else:
                title = f'Help{cog_text}' if len(help_embeds) == 0 else f'Help{cog_text}-{len(help_embeds) + 1}'
                help_embed = self._get_boilerplate_embed(author_name=author_name, title=title)
                help_embed.description = new_help_text
                help_embeds.append(help_embed)
                new_help_text, is_embed_created = help_text, True

        if not is_embed_created:
            title = f'Help{cog_text}' if len(help_embeds) == 0 else f'Help{cog_text}-{len(help_embeds) + 1}'
            help_embed = self._get_boilerplate_embed(author_name=author_name, title=title)
            help_embed.description = new_help_text
            help_embeds.append(help_embed)

        return help_embeds


def setup(bot):
    bot.add_cog(General(bot))
