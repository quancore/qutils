import textwrap
import ast
import typing
from discord import Member, Role, Embed, Colour, File, utils
from discord.ext import commands
from utils import db, formats
import logging
from collections import defaultdict
import datetime
import asyncio
import json
from libneko import pag


from config import GUILD_ID, ACTIVITY_ROLE_NAME, ACTIVITY_INCLUDED_ROLES, \
    activity_schedule_gap, activity_min_day, activity_template, role_upgrade_template, \
    ANNOUNCEMENT_CHANNEL_ID, LOGGING_CHANNEL_ID, role_upgrade_gap, \
    TIER1, TIER1toTIER2, TIER2, TIER2toTIER3, TIER3
from utils import permissions, time
from utils.formats import CustomEmbed

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


class Admin(commands.Cog):
    """
    Admin functionality
    """

    def __init__(self, bot):
        self.bot = bot

    async def cleanup_schedule(self):
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
        guild = self.bot.get_guild(GUILD_ID)

        reminder = self.bot.get_cog('Reminder')
        if reminder is None:
            channel = guild.get_channel(ANNOUNCEMENT_CHANNEL_ID)
            return await channel.send('Sorry, this functionality is currently unavailable. Please try again later')

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
                exceptions = [guild.get_member(member_id) for member_id in exception_ids]
                included_roles = json.loads(row['included_roles'])
                log.info(exceptions)
                inactive_members, member_text = await Admin.get_inactive_members(guild, included_roles,
                                                                                 activity_role, exceptions)
                activity_template_final = activity_template.format(expire_date.strftime("%Y-%m-%d %H:%M:%S"))
                embed_dict = {'title': activity_template_final,
                              'fields': [{'name': 'Members will be discarded', 'value': member_text, 'inline': False}, ]
                              }
                await guild.get_channel(ANNOUNCEMENT_CHANNEL_ID).send(embed=Embed.from_dict(embed_dict))
                await reminder.create_timer(expire_date, 'schedule', GUILD_ID,
                                            json.dumps(inactive_members), row['exceptions'], row['reason'],
                                            row['is_ban'], row['role_id'], row['included_roles'],
                                            connection=self.bot.pool,
                                            created=datetime.datetime.utcnow())

                log.info(f'The event has been rescheduled in autonomous function for '
                         f'{expire_date.strftime("%Y-%m-%d %H:%M:%S")}.')
            else:
                log.info(f'There is already scheduled removal on {total["expires"].strftime("%Y-%m-%d %H:%M:%S")}, '
                         f'so autonomous function could not schedule a new removal.')

    @commands.Cog.listener()
    async def on_ready(self):
        # pass
        # self.bot.loop.run_until_complete(self.update_roles())
        asyncio.ensure_future(self.cleanup_schedule(), loop=self.bot.loop)
        asyncio.ensure_future(self.update_roles(), loop=self.bot.loop)

    async def cog_command_error(self, ctx, error):
        if isinstance(error, commands.BadArgument):
            log.exception(error)
            await ctx.send(error)

    @commands.group(name='discard', help='Command group for discarding members',
                    usage='This is not a command but a command group.', hidden=True)
    async def discard(self, ctx):
        pass

    @discard.command(name='by_role', help='Kick / ban all members with a given role',
                     usage='@role_mention [optional True for ban/ False for Kick] '
                           '[optional Exception members: @member_mentions]\n'
                           'Ex: !discard by_role @Yabancilar True @abc @abd')
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True, kick_members=True, ban_members=True)
    async def by_role(self, ctx, role: Role, is_ban: typing.Optional[bool] = False,
                      exceptions: commands.Greedy[Member] = None,
                      *, reason: str = 'Discharged due to inactivity'):
        if exceptions is None:
            exceptions = []

        if role is None:
            await self.cog_command_error(ctx, commands.BadArgument('Role name is not valid'))
            return

        guild = ctx.guild
        valid_members = []
        query_params = []
        member_text = ''
        exception_member_text = ''
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
                                 {'name': 'Member list', 'value': member_text, 'inline': False},
                                 {'name': 'Exceptions', 'value': exception_member_text, 'inline': False},
                                 {'name': 'Reason', 'value': reason, 'inline': False},
                                 ],
                      }
        e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name, avatar_url=self.bot.user.avatar_url)
        await ctx.send(embed=e.to_embed())

        confirm = await ctx.prompt("Are you sure you want to handle operation?")
        log.exception(query)
        if confirm:
            for member in valid_members:
                if is_ban:
                    await member.ban(reason=reason)
                else:
                    await member.kick(reason=reason)

            await ctx.db.executemany(query, query_params)

            return await ctx.send('Operation has successfully finished.')

    @discard.command(name='fetch', help='Display all discarded users\n',
                     usage='Ex: !discard fetch [optional True for csv file]')
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True, kick_members=True, ban_members=True)
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

        records = await ctx.db.fetch(query)
        if len(records) == 0:
            return await ctx.send('No results found...')

        # e = Embed(colour=0xF02D7D)
        # data = defaultdict(list)

        # for record in records:
        #     for key, value in record.items():
        #         data[key].append(value if value else 'N/A')
        #
        # num_chars = 0
        # for key, values in data.items():
        #     e.add_field(name=key, value='\n'.join(map(str, values)))

        # a hack to allow multiple inline fields
        # e.set_footer(text=format(formats.plural(len(records)), 'record') + '\u2003' * 100 + '\u200b')
        # nav = pag.EmbedNavigatorFactory(factory=formats.EmbedGenerator({}), max_lines=10)
        # nav += data.render()
        # nav = pag.EmbedNavigatorFactory(max_lines=20)
        nav = pag.StringNavigatorFactory(max_lines=20, enable_truncation=False)
        data = formats.TabularData(nav.line_break)
        table_columns = ["User", "Num. discarded", "Joined", "Discarded", "Type", "Role", "Reason"]
        data.set_columns(table_columns)
        data.add_rows(records, [1])
        print(data.render())
        nav.prefix = data.get_column_str()

        # Insert the dummy text into our factory.
        nav += data.render(render_column=False)
        nav.start(ctx)

        if to_csv:
            f = data.to_csv(["ID", "Nickname", "Num. discarded", "Joined", "Discarded", "Type", "Role", "Reason"])
            await ctx.channel.send(content="Removed users CSV file", file=File(fp=f, filename="removed_user_info.txt"))

    @discard.command(name='clear', help='Remove all removed user records',
                     usage="Ex: !discard clear")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True, kick_members=True, ban_members=True)
    async def clear_d(self, ctx):
        query = """TRUNCATE discardedusers;"""
        confirm = await ctx.prompt('Are you sure you want to delete all records?')
        if not confirm:
            return await ctx.send('Operation has been aborted.')

        status = await ctx.db.execute(query)
        if status == 'DELETE 0':
            return await ctx.send('Could not delete any event with that ID.')

        await ctx.send('Successfully deleted all records.')

    @commands.group(name='schedule', help='Command group for scheduling member removal',
                    usage='This is not a command but a command group.', hidden=True)
    async def schedule(self, ctx):
        pass

    @staticmethod
    async def get_inactive_members(guild, included_roles, activity_role, exceptions):
        valid_members = []
        member_text = ''

        for member in guild.members:
            member_delta = datetime.datetime.utcnow() - member.joined_at
            is_active = is_included = False
            if member not in exceptions and member_delta.days > activity_min_day:
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

    @schedule.command(name='create', help='Schedule an removal event based on activity role',
                      usage='duration [optional included roles: @role_mention]'
                            '[True for ban/ False for Kick] '
                            '[optional Exception members: @member_mentions] [optional reason]\n'
                            'Example durations: 30d, "until thursday at 3PM", "2024-12-31"'
                            'Note that times are in UTC.\n\n'
                            "Ex: !schedule create 10d @Çaylaklar False @abc @abd 'ban due to inactivity'")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True, kick_members=True, ban_members=True)
    async def create(self, ctx, duration: time.FutureTime,
                     included_roles: commands.Greedy[Role] = None,
                     is_ban: typing.Optional[bool] = False,
                     exceptions: commands.Greedy[Member] = None,
                     *, reason: str = 'Discharged on scheduled removal'):

        guild = ctx.guild

        # first check whether another scheduled removal exists within a day range
        query = f"""SELECT *
                    FROM reminders
                    WHERE '{duration.dt}'::date BETWEEN (expires - '{str(activity_schedule_gap)} days'::interval) AND 
                    (expires + '{str(activity_schedule_gap)} days'::interval)
                    AND event = 'schedule'
                    AND extra #>> '{{args,0}}' = $1;
                """
        # total = await ctx.db.fetchrow(query, str(guild.id))
        total = await self.bot.pool.fetchrow(query, str(guild.id))
        if total:
            return await ctx.send(f'There is already a scheduled event has the time gap less than {activity_schedule_gap} days')

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

        guild = ctx.guild
        exception_member_text = ''.join(f'{member.mention}\n' for member in exceptions)

        valid_members, member_text = await Admin.get_inactive_members(guild, included_roles,
                                                                      activity_role, exceptions)

        if exception_member_text is '':
            exception_member_text = 'No exception member'

        if member_text is '':
            member_text = 'No member will be discarded'

        included_role_text = ', '.join([role for role in included_roles])
        embed_dict = {'title': 'Operation summary', 'colour': Colour.red(),
                      'fields': [{'name': "Operation type", 'value': 'Ban' if is_ban else 'Kick', 'inline': False},
                                 {'name': "Included Roles", 'value': included_role_text, 'inline': False},
                                 {'name': 'Members will be discarded', 'value': member_text, 'inline': False},
                                 {'name': 'Date of removal', 'value': duration.dt.strftime("%Y-%m-%d %H:%M:%S"), 'inline': False},
                                 {'name': 'Exceptions', 'value': exception_member_text, 'inline': False},
                                 {'name': 'Reason', 'value': reason, 'inline': False},
                                 ],
                      }
        # await ctx.send(embed=Embed.from_dict(embed_dict))
        embed_factory = formats.EmbedGenerator(embed_dict, author_name=ctx.author.name,
                                               avatar_url=self.bot.user.avatar_url)
        nav = pag.EmbedNavigatorFactory(factory=embed_factory, max_lines=10)
        nav += 'Confirmation screen'
        nav.start(ctx)
        confirm = await ctx.prompt("Are you sure to schedule the event?")
        if confirm:
            activity_template_final = activity_template.format(duration.dt.strftime("%Y-%m-%d %H:%M:%S"))
            embed_dict = {'title': activity_template_final,
                          'fields': [{'name': 'Members will be discarded', 'value': member_text, 'inline': False},]
                          }
            await guild.get_channel(ANNOUNCEMENT_CHANNEL_ID).send(embed=Embed.from_dict(embed_dict))
            reminder = self.bot.get_cog('Reminder')
            if reminder is None:
                return await ctx.send('Sorry, this functionality is currently unavailable. Please try again later')

            exception_ids = [member.id for member in exceptions]
            await reminder.create_timer(duration.dt, 'schedule', ctx.guild.id,
                                        json.dumps(valid_members), json.dumps(exception_ids),
                                        reason, is_ban, activity_role.id, json.dumps(included_roles),
                                        connection=ctx.db,
                                        created=ctx.message.created_at)
            await ctx.send(f'The event has been scheduled for {duration.dt.strftime("%Y-%m-%d %H:%M:%S")}.')
        else:
            return await ctx.send('Operation has been cancelled.')

    @schedule.command(name='delete', help='Delete a scheduled event with id',
                      usage="Run schedule_list command to get currently queued events"
                            "Ex: !schedule delete id")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True, kick_members=True, ban_members=True)
    async def delete(self, ctx, id: int):
        query = """DELETE FROM reminders
                    WHERE id=$1
                    AND event = 'schedule';
                """
        confirm = await ctx.prompt('Are you sure you want to delete the record?')
        if not confirm:
            return await ctx.send('Operation has been aborted.')

        status = await ctx.db.execute(query, id)
        if status == 'DELETE 0':
            return await ctx.send('Could not delete any event with that ID.')

        await ctx.send('Successfully deleted scheduled event.')

    @schedule.command(name='clear', help='Delete all scheduled events',
                      usage="Ex: !schedule clear")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True, kick_members=True, ban_members=True)
    async def clear(self, ctx):
        # For UX purposes this has to be two queries.

        query = """SELECT COUNT(*)
                    FROM reminders
                    WHERE event = 'schedule';
                """

        total = await ctx.db.fetchrow(query)
        total = total[0]
        if total == 0:
            return await ctx.send('You do not have any schedule events to delete.')

        confirm = await ctx.prompt(f'Are you sure you want to delete {formats.Plural(total):scheduled events}?')
        if not confirm:
            return await ctx.send('Operation has been aborted.')

        query = """DELETE FROM reminders WHERE event = 'schedule';"""
        await ctx.db.execute(query)

        return await ctx.send(f'Successfully deleted {formats.Plural(total):scheduled events}.')

    @schedule.command(name='list', help='List last 10 scheduled events',
                      usage="Ex: !schedule list")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True, kick_members=True, ban_members=True)
    async def list(self, ctx):
        query = f"""SELECT id, expires, (extra #>> '{{args,1}}') AS members, extra #>> '{{args,2}}' AS exceptions, 
                    extra #>> '{{args,3}}' AS reason, 
                    (extra #>> '{{args,4}}')::boolean AS is_ban
                    FROM reminders
                    WHERE event = 'schedule'
                    AND extra #>> '{{args,0}}' = $1
                    ORDER BY expires
                    LIMIT 10;
                    """
        guild = ctx.guild
        records = await ctx.db.fetch(query, str(guild.id))

        if len(records) == 0:
            return await ctx.send(f'No scheduled event has been found.')

        embed_dict = {'title': 'Scheduled removals'}

        if len(records) == 10:
            embed_dict['footer'] = {'text': 'Only showing up to 10 reminders.'}
        else:
            embed_dict['footer'] = {'text': f'{len(records)} reminder{"s" if len(records) > 1 else ""}'}

        fields = []
        for _id, expires, _, _, reason, _ in records:
            shorten = textwrap.shorten(reason, width=512)
            field = {'name': f'{_id}: In {time.human_timedelta(expires)}', 'value': shorten, 'inline': False}
            fields.append(field)

        embed_dict['fields'] = fields

        e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name, avatar_url=self.bot.user.avatar_url)
        await ctx.send(embed=e.to_embed())

        max_record_id = max(records, key=lambda x: x['id'])['id']

        def representsInt(s):
            try:
                s = int(s)
                return s
            except ValueError:
                return -1

        def check(m):
            input_checker = m.content == 'c' or (0 < representsInt(m.content) <= max_record_id)
            return input_checker and m.channel == ctx.channel

        await ctx.send('Please type the row number for check details otherwise type c')

        try:
            msg = await self.bot.loop.create_task(self.bot.wait_for('message', check=check, timeout=60))
        except asyncio.TimeoutError as e:
            log.exception('Input timeout error', exc_info=True)
            return await ctx.send('Please type in 60 seconds next time.')
        else:
            id_ = representsInt(msg.content)
            if id_ > 0:
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
                await ctx.send(embed=e.to_embed())
            else:
                await ctx.send('Command has been cancelled.')

    @commands.Cog.listener()
    async def on_schedule_timer_complete(self, timer):
        guild_id, member_id_list, _, reason, is_ban, activity_role_id, _ = timer.args
        member_id_list = json.loads(member_id_list)
        await self.bot.wait_until_ready()

        guild = self.bot.get_guild(guild_id)
        activity_role = guild.get_role(activity_role_id)
        if guild is None:
            # RIP
            return log.exception('Guild has not found')

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

        for member_id in member_id_list:
            member = guild.get_member(member_id)
            if activity_role not in member.roles:
                top_role_id = member.top_role.id

                if is_ban:
                    await member.ban(reason=reason)
                else:
                    await member.kick(reason=reason)

                query_params.append(
                    (member.id, 1, member.display_name, member.joined_at, datetime.datetime.utcnow(),
                     is_ban, top_role_id, reason))

        await self.bot.pool.executemany(query, query_params)


