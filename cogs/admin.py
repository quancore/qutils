import os
import textwrap
import typing
import glob

from discord import Member, Role, Embed, Colour, File, utils, HTTPException, PermissionOverwrite
from discord.ext import commands
import logging

import datetime
import asyncio
import json
from libneko import pag


from config import GUILD_ID, ACTIVITY_ROLE_NAME, ACTIVITY_INCLUDED_ROLES, ADMIN_ROLE_NAMES, RECEPTION_CHANNEL_ID, \
    activity_schedule_gap, activity_template, activity_pm_template, role_upgrade_template, \
    removed_member_pm_template, ANNOUNCEMENT_CHANNEL_ID, role_upgrade_gap, \
    TIER1, TIER1toTIER2, TIER2, TIER2toTIER3, TIER3, base_json_dir, short_delay, mid_delay
from utils import time, db, formats, helpers
from utils.formats import EmbedGenerator, CustomEmbed, Plural, pag

log = logging.getLogger('root')


class DiscardedUsers(db.Table):
    # this is the user_id
    id = db.Column(db.Integer(big=True), primary_key=True)
    num_discarded = db.Column(db.Integer, default=1)
    nickname = db.Column(db.String)
    joined_at = db.Column(db.Datetime)
    discarded_at = db.Column(db.Datetime)
    is_banned = db.Column(db.Boolean, default=False)
    last_role_id = db.Column(db.Integer(big=True))
    reason = db.Column(db.String, default='')

    # extra params
    extra = db.Column(db.JSON, default="'{}'::jsonb", nullable=False)


class ExceptionMembers(db.Table):
    member_id = db.Column(db.Integer(big=True), primary_key=True)
    guild_id = db.Column(db.Integer(big=True), primary_key=True)
    added_by = db.Column(db.Integer(big=True), nullable=False)
    until = db.Column(db.Datetime, nullable=False)
    reason = db.Column(db.String, default='')


class Admin(commands.Cog):
    """
    Admin functionality
    """

    def __init__(self, bot):
        self.bot = bot

# ****************  event handlers *********************
    @commands.Cog.listener('on_member_remove')
    async def handle_member_leave(self, member: Member):
        """ Remove member exception from activity rule when left the guild """
        # remove old member exception record if exist
        await self.remove_exception_db(member.guild.id, member_id=int(member.id))

    async def cleanup_schedule(self):
        """ Remove old scheduled member removal events and reschedule if no other removal event exists"""

        query = f"""WITH deleted AS (DELETE FROM reminders
                    WHERE event = 'schedule' AND expires < NOW() RETURNING *) 
                    SELECT id, expires, (extra #>> '{{args,1}}') AS members, 
                    (extra #>> '{{args,2}}') AS exceptions,
                    (extra #>> '{{args,3}}') AS reason, 
                    (extra #>> '{{args,4}}')::boolean AS is_ban, 
                    (extra #>> '{{args,5}}') AS role_id,
                    (extra #>> '{{args,6}}') AS included_roles
                    FROM deleted 
                    ORDER BY expires DESC
                    LIMIT 1;
                 """
        guild = await helpers.get_guild_by_id(self.bot, GUILD_ID)
        if guild is None:
            return log.exception('Guild is none in cleanup_schedule function')

        reminder = self.bot.get_cog('Reminder')
        if reminder is None:
            channel = await helpers.get_channel_by_id(self.bot, guild, ANNOUNCEMENT_CHANNEL_ID)
            if channel:
                log.exception("Reminder cog unavailable for cleanup_schedule operation")
                return await channel.send('Sorry, remainder cog is currently unavailable to use in cleanup_schedule.'
                                          'Please try again later')

        row = await self.bot.pool.fetchrow(query)
        if row:
            activity_schedule_gap_dt = time.FutureTime(activity_schedule_gap)
            expire_date = activity_schedule_gap_dt.dt - (datetime.datetime.utcnow() - row['expires'])
            # first check whether another scheduled removal exists within a day range
            check_query = f"""SELECT *
                              FROM reminders
                              WHERE '{expire_date}'::date < (expires + '{str(activity_schedule_gap)} days'::interval)
                              AND event = 'schedule'
                              AND extra #>> '{{args,0}}' = $1;
                            """
            total = await self.bot.pool.fetchrow(check_query, str(GUILD_ID))
            if total is None:
                activity_role = guild.get_role(int(row['role_id']))
                exception_ids = json.loads(row['exceptions'])
                exceptions = [await helpers.get_member_by_id(guild, member_id) for member_id in exception_ids]
                included_roles = json.loads(row['included_roles'])
                inactive_members, member_text = await helpers.get_inactive_members(guild, included_roles,
                                                                                   activity_role, exceptions)
                activity_template_final = activity_template.format(expire_date.strftime("%Y-%m-%d %H:%M:%S"))
                embed_dict = {'title': activity_template_final,
                              'fields': [{'name': 'Members will be discarded', 'value': member_text, 'inline': False}, ]
                              }

                channel = await helpers.get_channel_by_id(self.bot, guild, ANNOUNCEMENT_CHANNEL_ID)
                if channel:
                    await channel.send(embed=Embed.from_dict(embed_dict))

                await reminder.create_timer(expire_date, 'schedule', GUILD_ID,
                                            json.dumps(inactive_members), row['exceptions'], row['reason'],
                                            row['is_ban'], row['role_id'], row['included_roles'],
                                            connection=self.bot.pool,
                                            created=datetime.datetime.utcnow())

                log.info(f'The event has been rescheduled in autonomous function for '
                         f'{expire_date.strftime("%Y-%m-%d %H:%M:%S")}.')
            else:
                log.info(f'There is already scheduled member removal based on activity on '
                         f'{total["expires"].strftime("%Y-%m-%d %H:%M:%S")}, '
                         f'so autonomous function could not schedule a new removal.')

    @commands.Cog.listener()
    async def on_ready(self):
        # pass
        # self.bot.loop.run_until_complete(self.update_roles())
        asyncio.ensure_future(self.cleanup_schedule(), loop=self.bot.loop)
        asyncio.ensure_future(self.update_roles(), loop=self.bot.loop)

