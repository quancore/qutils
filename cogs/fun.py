from discord.ext import commands
from discord import utils, File, Member

from config import TENOR_API_KEY, VALID_STATS_ROLES, short_delay, mid_delay, long_delay
from utils import helpers
from utils.formats import CustomEmbed



from urllib.parse import urlencode
import asyncio
import io
import functools
# import pprint
from libneko import pag
from utils.formats import CustomEmbed
import googletrans
from PIL import Image
import requests
import random


class Fun(commands.Cog):
    base_tdk_url = "https://sozluk.gov.tr/gts"
    base_random_tenor_url = "https://api.tenor.com/v1/random?"
    base_search_tenor_url = "https://api.tenor.com/v1/search?"

    def __init__(self, bot):
        self.bot = bot
        self.trans = googletrans.Translator()

    # get a word meaning from Turkish Language Foundation
    @commands.command(name='tdk', help='Search a word meaning from TDK',
                      usage='phase \n For multiple words, use "...."')
    @commands.guild_only()
    @commands.cooldown(rate=1, per=1.5, type=commands.BucketType.user)
    @commands.has_any_role(*VALID_STATS_ROLES)
    async def tdk(self, ctx, *, phase: commands.clean_content):
        def get_str_from_list(list_of_dict, key, separator=', '):
            """ Get a key's value from given fetch_schedule of dicts as a separator concatenated """
            if list_of_dict is None:
                return ''

            return separator.join([_dict.get(key, '') for _dict in list_of_dict]).strip()

        sent_messages, sent_navs = [ctx.message], []
        try:
            params = {'ara': phase}
            resp = requests.get(url=self.base_tdk_url, params=params)
            resp_struct = resp.json()
            is_error = isinstance(resp_struct, dict) and resp_struct.get('error', None) is not None

            if len(resp_struct) > 0 and not is_error:
                nav = pag.EmbedNavigatorFactory(max_lines=20)
                nav.add_line(f'📚__**{phase}** kelimesinin anlami__\n')
                meanings_dict = resp_struct[0]
                # pprint.pprint(meanings_dict)
                meanings = meanings_dict.get('anlamlarListe', [])
                other_language = meanings_dict.get('lisan', '')
                if other_language != '':
                    nav.add_line(f'`{other_language}` \n')

                for index, meaning in enumerate(meanings):
                    # pprint.pprint(meaning)
                    # pprint.pprint('---------')
                    examples = meaning.get('orneklerListe', [])
                    properties = meaning.get('ozelliklerListe', [])
                    example_str = ''
                    properties_str = get_str_from_list(properties, 'tam_adi')
                    for example in examples:
                        example_quota_str = f"{example.get('ornek', '')}"
                        example_writer_str = ''
                        example_writer = example.get('yazar', [])
                        if example_writer:
                            example_writer = example_writer[0]
                            example_writer_str = f"{example_writer.get('tam_adi', '')}"
                        if example_quota_str != '' and example_writer_str != '':
                            example_str += f'\n--> "{example_quota_str}" - **{example_writer_str}**'

                    overall_str = f'**{index + 1}.** '
                    if properties_str:
                        overall_str += f'`{properties_str}` '
                    meaning_str = f"{meaning['anlam']}." if example_str == '' else f"{meaning['anlam']}:"
                    overall_str += meaning_str
                    if example_str:
                        overall_str += f'{example_str}'
                    # overall_str += '```'
                    nav.add_line(overall_str)
                    # nav.add_line('**-----------------------------**')
                    # pprint.pprint(meaning)

                emb_nav = nav.build(ctx=ctx)
                emb_nav.start()
                sent_navs.append(emb_nav)
            else:
                await ctx.send(f'We could not found a meaning for **{phase}**', delete_after=short_delay)

        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=mid_delay)

    @commands.command(name='cat', help='Get a random cat image')
    @commands.cooldown(rate=1, per=1.5, type=commands.BucketType.user)
    @commands.has_any_role(*VALID_STATS_ROLES)
    async def cat(self, ctx):
        """Gives you a random cat."""
        sent_messages = [ctx.message]
        try:
            async with ctx.session.get('https://api.thecatapi.com/v1/images/search') as resp:
                if resp.status != 200:
                    return await ctx.send('No cat found :(')
                js = await resp.json()
                embed_dict = {'title': 'Random cat'}
                e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name).set_image(url=js[0]['url'])
                msg = await ctx.send(embed=e.to_embed())
                sent_messages.append(msg)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=mid_delay)

    @commands.command(name='dog', help='Get a random cat image')
    @commands.cooldown(rate=1, per=1.5, type=commands.BucketType.user)
    @commands.has_any_role(*VALID_STATS_ROLES)
    async def dog(self, ctx):
        """Gives you a random dog."""
        sent_messages = [ctx.message]
        try:
            async with ctx.session.get('https://random.dog/woof') as resp:
                if resp.status != 200:
                    return await ctx.send('No dog found :(')

                filename = await resp.text()
                url = f'https://random.dog/{filename}'
                filesize = ctx.guild.filesize_limit if ctx.guild else 8388608
                if filename.endswith(('.mp4', '.webm')):
                    async with ctx.typing():
                        async with ctx.session.get(url) as other:
                            if other.status != 200:
                                return await ctx.send('Could not download dog video :(')

                            if int(other.headers['Content-Length']) >= filesize:
                                return await ctx.send(f'Video was too big to upload... See it here: {url} instead.',
                                                      delete_after=short_delay)

                            fp = io.BytesIO(await other.read())
                            await ctx.send(file=File(fp, filename=filename))
                else:
                    embed_dict = {'title': 'Random dog'}
                    e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name).set_image(url=url)
                    msg = await ctx.send(embed=e)
                    sent_messages.append(msg)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=mid_delay)

    @commands.command(name='duck', help='Get a random duck image')
    @commands.cooldown(rate=1, per=1.5, type=commands.BucketType.user)
    async def duck(self, ctx):
        """ Posts a random duck """
        sent_messages = [ctx.message]
        try:
            async with ctx.session.get('https://random-d.uk/api/v1/random') as resp:
                if resp.status != 200:
                    return await ctx.send('No duck found :(')

                json = await resp.json()
                embed_dict = {'title': 'Random duck'}
                e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name).set_image(url=json['url'])
                msg = await ctx.send(embed=e)
                sent_messages.append(msg)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=mid_delay)

    @commands.command(name='translate', help='Translate a text from a language to a language',
                      usage='<translation_text>\n\n'
                            'translation_text: str, required - Text to be translated\n\n'
                            'Ex: !translate dün cok yemek yedim')
    @commands.has_any_role(*VALID_STATS_ROLES)
    async def translate(self, ctx, *, message: commands.clean_content):
        """Translates a message to another language using Google translate."""

        def check_message(m):
            if m.author.id != ctx.author.id:
                return False
            if m.channel != ctx.channel:
                return False

            _given_codes = m.content.split(',')
            is_source_valid, is_dest_valid = False, False
            if len(_given_codes) == 2:
                is_source_valid = "-" or googletrans.LANGUAGES.get(_given_codes[0]) is not None
                is_dest_valid = "-" or googletrans.LANGUAGES.get(_given_codes[1]) is not None

            check_res = m.content == 'c' or (is_source_valid and is_dest_valid)

            return check_res

        sent_messages, sent_navs = [ctx.message], []
        try:
            nav = pag.EmbedNavigatorFactory(max_lines=20)
            nav.add_line('**Language with codes**')
            for k, v in googletrans.LANGUAGES.items():
                nav.add_line(f'**{k}**: {v}')

            emb_nav = nav.build(ctx=ctx)
            emb_nav.start()
            sent_navs.append(emb_nav)

            question = '**Valid languages with language code has been given above.**\n' \
                       '**Please enter your source and destination language code with comma separated.**\n' \
                       'If you provide "-" as source language, it will be tried to determine automatically\n' \
                       'If you provide "-" as destination language, it will translate to english\n' \
                       'Ex: en,ko    de,fr   -,en   de,-\n' \
                       'Type "c" to cancel '

            msg = await ctx.channel.send(question)
            sent_messages.append(msg)

            try:
                lang_msg = await self.bot.wait_for("message",
                                                    check=check_message,
                                                    timeout=240)
            except asyncio.TimeoutError:
                return await ctx.channel.send("Command has been timeout", delete_after=short_delay)
            else:
                if lang_msg.content == "c":
                   return await ctx.send('Command has been cancelled', delete_after=short_delay)

            given_codes = lang_msg.content.split(',')
            src = googletrans.LANGUAGES.get(given_codes[0]) or "auto"
            dest = googletrans.LANGUAGES.get(given_codes[1]) or "en"
            try:
                ret = await self.bot.loop.run_in_executor(None, functools.partial(self.trans.translate,
                                                                                  message, src=src, dest=dest)
                                                          )
            except Exception as e:
                return await ctx.send(f'An error occurred: {e.__class__.__name__}: {e}', delete_after=short_delay)

            embed_dict = {'title': 'Translation',
                          'fields': [{'name': f'From {googletrans.LANGUAGES.get(ret.src, "Automated").title()}',
                                      'value': ret.origin, 'inline': False},
                                     {'name': f'To {googletrans.LANGUAGES.get(ret.dest, "Unknown").title() }',
                                      'value': ret.text, 'inline': False}
                          ]}
            e = CustomEmbed.from_dict(embed_dict, author_name=ctx.author.name)
            msg = await ctx.send(embed=e)
            sent_messages.append(msg)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=long_delay)

    @commands.command(name='urban', help='Get the best definition of a English word',
                      usage='<word>\n\n'
                            'word: str, required - Word or phase\n\n'
                            'Ex: !urban book')
    @commands.cooldown(rate=1, per=2.0, type=commands.BucketType.user)
    @commands.has_any_role(*VALID_STATS_ROLES)
    async def urban(self, ctx, *, search: commands.clean_content):
        """ Find the 'best' definition to your words """
        sent_messages, sent_navs = [ctx.message], []
        try:
            async with ctx.session.get(f'https://api.urbandictionary.com/v0/define?term={search}') as resp:
                if resp.status != 200:
                    return await ctx.send('No definition found :(', delete_after=short_delay)

                json = await resp.json()

                if not json:
                    return await ctx.send("I think the API broke...", delete_after=short_delay)

                if not len(json['list']):
                    return await ctx.send("Couldn't find your search in the dictionary...", delete_after=short_delay)

                results = sorted(json['list'], reverse=True, key=lambda g: int(g["thumbs_up"]))

                nav = pag.EmbedNavigatorFactory(max_lines=40)
                nav.add_line(f'📚__Definitions for **{results[0]["word"]}**__\n')
                for res in results:
                    definition = res.get('definition')
                    if definition:
                        thumbs_up = res.get('thumbs_up', "?")
                        nav.add_line(f"```fix\n{definition}\n\n"
                                     f"Ex: {res.get('example', '-')}\n```\n"
                                     f"👍**{int(thumbs_up)}**")
                        nav.add_page_break()

                emb_nav = nav.build(ctx=ctx)
                emb_nav.start()
                sent_navs.append(emb_nav)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, navigators=sent_navs, delete_after=long_delay)

    @commands.command(name='blackwhite', help='Convert a user image to black and white',
                      usage='<member_name or mention>\n\n'
                            'member_name: str or mention, optional - Member mention or name.'
                            'If not given, convert current author of the command\n\n'
                            'Ex: !blackwhite Quancore',
                      aliases=['bw'])
    @commands.cooldown(rate=1, per=1.5, type=commands.BucketType.user)
    @commands.has_any_role(*VALID_STATS_ROLES)
    async def blackwhite(self, ctx, user: Member = None):
        """Turns your avatar or the specified user's avatar black and white"""
        sent_messages = [ctx.message]
        try:
            await ctx.channel.trigger_typing()
            if user is None:
                user = ctx.author
            response = requests.get(user.avatar_url)
            color_image = Image.open(io.BytesIO(response.content))
            bw = color_image.convert('L')
            # prepare the stream to save this image into
            bw_bytes = io.BytesIO()
            # save into the stream, using png format.
            bw.save(bw_bytes, "png")
            # seek back to the start of the stream
            bw_bytes.seek(0)

            msg = await ctx.send(file=File(filename=f"{user.display_name}_bw.png", fp=bw_bytes))
            sent_messages.append(msg)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=long_delay)

    @commands.command(name='rolldice', help='Roll a dice', aliases=['rd'])
    @commands.cooldown(rate=1, per=5, type=commands.BucketType.user)
    # @commands.has_any_role(*VALID_STATS_ROLES)
    async def rolldice(self, ctx):
        """Roll some die"""
        sent_messages = [ctx.message]
        try:
            author = ctx.author
            await ctx.send(f"{author.mention} rolled a {random.randint(1, 6)}!", delete_after=mid_delay)
        finally:
            await helpers.cleanup_messages(ctx.channel, sent_messages, delete_after=mid_delay)

    async def search_tenor(self, ctx, term, limit, **kwargs):
        """ Search and find a gif from Tenor and return url"""
        kwargs['q'] = term
        kwargs['limit'] = max(min(limit, 1), 50)
        kwargs['key'] = TENOR_API_KEY
        search_type = kwargs.get('search_type', 's')
        base_url = self.base_search_tenor_url
        gif_urls = None
        if search_type == 'r':
            base_url = self.base_random_tenor_url
        async with ctx.session.get(url=base_url, params=kwargs) as resp:
            if resp.status == 200:
                json = await resp.json()
                if json and 'results' in json:
                    results = json['results']
                    gif_urls = [result['media'][0]['gif']['url'] for result in results if result]

        return gif_urls

    @commands.command(name='slot', help='Play a slot machine', aliases=['sl', 'bet'],
                      usage='<content_filter>\n\n'
                           'content_filter: string, default o - Content filter. '
                            'Values h for high (no nudity, violence etc.), m for medium (medium filtering)'
                            'l for low (low filtering the content) and o for off (no filter) \n'
                            'Please check for details: https://tenor.com/gifapi/documentation#contentfilter\n'
                           'Ex: !slot\n\n')
    @commands.cooldown(rate=10, per=3600, type=commands.BucketType.user)
    async def slot(self, ctx, *, content_filter: str = 'o'):
        """ Roll the slot machine """
        async def get_random_gif():
            random_gift = random.choice(list(won_gifts.keys()))
            gift_sentence, gif_url = won_gifts.get(random_gift), None
            gift_urls = await self.search_tenor(ctx, random_gift, 50,
                                                media_filter='minimal',
                                                contentfilter=filter_value)
            if gift_urls:
                gif_url = random.choice(gift_urls)

            return gift_sentence, gif_url

        won_gifts = {'kiss': 'you can kiss {} 🤗', 'hug': 'you can hug {} 💏', 'present': 'you received a present from {} 🎁',
                     'dildo': 'you received a dildo from {} 😳', 'like': '{} sent you a super like 👍', 'eggplant': 'you made love with {} 🍆',
                     'love letter': 'you received a love letter from {} 💌', 'strapon': 'you received a strapon from {} 🍌',
                     'sexy panties': 'you received new sexy panties from {} 🩲', 'cat': 'A cat {} has been gifted to you 🐈',
                     '100': '{} give you 💯', 'allah': 'you received ALLAHIN DUASI from {} 🙏🏻', 'Lingerie': 'you received garter from {}',
                     'travel': 'you started a new world tour with {} 🌎'
                     }
        content_filter_map = {'o': 'off', 'l': 'low', 'm': 'medium', 'h': 'high'}
        if content_filter is not None:
            filter_value = content_filter_map.get(content_filter)
            if filter_value is None:
                raise commands.BadArgument('Security level is not valid '
                                           'please use l (low), m (medium) h (high)')

        emojis = "🍎🍊🍐🍋🍉🍇🍓🍒"
        a = random.choice(emojis)
        b = random.choice(emojis)
        c = random.choice(emojis)

        slotmachine = f"**[ {a} {b} {c} ]\n{ctx.author.name}**,"
        random_member = random.choice(tuple(filter(lambda m: m.top_role.name in VALID_STATS_ROLES, ctx.guild.members)))
        res, gif_url = f"{slotmachine} No match, you lost 😢", None
        if a == b == c:
            gift_sentence, gif_url = await get_random_gif()
            res = f"{slotmachine} All matching, you won! 🎉\n {gift_sentence.format(random_member.mention)}"
        elif (a == b) or (a == c) or (b == c):
            gift_sentence, gif_url = await get_random_gif()
            res = f"{slotmachine} 2 in a row, you won! 🎉 \n {gift_sentence.format(random_member.mention)}"

        embed_dict = {'description': res}
        e = CustomEmbed.from_dict(embed_dict, is_thumbnail=False, author_name=ctx.author)
        e.set_image(url=gif_url)
        return await ctx.send(embed=e)


def setup(bot):
    bot.add_cog(Fun(bot))