#     ********* autonomous functions ************
    @commands.group(name='role', help='Command group for discarding members',
                    usage='This is not a command but a command group.', hidden=True)
    async def role(self, ctx):
        pass

    @role.command(name='list', help='List last 10 role update events',
                  usage="Ex: !role list")
    @commands.guild_only()
    @commands.has_permissions(manage_roles=True, kick_members=True, ban_members=True)
    async def list_r(self, ctx):
        query = f"""SELECT id, expires, (extra #>> '{{args,1}}') AS tier1to2,
                    (extra #>> '{{args,2}}') AS tier2to3
                    FROM reminders
                    WHERE event = 'role_upgrade'
                    AND extra #>> '{{args,0}}' = $1
                    ORDER BY expires
                    LIMIT 10;
                """

        records = await ctx.db.fetch(query, str(ctx.guild.id))

        if len(records) == 0:
            return await ctx.send(f'No role upgrade event has been found.')

        embed_dict = {'title': 'Scheduled removals'}

        if len(records) == 10:
            embed_dict['footer'] = {'text': 'Only showing up to 10 role upgrade.'}
        else:
            embed_dict['footer'] = {'text': f'{len(records)} reminder{"s" if len(records) > 1 else ""}'}

        fields = []
        for _id, expires, _, _ in records:
            shorten = textwrap.shorten('Role upgrade', width=512)
            field = {'name': f'{_id}: In {time.human_timedelta(expires)}', 'value': shorten, 'inline': False}
            fields.append(field)

        embed_dict['fields'] = fields

        e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name, avatar_url=self.bot.user.avatar_url)
        await ctx.send(embed=e.to_embed())

        max_record_id = max(records, key=lambda x: x['id'])['id']

        def representsInt(s):
            try:
                s = int(s)
                return s
            except ValueError:
                return -1

        def check(m):
            input_checker = m.content == 'c' or (0 < representsInt(m.content) <= max_record_id)
            return input_checker and m.channel == ctx.channel

        await ctx.send('Please type the row number for check details otherwise type c')

        try:
            msg = await self.bot.loop.create_task(self.bot.wait_for('message', check=check, timeout=60))
        except asyncio.TimeoutError as e:
            log.exception('Input timeout error', exc_info=True)
            return await ctx.send('Please type in 60 seconds next time.')
        else:
            id_ = representsInt(msg.content)
            if id_ > 0:
                record = next((record for record in records if record['id'] == id_), None)
                tier1to2 = json.loads(record['tier1to2'])
                tier2to3 = json.loads(record['tier2to3'])
                tier1to2_str = ''.join([f'<@{member_id}>\n' for member_id in tier1to2])
                tier2to3_str = ''.join([f'<@{member_id}>\n' for member_id in tier2to3])
                if tier1to2_str == '':
                    tier1to2_str = 'Empty upgrade list'

                if tier2to3_str == '':
                    tier2to3_str = 'Empty upgrade list'
                embed_dict = {'title': 'Role upgrade',
                              'fields': [
                                  {'name': f'From: {TIER1} to {TIER2}', 'value': tier1to2_str, 'inline': False},
                                  {'name': f'From: {TIER2} to {TIER3}', 'value': tier2to3_str, 'inline': False},
                                  {'name': 'Date of removal', 'value': record['expires'].strftime("%Y-%m-%d %H:%M:%S"),
                                   'inline': False},
                              ],
                              }
                e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name, avatar_url=self.bot.user.avatar_url)
                await ctx.send(embed=e.to_embed())
            else:
                await ctx.send('Command has been cancelled.')

    async def update_roles(self):
        query = f"""SELECT *
                    FROM reminders
                    WHERE expires BETWEEN NOW() AND
                    (NOW() + '{str(role_upgrade_gap)}'::interval)
                    AND event = 'role_upgrade'
                    AND extra #>> '{{args,0}}' = $1;
                """
        total = await self.bot.pool.fetchrow(query, str(GUILD_ID))
        log.info(total)
        if total:
            return log.info('There is already schedule role upgrade')

        guild = self.bot.get_guild(GUILD_ID)
        if not guild.chunked:
            await self.bot.request_offline_members(guild)

        tier1to2, tier2to3 = [], []
        utc_today = datetime.datetime.utcnow()
        role_upgrade_gap_dt = time.FutureTime(role_upgrade_gap)

        log.info(role_upgrade_gap_dt.dt)
        for member in guild.members:
            isTier1, isTier2 = False, False
            for role in member.roles:
                if role.name == TIER1:
                    isTier1 = True
                    break

                elif role.name == TIER2:
                    isTier2 = True
                    break

            if isTier1 and (utc_today - member.joined_at).days > TIER1toTIER2:
                tier1to2.append(member.id)

            elif isTier2 and (utc_today - member.joined_at).days > TIER2toTIER3:
                tier2to3.append(member.id)

        reminder = self.bot.get_cog('Reminder')
        if reminder is None:
            return log.exception('Role upgrade timer has not been handled.')

        return await reminder.create_timer(role_upgrade_gap_dt.dt, 'role_upgrade', GUILD_ID,
                                           json.dumps(tier1to2), json.dumps(tier2to3),
                                           connection=self.bot.pool,
                                           created=utc_today)

    @commands.Cog.listener()
    async def on_role_upgrade_timer_complete(self, timer):
        log.info('Role update has been started')
        guild_id, tier1to2, tier2to3 = timer.args
        tier1to2,  tier2to3 = json.loads(tier1to2), json.loads(tier2to3)
        await self.bot.wait_until_ready()

        guild = self.bot.get_guild(guild_id)
        if guild is None:
            # RIP
            return
        elif not guild.chunked:
            await self.bot.request_offline_members(guild)

        tier1_role = utils.get(guild.roles, name=TIER1)
        tier2_role = utils.get(guild.roles, name=TIER2)
        tier3_role = utils.get(guild.roles, name=TIER3)

        async def switch_role(member_list, from_role, to_role):
            for member_id in member_list:
                member = guild.get_member(member_id)
                await member.add_roles(to_role, reason='Autonomous Role upgrade')
                await member.remove_roles(from_role, reason='Autonomous Role upgrade')
                log.info(f'Member: {member.name} role has switched from: {from_role.name} to· {to_role.name}')
                await guild.get_channel(ANNOUNCEMENT_CHANNEL_ID).\
                    send(role_upgrade_template.format(member.mention, from_role.name, to_role.name))

        await switch_role(tier1to2, tier1_role, tier2_role)
        await switch_role(tier2to3, tier2_role, tier3_role)

        return await self.update_roles()


def setup(bot):
    bot.add_cog(Admin(bot))