# *******************************************
    @commands.command(name='set_prefix', help='Set the server prefix',
                      usage='<prefix_to_set>\n\n'
                            'For setting multiple prefix, use: "! ? - ...."\n\n'
                            'Ex: !set_prefix "! -"', aliases=['s_p'])
    @commands.has_any_role(*ADMIN_ROLE_NAMES)
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def set_prefix(self, ctx, prefix: str):
        guild = ctx.guild
        prefixes = prefix.split(' ')
        await self.bot.set_guild_prefixes(guild, prefixes)
        await ctx.send(f'The prefix has been set to: **{prefixes}**', delete_after=short_delay)

    @commands.command(name='change_permission', help='Change a channel permission based on a json file',
                      usage='The JSON file should be in the format of freezone_text_open.json and'
                            'stored in json_templates directory.\n\n'
                            'Ex: !change_permission', aliases=['c_p'])
    @commands.has_permissions(administrator=True)
    @commands.guild_only()
    @commands.cooldown(1, 5, commands.BucketType.guild)
    async def change_permission(self, ctx):
        sent_messages = [ctx.message]
        try:
            pseudo_path = os.path.join(base_json_dir, "*.json")
            json_files = glob.glob(pseudo_path)
            if len(json_files) == 0:
                return await ctx.send("No file has been found in json directory", delete_after=short_delay)

            json_dict = {}
            json_filename_text = ''
            for index, json_path in enumerate(json_files):
                filename = os.path.basename(json_path)
                json_filename_text += f'**{index+1})** {filename}\n'
                json_dict[index+1] = json_path

            question = '**__Here is the list of JSON templates for channels:__**\n' \
                       f'{json_filename_text}' \
                       'Please type the number of file you want to use otherwise type c'
            try:
                abs_json_path, msg = await helpers.get_multichoice_answer(self.bot, ctx, json_dict, question)
                sent_messages.extend(msg)
            except asyncio.TimeoutError:
                return await ctx.send('Please type in 60 seconds next time.', delete_after=short_delay)

            if abs_json_path is None:
                return await ctx.send('Command has been cancelled.', delete_after=short_delay)

            with open(abs_json_path, 'r', encoding='utf-8') as r:
                try:
                    perms = json.load(r)
                except Exception as e:
                    return await ctx.send(f"Encountered error during JSON read: {e}", delete_after=short_delay)

            channel_settings = perms['settings']
            guild = ctx.guild
            channel_name, channel_type = channel_settings['channelName'], channel_settings['channelType']
            channel = await helpers.get_channel_by_name(guild, channel_name, channel_type)
            if channel:
                role_settings = channel_settings['permissionOverrides']
                for role_setting in role_settings:
                    role_name = role_setting['roleName']
                    role = await helpers.get_role_by_name(guild, role_name)
                    if role:
                        perms = role_setting['permissions']
                        overwrite = PermissionOverwrite()
                        overwrite.update(**perms)
                        await channel.set_permissions(role, overwrite=overwrite)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)

    @commands.group(name='discard', help='Command group for discarding members',
                    usage='This is not a command but a command group.', hidden=True)
    @commands.has_any_role(*ADMIN_ROLE_NAMES)
    async def discard(self, ctx):
        pass

    @discard.command(name='by_role', help='Kick / ban all members with a given role',
                     usage='<@role_mention> <is_ban> <@exceptions>\n\n'
                           'is_ban: bool, default True - True for ban/ False for Kick\n'
                           'exceptions: List[Member], default None - Members will be excluded for this op.\n\n'
                           'Ex: !discard by_role @Yabancilar True @mem1 @mem2')
    @commands.guild_only()
    async def by_role(self, ctx, role: Role, is_ban: typing.Optional[bool] = False,
                      exceptions: commands.Greedy[Member] = None,
                      *, reason: str = 'Discharged due to inactivity'):
        sent_messages = [ctx.message]
        try:
            if exceptions is None:
                exceptions = []

            if role is None:
                return await self.cog_command_error(ctx, commands.BadArgument('Role name is not valid'))

            guild = ctx.guild

            # get global exception members and include them in exceptions
            global_exception_member_records = await self.fetch_all_exceptions(self.bot.pool, guild.id)
            global_exception_members = [await helpers.get_member_by_id(guild, record['member_id'])
                                        for record in global_exception_member_records]
            exceptions = [member for member in global_exception_members if member and member not in exceptions]

            valid_members, query_params = [], []
            member_text, exception_member_text = '', ''
            col_list = DiscardedUsers.get_col_names(excluded=['id', 'num_discarded', 'extra'])
            col_names = ', '.join(col_list)
            col_val_placeholder = ', '.join(f'${3 + i}' for i in range(len(col_list)))
            query = f"""INSERT INTO discardedusers AS du (id, num_discarded, {col_names})
                        VALUES ($1, $2, {col_val_placeholder})
                        ON CONFLICT (id)
                        DO UPDATE
                        SET (num_discarded, {col_names}) = ROW(du.num_discarded+1, {col_val_placeholder});
                    """

            for member in guild.members:
                if member not in exceptions:
                    if role in member.roles:
                        valid_members.append(member)
                        member_text += (member.display_name + '\n')
                        top_role_id = member.top_role.id
                        query_params.append(
                            (member.id, 1, member.display_name, member.joined_at, datetime.datetime.utcnow(),
                             is_ban, top_role_id, reason))
                else:
                    exception_member_text += (member.display_name + '\n')

            if exception_member_text is '':
                exception_member_text = 'No exception'

            embed_dict = {'title': 'Operation summary', 'colour': Colour.red(),
                          'timestamp': datetime.datetime.utcnow().__str__(),
                          'fields': [{'name': "Operation type", 'value': 'Ban' if is_ban else 'Kick', 'inline': False},
                                     {'name': "Role", 'value': role.name, 'inline': False},
                                     {'name': 'Member list_role', 'value': member_text, 'inline': False},
                                     {'name': 'Exceptions (some may come from global exceptions)',
                                      'value': exception_member_text, 'inline': False},
                                     {'name': 'Reason', 'value': reason, 'inline': False},
                                     ],
                          }
            e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name, avatar_url=self.bot.user.avatar_url)
            msg = await ctx.send(embed=e.to_embed())
            sent_messages.append(msg)

            confirm = await ctx.prompt("Are you sure you want to handle operation?", timeout=short_delay, delete_after=True)
            if confirm:
                for member in valid_members:
                    if is_ban:
                        await member.ban(reason=reason)
                    else:
                        await member.kick(reason=reason)

                await ctx.db.executemany(query, query_params)

            elif confirm is None:
                await ctx.send("Operation has been cancelled.", delete_after=short_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)

    @discard.command(name='fetch', help='Display all discarded users\n',
                     usage='<to_csv>\n\n'
                           'to_csv: bool, default False - True for writing to CSV otherwise False\n\n'
                           'Ex: !discard fetch True')
    @commands.guild_only()
    async def fetch(self, ctx, to_csv: typing.Optional[bool] = False):
        query = """SELECT format('<@%s>', id) AS "User",
                    nickname AS "Nickname",
                    num_discarded AS "Num. discarded",
                    TO_CHAR(joined_at :: DATE, 'dd/mm/yyyy') AS "Joined", 
                    TO_CHAR(discarded_at :: DATE, 'dd/mm/yyyy') AS "Discarded",
                    (CASE WHEN is_banned THEN 'B' ELSE 'K' end) AS "Type",
                    (CASE WHEN last_role_id IS NOT NULL THEN format('<@&%s>', last_role_id) ELSE '-' end) AS "Role",
                    (CASE WHEN reason <> '' THEN reason ELSE '-' end) AS "Reason"
                    FROM discardedusers"""

        sent_messages, sent_navs = [ctx.message], []
        try:
            records = await ctx.db.fetch(query)
            if len(records) == 0:
                return await ctx.send('No results found...', delete_after=mid_delay)

            nav = pag.StringNavigatorFactory(max_lines=20, enable_truncation=False)
            data = formats.TabularData(nav.line_break)
            table_columns = ["User", "Num. discarded", "Joined", "Discarded", "Type", "Role", "Reason"]
            data.set_columns(table_columns)
            data.add_rows(records, [1])
            nav.prefix = data.get_column_str()

            nav += data.render(render_column=False)
            emb_nav = nav.build(ctx=ctx)
            emb_nav.start()
            sent_navs.append(emb_nav)

            if to_csv:
                f = data.to_csv(["ID", "Nickname", "Num. discarded", "Joined", "Discarded", "Type", "Role", "Reason"])
                return await ctx.channel.send(content="Removed users CSV file",
                                              file=File(fp=f, filename="removed_user_info.txt"), delete_after=mid_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=120)

    @discard.command(name='clear', help='Remove all discarded user records',
                     usage="Ex: !discard clear")
    @commands.guild_only()
    async def clear_d(self, ctx):
        sent_messages = [ctx.message]
        try:
            query = """TRUNCATE discardedusers;"""
            confirm = await ctx.prompt('Are you sure you want to delete all records?', timeout=short_delay, delete_after=True)
            if confirm is None:
                return await ctx.send('Operation has timeout', delete_after=short_delay)
            elif not confirm:
                return await ctx.send('Operation has been aborted', delete_after=short_delay)

            status = await ctx.db.execute(query)
            if status == 'DELETE 0':
                return await ctx.send('Could not delete any event with that ID.', delete_after=short_delay)

            return await ctx.send('Successfully deleted all records.', delete_after=short_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)

    @commands.group(name='schedule', help='Command group for scheduling and controlling member removal ops',
                    usage='This is not a command but a command group.', hidden=True, aliases=['sc'])
    @commands.has_any_role(*ADMIN_ROLE_NAMES)
    async def schedule(self, ctx):
        pass

    @schedule.command(name='create', help='Schedule an removal event based on activity role',
                      usage='<duration> <@included_roles> <is_ban> <@exceptions> <reason>\n\n'
                            'duration: time.FutureTime, required - human language duration expression. '
                            'Example durations: 30d, "until thursday at 3PM", "2024-12-31". '
                            'Note that times are in UTC.\n'
                            'included_roles: List[Role], default None - role names, mentions or ids '
                            'the operation will be executed on. If None, all activity roles in config will be used.\n'
                            'is_ban: bool, default False - True for ban false for kick when a member is discarded.\n'
                            'exceptions: List[Member], default None - Members will be excluded for this op.\n'
                            'reason: str, default "Discharged on scheduled removal" - reason to this operation.\n\n'
                            "Ex: !schedule create 10d @Çaylaklar False @abc @abd 'ban due to inactivity'",
                      aliases=['c'])
    @commands.guild_only()
    async def create(self, ctx, duration: time.FutureTime,
                     included_roles: commands.Greedy[Role] = None,
                     is_ban: typing.Optional[bool] = False,
                     exceptions: commands.Greedy[Member] = None,
                     *, reason: str = 'Discharged on scheduled removal'):

        sent_messages = [ctx.message]
        try:
            guild = ctx.guild

            # first check whether another scheduled removal exists within a day range
            query = f"""SELECT *
                        FROM reminders
                        WHERE '{duration.dt}'::date BETWEEN (expires - '{str(activity_schedule_gap)} days'::interval) AND 
                        (expires + '{str(activity_schedule_gap)} days'::interval)
                        AND event = 'schedule'
                        AND extra #>> '{{args,0}}' = $1;
                    """
            total = await self.bot.pool.fetchrow(query, str(guild.id))
            if total:
                return await ctx.send(f'There is already a scheduled event has the time gap '
                                      f'less than {activity_schedule_gap} days', delete_after=short_delay)

            if exceptions is None:
                exceptions = []

            activity_role = await commands.RoleConverter().convert(ctx, ACTIVITY_ROLE_NAME)
            if activity_role is None:
                return await self.cog_command_error(ctx, commands.BadArgument('Role determining '
                                                                              'activity of members is incorrect'))

            included_roles = tuple(included_role.name for included_role in included_roles) \
                if included_roles else ACTIVITY_INCLUDED_ROLES
            if included_roles is None:
                return await self.cog_command_error(ctx, commands.BadArgument('Role defining member set is not valid.'))

            # get global exception members and include them in exceptions
            global_exception_member_records = await self.fetch_all_exceptions(self.bot.pool, guild.id)
            global_exception_members = [await helpers.get_member_by_id(guild, record['member_id'])
                                        for record in global_exception_member_records]
            exceptions = exceptions + [member for member in global_exception_members if member and member not in exceptions]

            exception_member_text = ''.join(f'{member.mention}\n' for member in exceptions)

            valid_members, member_text = await helpers.get_inactive_members(guild, included_roles,
                                                                            activity_role, exceptions)

            if exception_member_text is '':
                exception_member_text = 'No exception member'

            if member_text is '':
                member_text = 'No member will be discarded'

            included_role_text = ', '.join([role for role in included_roles])
            embed_dict = {'title': 'Operation summary',
                          'fields': [{'name': "Operation type", 'value': 'Ban' if is_ban else 'Kick', 'inline': False},
                                     {'name': "Included Roles", 'value': included_role_text, 'inline': False},
                                     {'name': 'Members will be discarded', 'value': member_text, 'inline': False},
                                     {'name': 'Date of removal', 'value': duration.dt.strftime("%Y-%m-%d %H:%M:%S"), 'inline': False},
                                     {'name': 'Exceptions (some may come from global exceptions)', 'value': exception_member_text, 'inline': False},
                                     {'name': 'Reason', 'value': reason, 'inline': False},
                                     ],
                          }
            e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name, avatar_url=self.bot.user.avatar_url)
            msg = await ctx.send(embed=e.to_embed())
            sent_messages.append(msg)

            confirm = await ctx.prompt("Are you sure to schedule the event?", timeout=short_delay, delete_after=True)
            if confirm:
                activity_template_final = activity_template.format(duration.dt.strftime("%Y-%m-%d %H:%M:%S"))
                embed_dict = {'title': activity_template_final,
                              'fields': [{'name': 'Members will be discarded', 'value': member_text, 'inline': False}]
                              }
                channel = await helpers.get_channel_by_id(self.bot, guild, ANNOUNCEMENT_CHANNEL_ID)
                if channel:
                    await channel.send(embed=Embed.from_dict(embed_dict))

                reminder = self.bot.get_cog('Reminder')
                if reminder is None:
                    return await ctx.send('Sorry, this functionality is currently '
                                          'unavailable. Please try again later', delete_after=short_delay)

                exception_ids = [member.id for member in exceptions]
                await reminder.create_timer(duration.dt, 'schedule', ctx.guild.id,
                                            json.dumps(valid_members), json.dumps(exception_ids),
                                            reason, is_ban, activity_role.id, json.dumps(included_roles),
                                            connection=ctx.db,
                                            created=ctx.message.created_at)

                # send a pm to all user to announce removal
                filled_pm_message = activity_pm_template.format(guild.name, duration.dt.strftime("%Y-%m-%d %H:%M:%S"))
                for member_id in valid_members:
                    member = await helpers.get_member_by_id(guild, member_id)
                    if member:
                        await member.send(filled_pm_message)

                log.info(f'A removal event has been scheduled for the date: {duration.dt.strftime("%Y-%m-%d %H:%M:%S")}.')
                return await ctx.send(f'The removal event has been '
                                      f'scheduled for {duration.dt.strftime("%Y-%m-%d %H:%M:%S")}.', delete_after=60)

            elif confirm is None:
                return await ctx.send('Operation has timeout.', delete_after=short_delay)
            else:
                return await ctx.send('Operation has been cancelled.', delete_after=short_delay)

        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)

    @schedule.command(name='delete', help='Delete a scheduled event with id',
                      usage="<item_id>\n\n"
                            "item_id: int, required\n"
                            "Run fetch command to get currently queued events.\n\n"
                            "Ex: !schedule delete 124",
                      aliases=['d'])
    @commands.guild_only()
    async def delete(self, ctx, item_id: int):
        query = """DELETE FROM reminders
                    WHERE id=$1
                    AND event = 'schedule';
                """
        sent_messages = [ctx.message]
        try:
            confirm = await ctx.prompt('Are you sure you want to delete the record?',
                                       timeout=short_delay, delete_after=True)
            if confirm is None:
                return await ctx.send('Operation has been timeout.', delete_after=short_delay)
            elif not confirm:
                return await ctx.send('Operation has been aborted.', delete_after=short_delay)

            status = await ctx.db.execute(query, item_id)
            if status == 'DELETE 0':
                return await ctx.send('Could not delete any event with that ID.', delele_after=short_delay)

            return await ctx.send("Successfully deleted scheduled event.", delete_after=short_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)

    @schedule.command(name='clear', help='Delete all scheduled events',
                      usage="Ex: !schedule clear",
                      aliases=['cl'])
    @commands.guild_only()
    async def clear(self, ctx):
        # For UX purposes this has to be two queries.

        query = """SELECT COUNT(*)
                    FROM reminders
                    WHERE event = 'schedule';
                """

        sent_messages = [ctx.message]
        try:
            total = await ctx.db.fetchrow(query)
            total = total[0]
            if total == 0:
                return await ctx.send('You do not have any schedule events to delete.', delete_after=short_delay)

            confirm = await ctx.prompt(f'Are you sure you want to delete '
                                       f'{formats.Plural(total):scheduled events}?', timeout=short_delay, delete_after=True)
            if confirm is None:
                return await ctx.send('Operation has been timeout.', delete_after=short_delay)
            elif not confirm:
                return await ctx.send('Operation has been aborted.', delete_after=short_delay)

            query = """DELETE FROM reminders WHERE event = 'schedule';"""
            await ctx.db.execute(query)

            return await ctx.send(f'Successfully deleted {formats.Plural(total):scheduled events}.', delete_after=short_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=short_delay)

    @schedule.command(name='fetch', help='Fetch last 10 scheduled events',
                      usage="Ex: !schedule fetch", aliases=['f'])
    @commands.guild_only()
    async def fetch_schedule(self, ctx):
        query = f"""SELECT id, expires, (extra #>> '{{args,1}}') AS members, extra #>> '{{args,2}}' AS exceptions, 
                    extra #>> '{{args,3}}' AS reason, 
                    (extra #>> '{{args,4}}')::boolean AS is_ban
                    FROM reminders
                    WHERE event = 'schedule'
                    AND extra #>> '{{args,0}}' = $1
                    ORDER BY expires
                    LIMIT 10;
                    """
        sent_messages = [ctx.message]
        try:
            guild = ctx.guild
            records = await ctx.db.fetch(query, str(guild.id))

            if len(records) == 0:
                return await ctx.send(f'No scheduled event has been found.', delete_after=mid_delay)

            embed_dict = {'title': 'Scheduled removals'}

            if len(records) == 10:
                embed_dict['footer'] = {'text': 'Only showing up to 10 reminders.'}
            else:
                embed_dict['footer'] = {'text': f'{len(records)} reminder{"s" if len(records) > 1 else ""}'}

            fields, _id_to_row = [], {}
            for index, (_id, expires, _, _, reason, _) in enumerate(records):
                shorten = textwrap.shorten(reason, width=512)
                field = {'name': f'**{index+1})** ID: {_id}: In {time.human_timedelta(expires)}',
                         'value': shorten, 'inline': False}
                _id_to_row[index+1] = _id
                fields.append(field)

            embed_dict['fields'] = fields

            e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name, avatar_url=self.bot.user.avatar_url)
            msg = await ctx.send(embed=e.to_embed())
            sent_messages.append(msg)

            question = 'Please type the row number for check details otherwise type c'
            try:
                id_, msg = await helpers.get_multichoice_answer(self.bot, ctx, _id_to_row, question)
                sent_messages.extend(msg)
            except asyncio.TimeoutError:
                return await ctx.send('Please type in 60 seconds next time.', delete_after=short_delay)

            if id_ is None:
                return await ctx.send('Command has been cancelled.', delete_after=short_delay)

            record = next((record for record in records if record['id'] == id_), None)
            member_list = json.loads(record['members'])
            exceptions_list = json.loads(record['exceptions'])
            member_list_str = ''.join([f'<@{member_id}>\n' for member_id in member_list])
            exceptions_list_str = ''.join([f'<@{member_id}>\n' for member_id in exceptions_list])
            embed_dict = {'title': 'Scheduled removal', 'colour': Colour.blurple(),
                          'fields': [
                              {'name': "Operation type", 'value': 'Ban' if record['is_ban'] else 'Kick', 'inline': False},
                              {'name': 'Members will be discarded', 'value': member_list_str, 'inline': False},
                              {'name': 'Exception members', 'value': exceptions_list_str, 'inline': False},
                              {'name': 'Date of removal', 'value': record['expires'].strftime("%Y-%m-%d %H:%M:%S"),
                               'inline': False},
                              {'name': 'Reason', 'value': record['reason'], 'inline': False},
                              ],
                          }
            e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name, avatar_url=self.bot.user.avatar_url)
            await ctx.send(embed=e.to_embed(), delete_after=mid_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages)

    @schedule.command(name='add_exception', help='Add an exception member which '
                                                 'will be excluded on all automated member removals',
                      usage="<duration> <@member> <reason>\n\n"
                            "duration: time.FutureTime - human language duration expression."
                            "member: Member, required - a member mention, id or name to be excluded.\n"
                            "reason: str, required - reason to the member exclusion op.\n"
                            "Ex: !schedule add_exception 14days @mem1 'reason for not'",
                      aliases=['a_e'])
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True, kick_members=True, ban_members=True)
    async def add_exception(self, ctx, duration: time.FutureTime, member: Member, reason: str):
        query = f"""INSERT INTO exceptionmembers (member_id, guild_id, added_by, until, reason)
                    VALUES ($1, $2, $3, $4, $5)
                    ON CONFLICT (member_id, guild_id)
                    DO UPDATE
                    SET added_by = EXCLUDED.added_by, until = EXCLUDED.until, reason=EXCLUDED.reason;
                """
        sent_messages = [ctx.message]
        try:
            author = ctx.author
            guild = ctx.guild
            if member is None:
                return await ctx.send(f'Member not found.', delete_after=short_delay)

            # first remove old exceptions from DB
            await self.remove_exception_db(guild.id)

            await self.bot.pool.execute(query, member.id, guild.id, author.id, duration.dt, reason)
            return await ctx.send(f'Exception added for: {member.mention} by: {author.mention} '
                                  f'until: {duration.dt.strftime("%Y-%m-%d %H:%M:%S")} for reason: {reason}',
                                  delete_after=short_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages)

    @staticmethod
    async def fetch_all_exceptions(db_conn, guild_id):
        """ Fetch all exceptions for given guild ID """
        query = """ SELECT * FROM exceptionmembers
                    WHERE guild_id = $1"""
        return await db_conn.fetch(query, guild_id)

    async def remove_exception_db(self, guild_id, member_id: int = None):
        """ Remove all exceptions older than now.
        If member_id given, removal will be based on member"""
        query = """DELETE FROM exceptionmembers
                WHERE (guild_id = $1) AND (until < NOW() OR 
                ($2::BIGINT is not null and member_id::BIGINT = $2))"""

        # first clear DB
        await self.fetch_all_exceptions(self.bot.pool, guild_id)

        return await self.bot.pool.execute(query, guild_id, member_id)

    @schedule.command(name='fetch_exception', help='Fetch all exceptions in DB',
                      usage="Ex: !schedule fetch_exception",
                      aliases=['f_e'])
    @commands.guild_only()
    async def fetch_exception(self, ctx):
        sent_messages, sent_navs = [ctx.message], []
        try:
            author = ctx.author
            guild = ctx.guild

            records = await self.fetch_all_exceptions(self.bot.pool, guild.id)
            if len(records) == 0:
                return await ctx.send(f'No exception has been found.', delete_after=short_delay)

            format_dict = {'title': 'Member exception list',
                           'footer': {'text': f'Showing {Plural(len(records)):exception}'}}
            e_generator = EmbedGenerator(format_dict=format_dict, author_name=author.name,
                                         avatar_url=self.bot.user.avatar_url)
            nav = pag.EmbedNavigatorFactory(factory=e_generator, max_lines=20)
            for member_id, _, added_by_id, until, reason in records:
                member = await helpers.get_member_by_id(guild, member_id)
                if member:
                    added_by_member = await helpers.get_member_by_id(guild, added_by_id)
                    shorten = textwrap.shorten(reason, width=500)
                    line = f'**Member:** {member.mention} **ID**: {member_id} | ' \
                           f'**Added_by:**: {added_by_member.mention if added_by_member else added_by_id} | ' \
                           f'**Until:** {until.strftime("%Y-%m-%d %H:%M:%S")} -> {shorten}'
                    nav.add_line(line)
                    nav.add_line('**-----------------------------**')

            emb_nav = nav.build(ctx=ctx)
            emb_nav.start()
            sent_navs.append(emb_nav)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=short_delay)

    @schedule.command(name='delete_exception', help='Delete an exception for a member.',
                      usage="Ex: !schedule delete_exception",
                      aliases=['d_e'])
    @commands.guild_only()
    async def delete_exception(self, ctx):
        sent_messages, sent_navs = [ctx.message], []
        try:
            author = ctx.author
            guild = ctx.guild

            records = await self.fetch_all_exceptions(self.bot.pool, guild.id)
            if len(records) == 0:
                return await ctx.send(f'No exception has been found.', delete_after=short_delay)

            format_dict = {'title': 'Member exception list',
                           'footer': {'text': f'Showing {Plural(len(records)):exception}'}}
            e_generator = EmbedGenerator(format_dict=format_dict, author_name=author.name,
                                         avatar_url=self.bot.user.avatar_url)
            nav = pag.EmbedNavigatorFactory(factory=e_generator, max_lines=20)
            _row_to_member_id = {}
            for index, (member_id, _, added_by_id, until, reason) in enumerate(records):
                member = await helpers.get_member_by_id(guild, member_id)
                if member:
                    added_by_member = await helpers.get_member_by_id(guild, added_by_id)
                    shorten = textwrap.shorten(reason, width=500)
                    line = f'**{index+1})** **Member:** {member.mention} **ID**: {member_id} | ' \
                           f'**Added_by:**: {added_by_member.mention if added_by_member else added_by_id} | ' \
                           f'**Until:** {until.strftime("%Y-%m-%d %H:%M:%S")} -> {shorten}'
                    _row_to_member_id[index+1] = member.id
                    nav.add_line(line)
                    nav.add_line('**-----------------------------**')

            emb_nav = nav.build(ctx=ctx)
            emb_nav.start()
            sent_navs.append(emb_nav)

            question = 'Please type the row number for delete an exception otherwise type c'
            try:
                member_id_or_none, msg = await helpers.get_multichoice_answer(self.bot, ctx, _row_to_member_id, question)
                sent_messages.extend(msg)
            except asyncio.TimeoutError:
                return await ctx.send('Please type in 60 seconds next time.', delete_after=short_delay)

            if member_id_or_none is None:
                return await ctx.send('Command has been cancelled.', delete_after=short_delay)

            return await self.remove_exception_db(guild.id, member_id_or_none)

        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=short_delay)

    @commands.group(name='role', help='Command group for role based member operations',
                    usage='This is not a command but a command group.', hidden=True)
    @commands.has_any_role(*ADMIN_ROLE_NAMES)
    async def role(self, ctx):
        pass

    @role.command(name='list', help='List the user with given roles',
                  usage='<@roles> <is_cs>\n\n'
                        'roles: list[Role], required - role mentions, ids, or names to be processed\n'
                        'is_cs: bool, default False - output member name with comma separated format or not\n'
                        'If multiple roles given, the intersection fo them will be listed.\n\n'
                        'Ex: !role list @Yabancılar',
                  aliases=['l'])
    @commands.guild_only()
    async def list_role(self, ctx, roles: commands.Greedy[Role], is_cs: typing.Optional[bool] = False):
        sent_messages = [ctx.message]
        try:
            if not roles:
                raise commands.BadArgument('No role is not given.')

            members = []
            guild = ctx.guild
            for member in guild.members:
                member_roles = member.roles
                if member_roles:
                    check_all = all([True if role in member_roles else False for role in roles])
                    if check_all:
                        members.append(member)

            member_text = None
            if members:
                if not is_cs:
                    member_text = '\n'.join([member.mention for member in members])
                else:
                    member_text = ','.join([member.name for member in members])

            role_text = ', '.join([role.name for role in roles])
            embed_dict = {"title": f"Members for roles: {role_text}",
                          'fields': [
                              {'name': "Members", 'value': (member_text if member_text else 'No member found'), 'inline': False},
                          ],
                          }
            e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name,
                                      avatar_url=self.bot.user.avatar_url,
                                      is_thumbnail=False)
            return await ctx.send(embed=e.to_embed(), delete_after=mid_delay)

        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=mid_delay)

    @role.command(name='list_update', help='List last 10 role update events',
                  usage="Ex: !role list_update", aliases=['l_u'])
    @commands.guild_only()
    async def list_r(self, ctx):
        query = f"""SELECT id, expires, (extra #>> '{{args,1}}') AS tier1to2,
                    (extra #>> '{{args,2}}') AS tier2to3
                    FROM reminders
                    WHERE event = 'role_upgrade'
                    AND extra #>> '{{args,0}}' = $1
                    ORDER BY expires
                    LIMIT 10;
                """
        sent_messages, sent_navs = [ctx.message], []
        try:
            records = await ctx.db.fetch(query, str(ctx.guild.id))

            if len(records) == 0:
                return await ctx.send(f'No role upgrade event has been found.',
                                      delete_after=short_delay)

            embed_dict = {'title': 'Scheduled role upgrades'}

            if len(records) == 10:
                embed_dict['footer'] = {'text': 'Only showing up to 10 role upgrade.'}
            else:
                embed_dict['footer'] = {'text': f'{len(records)} reminder{"s" if len(records) > 1 else ""}'}

            fields, _id_to_row = [], {}
            for index, (_id, expires, _, _) in enumerate(records):
                shorten = textwrap.shorten('Role upgrade', width=512)
                field = {'name': f'**{index+1})** {_id}: In {time.human_timedelta(expires)}', 'value': shorten, 'inline': False}
                fields.append(field)
                _id_to_row[index+1] = _id

            embed_dict['fields'] = fields

            e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name, avatar_url=self.bot.user.avatar_url)
            msg = await ctx.send(embed=e.to_embed())
            sent_messages.append(msg)

            question = 'Please type the row number for check details otherwise type c'
            try:
                id_, msg = await helpers.get_multichoice_answer(self.bot, ctx, _id_to_row, question)
                sent_messages.extend(msg)
            except asyncio.TimeoutError:
                return await ctx.send('Please type in 60 seconds next time.', delete_after=60)

            if id_ is None:
                return await ctx.send('Command has been cancelled.', delete_after=60)

            record = next((record for record in records if record['id'] == id_), None)
            tier1to2 = json.loads(record['tier1to2'])
            tier2to3 = json.loads(record['tier2to3'])
            tier1to2_str = ''.join([f'<@{member_id}>\n' for member_id in tier1to2])
            tier2to3_str = ''.join([f'<@{member_id}>\n' for member_id in tier2to3])
            if tier1to2_str == '':
                tier1to2_str = 'Empty upgrade list_role'

            if tier2to3_str == '':
                tier2to3_str = 'Empty upgrade list_role'
            embed_dict = {'title': 'Role upgrade',
                          'fields': [
                              {'name': f'From: {TIER1} to {TIER2}', 'value': tier1to2_str, 'inline': False},
                              {'name': f'From: {TIER2} to {TIER3}', 'value': tier2to3_str, 'inline': False},
                              {'name': 'Date of removal', 'value': record['expires'].strftime("%Y-%m-%d %H:%M:%S"),
                               'inline': False},
                          ],
                          }
            e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name, avatar_url=self.bot.user.avatar_url)
            return await ctx.send(embed=e.to_embed(), delete_after=mid_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=mid_delay)

