"""Main script to define bot methods, and start the bot."""

import asyncio
import click
import traceback
import importlib
import asyncpg
import sys

import discord

from utils.logger import LOGGER
from utils.db import Table
from utils.config import bot_config
from bot import Qutils, initial_extensions


def run_bot():
    # create bot
    intents = discord.Intents.all()
    bot = Qutils(intents)
    loop = asyncio.get_event_loop()
    bot.log = LOGGER

    try:
        pool = loop.run_until_complete(Table.create_pool(bot_config.db.get_conn_str(), command_timeout=60))
    except Exception as e:
        click.echo('Could not set up PostgreSQL. Exiting.', file=sys.stderr)
        LOGGER.exception('Could not set up PostgreSQL. Exiting.')
        return
    else:
        bot.pool = pool
        bot.loop = loop
        bot.run()


@click.group(invoke_without_command=True, options_metavar='[options]')
@click.pass_context
def main(ctx):
    """Launches the bot."""
    if ctx.invoked_subcommand is None:
        run_bot()


@main.group(short_help='database stuff', options_metavar='[options]')
def db():
    pass


@db.command(short_help='initialises the databases for the bot', options_metavar='[options]')
@click.argument('cogs', nargs=-1, metavar='[cogs]')
@click.option('-q', '--quiet', help='less verbose output', is_flag=True)
def init(cogs, quiet):
    """This manages the migrations and database creation system for you."""
    run = asyncio.get_event_loop().run_until_complete
    try:
        run(Table.create_pool(bot_config.db.get_conn_str()))
    except Exception:
        click.echo(f'Could not create PostgreSQL connection pool.\n{traceback.format_exc()}', err=True)
        return

    if not cogs:
        cogs = initial_extensions

    try:
        load_extensions(cogs)
    except Exception:
        click.echo(f'Extensions are not loaded.\n{traceback.format_exc()}', err=True)
        return

    for table in Table.all_tables():
        try:
            created = run(table.create(verbose=not quiet, run_migrations=False))
        except Exception:
            click.echo(f'Could not create {table.__tablename__}.\n{traceback.format_exc()}', err=True)
        else:
            if created:
                click.echo(f'[{table.__module__}] Table: {table.__tablename__} has been created.')
            else:
                click.echo(f'[{table.__module__}] No work needed for {table.__tablename__}.')


@db.command(short_help='migrates the databases')
@click.argument('cog', nargs=1, metavar='[cog]')
@click.option('-q', '--quiet', help='less verbose output', is_flag=True)
@click.pass_context
def migrate(ctx, cog, quiet):
    """Update the migration file with the newest schema."""

    try:
        load_extensions([cog])
    except Exception:
        return

    def work(table, *, invoked=False):
        try:
            actually_migrated = table.write_migration()
        except RuntimeError as e:
            click.echo(f'Could not migrate {table.__tablename__}: {e}', err=True)
            if not invoked:
                click.confirm('Do you want to create the table?', abort=True)
                ctx.invoke(init, cogs=[cog], quiet=quiet)
                work(table, invoked=True)
            sys.exit(-1)
        else:
            if actually_migrated:
                click.echo(f'Successfully updated migrations for {table.__tablename__}.')
            else:
                click.echo(f'Found no changes for {table.__tablename__}.')

    for table in Table.all_tables():
        work(table)

    click.echo(f'Done migrating {cog}.')


async def apply_migration(cog, quiet, index, *, downgrade=False):
    try:
        pool = await Table.create_pool(bot_config.db.get_conn_str())
    except Exception:
        click.echo(f'Could not create PostgreSQL connection pool.\n{traceback.format_exc()}', err=True)
        return

    try:
        load_extensions([cog])
    except Exception:
        return

    async with pool.acquire() as con:
        tr = con.transaction()
        await tr.start()
        for table in Table.all_tables():
            try:
                await table.migrate(index=index, downgrade=downgrade, verbose=not quiet, connection=con)
            except RuntimeError as e:
                click.echo(f'Could not migrate {table.__tablename__}: {e}', err=True)
                await tr.rollback()
                break
        else:
            await tr.commit()


@db.command(short_help='upgrades from a migration')
@click.argument('cog', nargs=1, metavar='[cog]')
@click.option('-q', '--quiet', help='less verbose output', is_flag=True)
@click.option('--index', help='the index to use', default=-1)
def upgrade(cog, quiet, index):
    """Runs an upgrade from a migration"""
    run = asyncio.get_event_loop().run_until_complete
    run(apply_migration(cog, quiet, index))