#     ********* event handlers ******************
    @commands.Cog.listener()
    async def on_schedule_timer_complete(self, timer):
        """ Scheduled member removal event handler """
        guild_id, member_id_list, _, reason, is_ban, activity_role_id, _ = timer.args
        member_id_list = json.loads(member_id_list)
        await self.bot.wait_until_ready()

        guild = await helpers.get_guild_by_id(self.bot, guild_id)
        if guild is None:
            return log.exception('Guild has not found on scheduled removal event in event handler')

        activity_role = guild.get_role(activity_role_id)
        if activity_role is None:
            return log.exception('Activity role has not found on scheduled removal event in event handler')

        log.info(f'Scheduled member removal event has been started.\n'
                 f'member list: {member_id_list}\n'
                 f'reason: {reason}\n'
                 f'is_ban: {is_ban}')
        reception_channel = await helpers.get_channel_by_id(self.bot, guild, RECEPTION_CHANNEL_ID)
        invite_link = None
        if reception_channel:
            try:
                invite_link = await reception_channel.create_invite(max_use=1,
                                                                    max_age=86400,
                                                                    reason=reason)
            except HTTPException as err:
                log.info(f'Error on creating invitation: {err}')

        query_params = []
        col_list = DiscardedUsers.get_col_names(excluded=['id', 'num_discarded', 'extra'])
        col_names = ', '.join(col_list)
        col_val_placeholder = ', '.join(f'${3 + i}' for i in range(len(col_list)))
        query = f"""INSERT INTO discardedusers AS du (id, num_discarded, {col_names})
                        VALUES ($1, $2, {col_val_placeholder})
                        ON CONFLICT (id)
                        DO UPDATE
                        SET (num_discarded, {col_names}) = ROW(du.num_discarded+1, {col_val_placeholder});
                    """

        global_exception_member_records = await self.fetch_all_exceptions(self.bot.pool, guild.id)
        global_exception_members = [await helpers.get_member_by_id(guild, record['member_id'])
                                    for record in global_exception_member_records]
        global_exception_members = [member for member in global_exception_members if member is not None]

        for member_id in member_id_list:
            member = await helpers.get_member_by_id(guild, member_id)
            if member is not None and activity_role not in member.roles:
                if member not in global_exception_members:
                    top_role_id = member.top_role.id

                    if is_ban:
                        await member.ban(reason=reason)
                    else:
                        # send a rejoin message to a member if kicked
                        if invite_link:
                            rejoin_msg = removed_member_pm_template.format(guild.name, invite_link, 1)
                            try:
                                await member.send(rejoin_msg)
                            except Exception as e:
                                log.info(f'Error on sending invitation link to user: {member.name}\n {e}')

                        await member.kick(reason=reason)

                    query_params.append(
                        (member.id, 1, member.display_name, member.joined_at, datetime.datetime.utcnow(),
                         is_ban, top_role_id, reason))
                else:
                    log.info(f'Member is excluded from removal on event handler: {member.mention}')

        await self.bot.pool.executemany(query, query_params)
        log.info(f'Scheduled removal event created at: {timer.created_at.strftime("%Y-%m-%d %H:%M:%S")} '
                 f'has been executed on: {datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")}\n'
                 f'Expected removal date was: {timer.expires.strftime("%Y-%m-%d %H:%M:%S")}')

    @commands.Cog.listener()
    async def on_role_upgrade_timer_complete(self, timer):
        guild_id, tier1to2, tier2to3 = timer.args
        tier1to2,  tier2to3 = json.loads(tier1to2), json.loads(tier2to3)
        log.info(f'Role upgrade has been started. '
                 f'Updates: {TIER1} to {TIER2}: {tier1to2} | {TIER2} to {TIER3}: {tier2to3} ')
        await self.bot.wait_until_ready()

        guild = await helpers.get_guild_by_id(self.bot, guild_id)
        if guild is None:
            return log.exception(f"No guild has been found for ID: {guild_id} on role upgrade")
        elif not guild.chunked:
            await self.bot.request_offline_members(guild)

        tier1_role = utils.get(guild.roles, name=TIER1)
        tier2_role = utils.get(guild.roles, name=TIER2)
        tier3_role = utils.get(guild.roles, name=TIER3)

        async def switch_role(member_list, from_role, to_role):
            for member_id in member_list:
                member = await helpers.get_member_by_id(guild, member_id)
                if member:
                    await member.add_roles(to_role, reason='Autonomous Role upgrade')
                    await member.remove_roles(from_role, reason='Autonomous Role upgrade')
                    log.info(f'Member: {member.name} role has switched from: {from_role.name} to· {to_role.name}')
                    channel = await helpers.get_channel_by_id(self.bot, guild, ANNOUNCEMENT_CHANNEL_ID)
                    if channel:
                        await channel.send(role_upgrade_template.format(member.mention, from_role.name, to_role.name))

        await switch_role(tier1to2, tier1_role, tier2_role)
        await switch_role(tier2to3, tier2_role, tier3_role)

        return await self.update_roles()

#     ********* autonomous functions ************

    async def update_roles(self):
        query = f"""SELECT *
                    FROM reminders
                    WHERE expires BETWEEN NOW() AND
                    (NOW() + '{str(role_upgrade_gap)}'::interval)
                    AND event = 'role_upgrade'
                    AND extra #>> '{{args,0}}' = $1;
                """
        total = await self.bot.pool.fetchrow(query, str(GUILD_ID))

        if total:
            return log.info(f'There is already schedule role upgrade on date: '
                            f'{total["expires"].strftime("%Y-%m-%d %H:%M:%S")}')

        guild = await helpers.get_guild_by_id(self.bot, GUILD_ID)
        if guild is None:
            return log.exception('Guild is none in update_roles function')

        if not guild.chunked:
            await self.bot.request_offline_members(guild)

        tier1to2, tier2to3 = [], []
        utc_today = datetime.datetime.utcnow()
        role_upgrade_gap_dt = time.FutureTime(role_upgrade_gap)

        for member in guild.members:
            isTier1, isTier2 = False, False
            for role in member.roles:
                if role.name == TIER1:
                    isTier1 = True
                    break

                elif role.name == TIER2:
                    isTier2 = True
                    break

            if isTier1 and (role_upgrade_gap_dt.dt - member.joined_at).days > TIER1toTIER2:
                tier1to2.append(member.id)

            elif isTier2 and (role_upgrade_gap_dt.dt - member.joined_at).days > TIER2toTIER3:
                tier2to3.append(member.id)

        reminder = self.bot.get_cog('Reminder')
        if reminder is None:
            return log.exception('Role upgrade timer has not been handled.')

        if tier1to2 or tier2to3:
            log.info(f'Role upgrade has been scheduled to {role_upgrade_gap_dt.dt}\n'
                     f'Updates: {TIER1} to {TIER2}: {tier1to2} | {TIER2} to {TIER3}: {tier2to3}')
            return await reminder.create_timer(role_upgrade_gap_dt.dt, 'role_upgrade', GUILD_ID,
                                               json.dumps(tier1to2), json.dumps(tier2to3),
                                               connection=self.bot.pool,
                                               created=utc_today)
        else:
            log.info(f'Role upgrade has been checked on : {utc_today.strftime("%Y-%m-%d %H:%M:%S")}. '
                     f'however no role upgrade has been found.')


def setup(bot):
    bot.add_cog(Admin(bot))