@db.command(short_help='downgrades from a migration')
@click.argument('cog', nargs=1, metavar='[cog]')
@click.option('-q', '--quiet', help='less verbose output', is_flag=True)
@click.option('--index', help='the index to use', default=-1)
def downgrade(cog, quiet, index):
    """Runs an downgrade from a migration"""
    run = asyncio.get_event_loop().run_until_complete
    run(apply_migration(cog, quiet, index, downgrade=True))


async def remove_tables(pool, cog, quiet):
    async with pool.acquire() as con:
        tr = con.transaction()
        await tr.start()
        for table in Table.all_tables():
            try:
                await table.drop(verbose=not quiet, connection=con)
            except RuntimeError as e:
                click.echo(f'Could not drop {table.__tablename__}: {e}', err=True)
                await tr.rollback()
                break
            else:
                click.echo(f'Dropped {table.__tablename__}.')
        else:
            await tr.commit()
            click.echo(f'successfully removed {cog} tables.')


@db.command(short_help="removes a cog's table", options_metavar='[options]')
@click.argument('cog', metavar='<cog>')
@click.option('-q', '--quiet', help='less verbose output', is_flag=True)
def drop(cog, quiet):
    """This removes a database and all its migrations.

    You must be pretty sure about this before you do it,
    as once you do it there's no coming back.

    You need to give the cog name.
    """

    run = asyncio.get_event_loop().run_until_complete
    click.confirm('do you really want to do this?', abort=True)

    try:
        pool = run(Table.create_pool(bot_config.db.get_conn_str()))
    except Exception:
        click.echo(f'Could not create PostgreSQL connection pool.\n{traceback.format_exc()}', err=True)
        return

    try:
        cog = load_extensions([cog])[0]
    except Exception:
        return

    run(remove_tables(pool, cog, quiet))


@main.command(short_help='migrates from JSON files')
@click.argument('cogs', nargs=-1)
@click.pass_context
def convertjson(ctx, cogs):
    """This migrates our older JSON files to PostgreSQL

    Note, this deletes all previous entries in the table
    so you can consider this to be a destructive decision.

    Do not pass in cog names with "cogs." as a prefix.

    This also connects us to Discord itself so we can
    use the cache for our migrations.

    The point of this is just to do some migration of the
    data from v3 -> v4 once and call it a day.
    """

    import data_migrators

    run = asyncio.get_event_loop().run_until_complete

    if not cogs:
        to_run = [(getattr(data_migrators, attr), attr.replace('migrate_', ''))
                  for attr in dir(data_migrators) if attr.startswith('migrate_')]
    else:
        to_run = []
        for cog in cogs:
            try:
                elem = getattr(data_migrators, 'migrate_' + cog)
            except AttributeError:
                click.echo(f'invalid cog name given, {cog}.', err=True)
                return

            to_run.append((elem, cog))

    async def make_pool():
        return await asyncpg.create_pool(bot_config.db.get_conn_str())

    try:
        pool = run(make_pool())
    except Exception:
        click.echo(f'Could not create PostgreSQL connection pool.\n{traceback.format_exc()}', err=True)
        return

    client = discord.AutoShardedClient()

    @client.event
    async def on_ready():
        click.echo(f'successfully booted up bot {client.user} (ID: {client.user.id})')
        await client.logout()

    try:
        run(client.login(bot_config.auth.token))
        run(client.connect(reconnect=False))
    except:
        pass

    extensions = ['cogs.' + name for _, name in to_run]
    ctx.invoke(init, cogs=extensions)

    for migrator, _ in to_run:
        try:
            run(migrator(pool, client))
        except Exception:
            click.echo(f'[error] {migrator.__name__} has failed, terminating\n{traceback.format_exc()}', err=True)
            return
        else:
            click.echo(f'[{migrator.__name__}] completed successfully')


def load_extensions(cogs):
    cogs_name = []

    for ext in cogs:
        if not ext.startswith('cogs.'):
            ext = f'cogs.{ext}'
            cogs_name.append(ext)
        try:
            importlib.import_module(ext)
        except Exception as e:
            click.echo(f'Could not load {ext}.\n{traceback.format_exc()}', err=True)
            raise e
    return cogs_name


if __name__ == '__main__':
    main()
